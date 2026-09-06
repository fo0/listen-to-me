"""Mute other applications (Discord, Teams, OBS, …) while dictating.

When a recording is running your dictation would otherwise be picked up by an
open voice call. For the duration of the recording this module synthesizes the
global mute keybind of each configured target application, so you are muted
there *exactly* while you speak to Listen To Me — and restored the moment the
recording stops.

It is deliberately application-agnostic: it works with anything that offers a
global mute / push-to-mute keybind. You configure the *same* key combination
here and in that app's keybind settings — no API, OAuth or vendor whitelisting
is needed, so it also covers apps that expose no control API at all.

Two per-target modes:

- ``hold``   — press the keybind when recording starts and release it when it
  stops. Matches a *push-to-mute* keybind: stateless and self-correcting, so it
  can never leave the target stuck muted. Recommended.
- ``toggle`` — tap the keybind once on start and once on stop. Matches a
  *toggle-mute* keybind, but can desync if the target is toggled by hand in
  between.

The synthesized keys are picked up by the target's *global* keybind hook (that
is why it works regardless of which window is focused), so the combination
should be one that is inert in ordinary text fields — a modifier chord or a
function key, exactly like the app's own recording hotkey.

That hook sees one shared keyboard state, which is why the keybind is not sent
the instant a recording starts: at that moment the *recording hotkey* is still
physically held (it is what just started the recording), and every key of it is
part of the state the target reads. A recording hotkey of Ctrl+Alt+Space turns
a Ctrl+Shift+M mute keybind into Ctrl+Alt+Shift+M on the way out, and releasing
it a moment later pulls the shared Ctrl out from under the keybind again. So
each combination waits for the keyboard to go quiet first — see
``_wait_for_quiet_modifiers``.

That wait cannot succeed while the recording hotkey is in *hold* mode: the
hotkey stays down for the whole take, so a toggle-mode keybind would be tapped
straight through it — widened by the held modifiers, and with its release
landing on the app's own hold listener, which reads a shared modifier going up
as the user letting go and ends the recording. Such targets are skipped for
the take instead, with a notification saying why — see
``_hold_mode_skip_reason``.

pynput is imported lazily inside the methods so importing this module (and the
rest of the app) stays cheap and never needs an X display until a mute target
is actually enabled and a recording starts.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger(__name__)

# How long a keybind waits for the recording hotkey to be let go before it is
# sent anyway. A tap is over in well under 100 ms; the ceiling exists for a
# hold-mode recording hotkey, which stays down for the whole take — muting late
# and imperfectly still beats not muting at all.
_SETTLE_TIMEOUT_S = 1.0
# The per-target modes a stored target may name — anything else is a hand-edit
# gone wrong, not a third mode.
_TARGET_MODES = ("hold", "toggle")
# How long a tapped combination stays down. A press and release in the same
# instant is a chord no one can observe: a target that samples the keyboard
# rather than hooking every event can fall straight through the gap.
_TAP_HOLD_S = 0.03


def _char_vk(char: str) -> int | None:
    """The virtual-key code that carries `char` on the active keyboard layout,
    or None when it can't be determined (not Windows, or an unmappable char).

    Only the key matters here, not the character it would type: which modifiers
    the layout needs to reach `char` is deliberately ignored, because the
    modifiers of a keybind come from the combination itself.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        scan = ctypes.windll.user32.VkKeyScanW
        scan.argtypes = [ctypes.c_wchar]
        scan.restype = ctypes.c_short
        result = scan(char)
    except Exception:
        log.debug("could not map %r to a virtual key", char, exc_info=True)
        return None
    if result == -1:  # the character is not reachable on this layout
        return None
    return (result & 0xFF) or None


