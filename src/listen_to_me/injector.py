"""Insert text at the current cursor position of the focused window."""

from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

from .choices import clipboard_copy_mode

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger(__name__)

# Windows virtual-key codes of the keys that turn a typed character into a
# chord/shortcut when physically held: Shift, Ctrl, Alt, LWin, RWin.
_WIN32_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)

# How often wait_for_quiet_modifiers() re-polls the physical modifier state.
_SETTLE_POLL_S = 0.01
# How long a finished transcript waits for the stop-hotkey chord to be let go
# before Ctrl+V / simulated typing is refused. Releasing a chord takes tens of
# milliseconds; a modifier held for seconds means the user is doing something
# else with the keyboard, and a chord sent into that fires whatever shortcut
# it completes there.
_INSERT_SETTLE_TIMEOUT_S = 2.0


class ModifierHeldError(RuntimeError):
    """Raised by the insertion paths when a modifier key stayed physically held
    past the settle timeout, so no chord or keystroke was sent. The transcript
    is on the clipboard (paste mode) or still in the caller's hands (type
    mode); ``App._insert_transcript`` turns this into the forced "press Ctrl+V /
    see History" notification."""


def sanitize_typed_text(text: str) -> str:
    """Reduce `text` to plain typeable characters.

    Every whitespace run (including newlines and tabs) becomes a single space
    and all other non-printable characters are dropped, so simulated typing can
    only ever produce visible text — never an Enter (which could submit a chat
    message or form) or a Tab (which could move the focus away mid-dictation).
    """
    cleaned = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(cleaned.split())


def _clip_text_equal(stored: str | None, text: str) -> bool:
    """Whether a clipboard read-back matches `text`.

    Windows hands back \\r\\n for the \\n that went in — compare normalized.
    """
    return (stored or "").replace("\r\n", "\n") == text.replace("\r\n", "\n")


