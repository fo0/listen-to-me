"""Insert text at the current cursor position of the focused window."""

from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger(__name__)

# Windows virtual-key codes of the keys that turn a typed character into a
# chord/shortcut when physically held: Shift, Ctrl, Alt, LWin, RWin.
_WIN32_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)


def sanitize_typed_text(text: str) -> str:
    """Reduce `text` to plain typeable characters.

    Every whitespace run (including newlines and tabs) becomes a single space
    and all other non-printable characters are dropped, so simulated typing can
    only ever produce visible text — never an Enter (which could submit a chat
    message or form) or a Tab (which could move the focus away mid-dictation).
    """
    cleaned = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(cleaned.split())


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


class Injector:
    def __init__(self, cfg):
        self.cfg = cfg

    def insert(self, text: str) -> None:
        if not text:
            return
        if self.cfg["injection_mode"] == "type":
            self._type(text)
        else:
            self._paste(text)
        log.info("inserted %d chars via %s", len(text), self.cfg["injection_mode"])

    def _type(self, text: str) -> None:
        from pynput.keyboard import Controller

        Controller().type(text)

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

    def _paste(self, text: str) -> None:
        import pyperclip
        from pynput.keyboard import Controller, Key

        previous = None
        if self.cfg["restore_clipboard"]:
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = None

        pyperclip.copy(text)
        time.sleep(0.15)  # give the clipboard time to settle

        keyboard = Controller()
        modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        with keyboard.pressed(modifier):
            keyboard.press("v")
            keyboard.release("v")

        if previous is not None:
            time.sleep(0.3)  # let the target application read the clipboard first
            try:
                pyperclip.copy(previous)
            except Exception:
                log.debug("could not restore clipboard", exc_info=True)