def _wait_for_quiet_modifiers(timeout: float = _SETTLE_TIMEOUT_S) -> bool:
    """Block until no modifier key is physically held, or `timeout` passes.
    True when the keyboard went quiet, False when it timed out.

    A mute keybind is read out of the *shared* keyboard state, so anything the
    user still holds is part of the combination the target application sees.
    The recording hotkey is always exactly that: it is what just started the
    recording, so its keys are down at the moment the keybind would go out.
    With the default Ctrl+Alt+Space that costs the keybind twice over — the
    stray Alt makes Ctrl+Shift+M arrive as Ctrl+Alt+Shift+M, and letting go of
    the shared Ctrl a moment later releases it right back out of the keybind
    the app is holding down.

    Waiting for the hotkey to be released is what makes the difference between
    a chord the target matches and one it doesn't; the cost is the few dozen
    milliseconds it takes to lift a finger. AutoHotkey solves the same problem
    the other way round, by releasing held modifiers itself and pressing them
    back afterwards — which is right for a synchronous Send, but here it would
    mean synthesizing releases for keys the user is still holding, and a
    hold-mode recording hotkey would read its own modifier going up as "the
    user let go" and stop the recording.

    Off Windows `modifiers_down()` can't poll the physical state and reports
    False, so this returns at once and behaves exactly as before.

    The polling itself lives in ``injector.wait_for_quiet_modifiers`` — the
    paste and typing paths wait for the very same reason; this wrapper only
    adds the mute-specific log line.
    """
    from .injector import wait_for_quiet_modifiers

    if wait_for_quiet_modifiers(timeout):
        return True
    log.info(
        "mute integration: modifier still held after %.1fs — sending the "
        "keybind anyway; it may reach the target as a wider combination",
        timeout,
    )
    return False


def target_problem(target) -> str | None:
    """Why a stored mute target cannot be used, or None when its shape is sound.

    The targets list is stored wholesale, so ``config._coerce`` never looks
    inside it — a hand-edited ``"hotkey": 120`` used to raise
    ``AttributeError`` on ``.strip()`` inside ``_active_targets``, on *every*
    state change, and because that read every target at once, one broken entry
    silenced all of them. Pure so the rule is checkable without pynput.
    """
    if not isinstance(target, dict):
        return "not an object"
    if not isinstance(target.get("enabled"), bool):
        return '"enabled" is not true/false'
    if not isinstance(target.get("name", ""), str):
        return '"name" is not text'
    if not isinstance(target.get("hotkey"), str):
        return '"hotkey" is not text'
    if target.get("mode") not in _TARGET_MODES:
        return '"mode" is not "hold" or "toggle"'
    return None


def _hold_mode_skip_reason(
    hotkey_keys: set, hotkey_has_modifier: bool, keybind_keys, mode: str
) -> str | None:
    """Why a mute keybind must not go out while a *hold-mode* recording hotkey is
    held, or None when it is safe to send. Pure: the parsed hotkey keys and
    ``Hotkeys.combo_flags``' modifier verdict come in, no pynput is touched.

    Only toggle-mode targets are affected — a tap presses AND releases every
    key of its chord while the hotkey is still down:

    - A key shared with the hotkey (the default Ctrl+Alt+Space next to
      Discord's Ctrl+Shift+M share Ctrl) is released by the tap, and the hold
      listener (``hotkeys.Hotkeys._handle_release``) cannot tell a synthesized
      release from the user's — the recording ends a second after it started.
    - A chord sharing no key is still tapped underneath the hotkey's held
      modifiers and reaches the target widened (Shift+M arrives as
      Ctrl+Alt+Shift+M), so it does not match either. Only a hotkey without
      modifiers (e.g. <f9>) leaves the chord as configured.

    A hold-mode target only presses at start and releases at stop — after the
    recording has already ended — so it keeps working in either case. This is
    the mute-side twin of ``App._live_typing_gate``, which keeps live typing
    off in hold mode for the same shared-keyboard reason.
    """
    if mode != "toggle":
        return None
    if hotkey_keys.intersection(keybind_keys):
        return "its shortcut shares keys with the recording hotkey"
    if hotkey_has_modifier:
        return "its shortcut would be tapped while the recording hotkey's modifier keys are held"
    return None