def modifiers_down() -> bool:
    """Best-effort check whether a modifier key is physically held right now.

    Used to pause simulated typing so an injected character can never combine
    with a held Ctrl/Alt/Shift/Win into an accidental shortcut (e.g. the user
    still holding the recording hotkey chord). Only Windows offers a cheap
    poll (GetAsyncKeyState); elsewhere this returns False and the hold-mode
    gate in app._live_typing_gate() is the protection instead.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _WIN32_MODIFIER_VKS)
    except Exception:
        log.debug("modifier state poll failed", exc_info=True)
        return False


def wait_for_quiet_modifiers(timeout: float, poll: float = _SETTLE_POLL_S) -> bool:
    """Block until no modifier key is physically held, or `timeout` passes.
    True when the keyboard went quiet, False when it timed out.

    Shared by every injection that sends a chord into the *shared* keyboard
    state: Ctrl+V for a paste, simulated typing, and the mute keybinds of
    ``integrations.py``. Whatever the user still holds — typically the
    recording hotkey that just started or stopped the take — is part of the
    combination the focused application sees, so a chord sent underneath it
    is a different chord (Ctrl+Alt+V instead of Ctrl+V), and typed text turns
    into shortcuts. Waiting the few dozen milliseconds it takes to lift a
    finger is what makes the difference; the ceiling keeps a caller from
    hanging on a key held for other reasons.

    AutoHotkey solves the same problem by releasing held modifiers itself and
    pressing them back afterwards. Not here: a hold-mode recording hotkey
    would read its own modifier going up as "the user let go" and stop the
    recording (see ``integrations.py``).

    Off Windows ``modifiers_down()`` can't poll the physical state and reports
    False, so this returns at once — behaviour there is unchanged.
    """
    deadline = time.monotonic() + timeout
    while modifiers_down():
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)
    return True


class Injector:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def clipboard_mode(self) -> str:
        """The configured clipboard policy: "off", "on_failure" or "always"."""
        return clipboard_copy_mode(self.cfg["clipboard_copy"])

    def insert(self, text: str) -> bool:
        """Insert `text` at the cursor of whatever window has focus.

        Paste mode falls back to simulated typing when the clipboard can't be
        used (no clipboard backend on this platform, or another application
        holding it open): the transcript already exists at that point, so
        dropping it because a clipboard write failed would be the worst
        possible outcome. Only a failure of both paths propagates.

        Returns whether the transcript is on the clipboard afterwards — either
        because paste mode left it there or because `clipboard_copy = "always"`
        put it there on purpose.

        Raises ``ModifierHeldError`` when a modifier key stayed physically held
        past the settle timeout on either path: the chord or keystrokes were
        not sent, and typing is no fallback for that (it would run into the
        same held key). The caller reports where the text can be recovered.
        """
        if not text:
            return False
        keep = self.clipboard_mode() == "always"
        mode = self.cfg["injection_mode"]
        on_clipboard = False
        if mode == "type":
            self._type(text)
        else:
            try:
                on_clipboard = self._paste(text, keep=keep)
            except ModifierHeldError:
                raise
            except Exception:
                log.exception("clipboard paste failed — falling back to typing")
                self._type(text)
                mode = "type (clipboard unavailable)"
        if keep and not on_clipboard:
            # Typing mode, or a paste that fell back to it: the option promises
            # the clipboard copy independently of how the text got inserted.
            on_clipboard = self.copy_to_clipboard(text)
        log.info(
            "inserted %d chars via %s%s",
            len(text),
            mode,
            " (kept on the clipboard)" if on_clipboard else "",
        )
        return on_clipboard

    def copy_to_clipboard(self, text: str) -> bool:
        """Put `text` on the clipboard and confirm it arrived; True when it did.

        The worker-thread twin of `qtutil.copy_to_clipboard`: this runs on the
        processing thread, so it must never touch Qt — pyperclip only, no
        QApplication fallback. The write is read back because a successful
        `copy()` only means the call returned: another application can own or
        overwrite the clipboard in the same moment, and a clipboard that
        silently didn't take the transcript is exactly the failure this option
        exists to prevent — the caller tells the user which it was.
        """
        if not text:
            return False
        try:
            import pyperclip

            pyperclip.copy(text)
            stored = pyperclip.paste()
        except Exception:
            log.exception("could not copy the transcript to the clipboard")
            return False
        if not _clip_text_equal(stored, text):
            log.warning("the clipboard did not take the transcript (%d chars)", len(text))
            return False
        return True

    def _type(self, text: str) -> None:
        from pynput.keyboard import Controller

        # Typed under a held Ctrl/Alt/Win every character is a shortcut in the
        # focused window; the live-typing path (type_plain) pauses for the same
        # reason. Refusing is the only safe outcome once the wait runs out.
        if not wait_for_quiet_modifiers(_INSERT_SETTLE_TIMEOUT_S):
            log.warning(
                "modifier key still held after %.1fs — %d chars not typed",
                _INSERT_SETTLE_TIMEOUT_S, len(text),
            )
            raise ModifierHeldError("a modifier key was held down")
        # pynput maps \n and \t to real Enter/Tab presses — in a chat box or a
        # terminal that submits instead of typing. Whisper output is flat, but
        # assistant output arrives verbatim, so every simulated-typing path
        # gets the sanitized text; pasting is unaffected (a pasted newline
        # presses no key).
        Controller().type(sanitize_typed_text(text))

    def type_plain(self, text: str) -> str:
        """Type already-sanitized plain text word by word, re-checking the
        physical modifier state between words. Stops as soon as a modifier is
        held and returns the untyped remainder ("" when everything went out) —
        the caller retries later. This is the only insertion path live typing
        uses: no clipboard, no chords, only printable characters.
        """
        if not text:
            return ""
        from pynput.keyboard import Controller

        keyboard = Controller()
        words = text.split(" ")
        for i, word in enumerate(words):
            if modifiers_down():
                rest = " ".join(words[i:])
                log.info("typing paused (%d chars pending) — modifier key held", len(rest))
                return rest
            keyboard.type(word + (" " if i < len(words) - 1 else ""))
        return ""

    def type_plain_blocking(self, text: str, timeout: float = 10.0) -> str:
        """type_plain(), but wait for held modifiers to be released — used for
        the final flush after a recording, where the user may still hold the
        stop-hotkey chord for a moment. Gives up after `timeout` seconds and
        returns the untyped remainder: typing despite a held modifier could
        fire shortcuts in whatever has focus by then (a modifier held that
        long means the user is doing something else entirely), so the caller
        reports the loss instead — the transcript is already in the history.
        """
        deadline = time.monotonic() + timeout
        rest = text
        while rest:
            rest = self.type_plain(rest)
            if not rest:
                return ""
            if time.monotonic() >= deadline:
                log.warning(
                    "modifier still held after %.0fs — %d chars left untyped", timeout, len(rest)
                )
                return rest
            time.sleep(0.05)
        return ""

    def _paste(self, text: str, keep: bool = False) -> bool:
        """Copy the text, send Ctrl+V, restore the previous clipboard content.

        Returns whether the transcript is still on the clipboard when this
        returns. `keep` (clipboard_copy = "always") suppresses the restore:
        putting the old content back would undo exactly what that option
        promises, so the two settings must not fight over the clipboard.
        """
        import pyperclip
        from pynput.keyboard import Controller, Key

        previous = None
        if self.cfg["restore_clipboard"] and not keep:
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = None

        pyperclip.copy(text)
        time.sleep(0.15)  # give the clipboard time to settle

        # The chord goes into the shared keyboard state: with the stop hotkey
        # still held, Ctrl+V arrives as Ctrl+Alt+V (or whatever the hotkey
        # adds) and pastes nothing — or triggers something else. Every other
        # injection path already waits for the keys to be let go; this one
        # sent the chord blind.
        if not wait_for_quiet_modifiers(_INSERT_SETTLE_TIMEOUT_S):
            log.warning(
                "modifier key still held after %.1fs — Ctrl+V not sent, the "
                "transcript stays on the clipboard",
                _INSERT_SETTLE_TIMEOUT_S,
            )
            if previous is not None and self.clipboard_mode() == "off":
                # "off" promises that dictated text never lingers on the
                # clipboard: put the old content back exactly as a completed
                # paste would have. Every other policy leaves the transcript
                # there — it is the recovery the caller points the user at.
                try:
                    pyperclip.copy(previous)
                except Exception:
                    log.debug("could not restore clipboard", exc_info=True)
            raise ModifierHeldError("a modifier key was held down")

        keyboard = Controller()
        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        with keyboard.pressed(modifier):
            keyboard.press("v")
            keyboard.release("v")

        time.sleep(0.3)  # let the target application read the clipboard first
        if previous:
            try:
                still_ours = _clip_text_equal(pyperclip.paste(), text)
            except Exception:
                log.debug("clipboard read-back failed", exc_info=True)
                return False
            if not still_ours:
                # Another application grabbed the clipboard meanwhile — it
                # owns it now; restoring would clobber a copy the user made.
                return False
            try:
                # Restore only while the clipboard still holds our transcript.
                pyperclip.copy(previous)
                return False
            except Exception:
                # The read-back above proved the transcript IS still there —
                # a failed restore must not hide that recovery from the user.
                log.debug("could not restore clipboard", exc_info=True)
                return True
        if previous == "" and self.clipboard_mode() == "off":
            # Restore was configured but the old content was non-text
            # (pyperclip reads images/files as ""), so there is nothing to put
            # back — yet "off" is the explicit promise that dictated text
            # never lingers on the clipboard, so scrub it like the restore
            # would have. Only while the clipboard is still ours, same as the
            # restore branch above.
            try:
                still_ours = _clip_text_equal(pyperclip.paste(), text)
            except Exception:
                log.debug("clipboard read-back failed", exc_info=True)
                return False
            if not still_ours:
                return False
            try:
                pyperclip.copy("")
            except Exception:
                log.debug("could not clear the clipboard", exc_info=True)
                return True  # scrub failed — the transcript is still there
            return False
        # No restore (keep requested, restoring disabled, or empty previous in
        # a keep-friendly mode): read the write back before the caller
        # promises a working Ctrl+V.
        try:
            return _clip_text_equal(pyperclip.paste(), text)
        except Exception:
            log.debug("clipboard read-back failed", exc_info=True)
            return False