def _synth_keys(keys: list, key_code_cls) -> list:
    """`keys` (one parsed pynput combination) with every character key replaced
    by its virtual-key equivalent, so the combination can be synthesized as
    real key events.

    `HotKey.parse` yields character keys as char-only `KeyCode`s — no vk — and
    pressing one of those through a `Controller` that already holds Shift goes
    wrong in two steps on Windows:

    1. `Controller._resolve` uppercases the character while the controller's
       own Shift is down ("m" → "M"), because that is what the key would type.
    2. "M" is not reachable without a modifier, so the Windows backend stops
       emitting a key event and injects the character as a Unicode packet
       (`KEYBDINPUT.UNICODE`, `wVk=0`) instead.

    A Unicode packet carries text, not a key: the low-level keyboard hook that
    Discord/Teams/OBS use for their global keybinds never sees VK_M, so the
    target is never muted — and because the packet bypasses the held modifiers
    entirely, the character lands as literal text in whatever field has focus.
    Discord's default mute keybind is Ctrl+Shift+M, so the most common setup of
    all hit both halves at once, while the shipped `<f9>` preset (parsed to a
    vk already) never did.

    A vk-carrying KeyCode has no `char` for `_resolve` to uppercase and the
    backend emits an ordinary key event, indistinguishable from the physical
    key press the target application is waiting for. Only Windows needs the
    substitution and only Windows offers the layout lookup; elsewhere pynput
    maps the character through the layout itself when sending, so an
    unsubstituted key is passed through unchanged rather than dropped.
    """
    prepared = []
    for key in keys:
        # Modifiers parse to Key members, which carry no .char at all.
        char = getattr(key, "char", None)
        if char and getattr(key, "vk", None) is None:
            vk = _char_vk(char)
            if vk is not None:
                key = key_code_cls.from_vk(vk)
        prepared.append(key)
    return prepared


class MuteIntegrations:
    """Drives the configured mute keybinds around a recording.

    ``on_recording_start`` / ``on_recording_stop`` are called from the app's
    main thread on every recording edge and return immediately: the keys go out
    on a short-lived worker, which first waits for the recording hotkey to be
    released (see ``_wait_for_quiet_modifiers``). The main thread must not do
    that waiting itself — it owns the tray, the overlay and the start beep, and
    the user needs those the moment the recording starts.

    ``_generation`` is what keeps the workers honest. Every edge bumps it, and
    a worker re-checks it after its wait and before touching a key: a keybind
    whose recording is already over must not still be pressed, and a stop that
    was overtaken by the next recording must not undo it. ``_lock`` guards the
    counter and the held-key bookkeeping together, so a worker that passes the
    check holds the lock all the way through its key sequence.
    """

    def __init__(self, cfg: Config, notify: Callable[[str], None] | None = None):
        self.cfg = cfg
        # Thread-safe user notification (App.notify posts to the main thread);
        # None keeps the module usable in the selftest without an App.
        self._notify = notify
        self._controller = None
        # pynput keys currently held down (hold-mode targets), in press order.
        self._held: list = []
        # Key lists of toggle-mode targets tapped on start, to re-tap on stop.
        self._toggles: list[list] = []
        self._active = False
        self._generation = 0
        self._lock = threading.Lock()
        # Once-per-session latches: a broken target is read on every state
        # change and a hold-mode conflict on every take — repeating either
        # would bury the log and nag before every dictation.
        self._malformed_reported: set[int] = set()
        self._malformed_notified = False
        self._hold_mode_skipped: set[str] = set()

    # ------------------------------------------------------- config helpers

    def _settings(self) -> dict:
        value = self.cfg.data.get("integrations")
        return value if isinstance(value, dict) else {}

    def _active_targets(self) -> list[dict]:
        """Enabled targets with a non-empty keybind, or [] when the master
        switch is off. Read fresh each time so Settings changes take effect on
        the next recording without any reload step."""
        settings = self._settings()
        # Default False, matching config.DEFAULTS: this feature synthesizes
        # keystrokes into other applications and is opt-in for that reason, so
        # a settings section that lost the key (an older build, a hand-edit, a
        # truncated file) must leave it off rather than switch it on.
        if not settings.get("mute_while_recording", False):
            return []
        targets = []
        stored = settings.get("targets")
        for index, target in enumerate(stored if isinstance(stored, list) else []):
            if isinstance(target, dict) and target.get("enabled") is False:
                continue  # off — whatever else is in there does nothing
            problem = target_problem(target)
            if problem is not None:
                self._report_malformed(index, target, problem)
                continue
            if target["hotkey"].strip():
                targets.append(target)
        return targets

    def _report_malformed(self, index: int, target, problem: str) -> None:
        """Say once per session that a stored target was skipped for its shape.

        Skipping alone would be the silent no-op the user cannot see: the
        Integrations page shows the entry, the master switch is on, and the
        target simply never mutes.
        """
        label = f"#{index + 1}"
        if isinstance(target, dict) and isinstance(target.get("name"), str) and target["name"]:
            label += f" ({target['name']})"
        if index not in self._malformed_reported:
            self._malformed_reported.add(index)
            log.warning(
                "mute integration: target %s in config.json is malformed (%s) — skipping it",
                label, problem,
            )
        if not self._malformed_notified and self._notify is not None:
            self._malformed_notified = True
            self._notify(
                f"Mute target {label} in config.json is malformed ({problem}) and was "
                "skipped — fix it under Settings → Integrations."
            )

    # ------------------------------------------------------------ lifecycle

    def on_recording_start(self) -> None:
        """Activate every enabled target's mute keybind. Returns immediately —
        the keys go out on a worker once the recording hotkey has been let go.
        No-op (and no pynput import) when nothing is configured."""
        targets = self._active_targets()
        if not targets:
            return
        with self._lock:
            if self._active:
                return
            self._active = True
            generation = self._bump()
        self._spawn(self._activate, generation, targets)

    def on_recording_stop(self) -> None:
        """Undo whatever ``on_recording_start`` did: release held keys and
        re-tap toggle keybinds. Safe to call when inactive.

        Deferred exactly like the activation, and for the same reason: the
        recording hotkey that just stopped the take is still held, and a toggle
        keybind tapped through it would miss the target and leave it muted.
        """
        with self._lock:
            if not self._active:
                return
            self._active = False
            generation = self._bump()
        self._spawn(self._deactivate, generation)

    def reset(self) -> None:
        """Release anything still held — used on shutdown so a quit mid-record
        never leaves a target application stuck muted.

        Runs on the calling thread and skips the settle wait, unlike every
        other path here: shutdown must not hand its last keystrokes to a daemon
        thread the interpreter is about to tear down. A keybind that reaches the
        target as a wider combination is a bad unmute; one that is never sent at
        all is a target stuck muted after the app is gone.
        """
        with self._lock:
            self._active = False
            generation = self._bump()
        self._deactivate(generation, settle=False)

    # ------------------------------------------------------------- internals

    def _bump(self) -> int:
        """Invalidate any worker still in flight and return the new generation.
        Caller holds self._lock."""
        self._generation += 1
        return self._generation

    def _spawn(self, work, *args) -> None:
        """Run `work` on a short-lived daemon thread, under the log guard the
        Qt main thread used to provide.

        Moving the keys onto a worker moved them out of the try/except in
        `App._set_state`, and a thread that dies of an unhandled exception only
        reaches `threading.excepthook` — which writes to stderr, and a
        `--windowed` build has none. The failure would leave no trace at all:
        no log line, no notification, a target simply never muted.
        """

        def guarded() -> None:
            try:
                work(*args)
            except Exception:
                log.exception("mute integration: the keybind worker failed")

        threading.Thread(target=guarded, name="mute-keybind", daemon=True).start()

    def _claim(self, generation: int):
        """Take the lock for `generation`, or return None if it was superseded.

        The caller must release the lock. Checking and acting have to happen
        under the same acquisition: a stop that slipped in between would find
        the bookkeeping empty and leave the target muted for good.
        """
        self._lock.acquire()
        if generation != self._generation:
            self._lock.release()
            log.debug("mute integration: keybind superseded before it was sent")
            return None
        return self._lock

    def _activate(self, generation: int, targets: list) -> None:
        """Worker: wait out the recording hotkey, then send every mute keybind."""
        try:
            from pynput.keyboard import Controller, HotKey, KeyCode
        except Exception:
            log.exception("mute integration: pynput unavailable — skipping")
            return
        _wait_for_quiet_modifiers()
        lock = self._claim(generation)
        if lock is None:
            return
        try:
            if self._controller is None:
                self._controller = Controller()

            if self._held or self._toggles:
                # This recording overtook the previous stop before its worker
                # got to run. Undo that one here — clearing the bookkeeping
                # instead would strand keys in the down position forever.
                log.info("mute integration: undoing a stop this recording overtook")
                self._undo()

            hold_hotkey = self._hold_mode_hotkey(HotKey)
            activated = skipped = 0
            sent: list[set] = []
            for target in targets:
                name = target.get("name") or "target"
                try:
                    combo = (target.get("hotkey") or "").strip()
                    parsed = HotKey.parse(combo)
                    keys = _synth_keys(parsed, KeyCode)
                except (ValueError, KeyError):
                    log.warning(
                        "mute integration: invalid keybind %r for %s — skipping",
                        target.get("hotkey"), name,
                    )
                    continue
                mode = "toggle" if target.get("mode") == "toggle" else "hold"
                if hold_hotkey is not None:
                    # GUARD, not the fix. The full fix is (a) a pynput
                    # win32_event_filter that drops LLKHF_INJECTED events while
                    # a tap is in flight, so our own release never reaches the
                    # hold listener, plus (b) releasing and re-pressing the
                    # extra held modifiers around the tap so the chord arrives
                    # unwidened — both Windows-only and untested here, hence
                    # the skip-and-say-why for now.
                    reason = _hold_mode_skip_reason(hold_hotkey[0], hold_hotkey[1], parsed, mode)
                    if reason is not None:
                        self._skip_in_hold_mode(name, reason)
                        skipped += 1
                        continue
                if any(set(keys) == already for already in sent):
                    # Several apps can listen for the same combination — Discord
                    # and Teams both default to Ctrl+Shift+M. One press reaches
                    # all of them, so sending it per target would toggle each app
                    # twice and leave every one of them exactly as it was.
                    log.info(
                        "mute integration: %s shares its keybind with an earlier "
                        "target — sending the combination once", name,
                    )
                    continue
                sent.append(set(keys))
                try:
                    if mode == "hold":
                        for key in keys:
                            self._controller.press(key)
                            self._held.append(key)
                    else:
                        self._tap(keys)
                        self._toggles.append(keys)
                    activated += 1
                except Exception:
                    log.exception("mute integration: could not activate %s", name)
            log.info(
                "mute integration: activated %d target(s) for recording%s",
                activated,
                f" ({skipped} skipped in hold mode)" if skipped else "",
            )
        finally:
            lock.release()

    def _hold_mode_hotkey(self, hotkey_cls) -> tuple[set, bool] | None:
        """(parsed keys, has_modifier) of the recording hotkey while it runs in
        hold mode — the keys that are necessarily held for the whole take.
        None in toggle mode (the hotkey is let go before any keybind goes out)
        and for a combo that does not parse (nothing was registered, so
        nothing is held)."""
        if self.cfg["hotkey_mode"] != "hold":
            return None
        combo = str(self.cfg["hotkey"] or "")
        try:
            keys = set(hotkey_cls.parse(combo))
        except (ValueError, KeyError):
            return None
        from .hotkeys import Hotkeys

        has_modifier, _has_typable = Hotkeys.combo_flags(combo)
        return keys, has_modifier

    def _skip_in_hold_mode(self, name: str, reason: str) -> None:
        """Log and notify — once per target and session — that a toggle keybind
        was not sent because the hold-mode recording hotkey would corrupt it.
        Once, because this fires on every take until the user changes either
        the hotkey or the target's mode, and the fix is a settings change."""
        if name in self._hold_mode_skipped:
            log.debug("mute integration: %s skipped again in hold mode", name)
            return
        self._hold_mode_skipped.add(name)
        log.warning(
            "mute integration: mute for %s is skipped in hold mode — %s; use a "
            "hotkey without modifiers (e.g. <f9>) or toggle mode",
            name, reason,
        )
        if self._notify is not None:
            self._notify(
                f"Mute for {name} is skipped in hold mode: {reason} — use a hotkey "
                "without modifiers (e.g. <f9>) or toggle mode."
            )

    def _deactivate(self, generation: int, settle: bool = True) -> None:
        """Worker: release held keybinds and re-tap toggle ones."""
        if settle:
            _wait_for_quiet_modifiers()
        lock = self._claim(generation)
        if lock is None:
            return
        try:
            self._undo()
        finally:
            lock.release()

    def _undo(self) -> None:
        """Put every activated keybind back. Caller holds self._lock."""
        if self._controller is None:
            return
        # Release hold-mode keys in reverse press order (modifiers last).
        for key in reversed(self._held):
            try:
                self._controller.release(key)
            except Exception:
                log.debug("mute integration: release failed", exc_info=True)
        self._held = []
        # Re-tap toggle-mode keybinds to switch mute back off.
        for keys in self._toggles:
            try:
                self._tap(keys)
            except Exception:
                log.exception("mute integration: could not deactivate toggle target")
        self._toggles = []

    # --------------------------------------------------------------- helpers

    def _tap(self, keys) -> None:
        """Press then release a full combination once (modifiers released last),
        holding it briefly so the target has a chord it can actually observe."""
        for key in keys:
            self._controller.press(key)
        time.sleep(_TAP_HOLD_S)
        for key in reversed(keys):
            self._controller.release(key)
