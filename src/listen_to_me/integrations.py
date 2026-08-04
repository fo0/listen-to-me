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

pynput is imported lazily inside the methods so importing this module (and the
rest of the app) stays cheap and never needs an X display until a mute target
is actually enabled and a recording starts.
"""

from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger(__name__)


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
    main thread on every recording edge; a lock still guards the held-key
    bookkeeping in case a shutdown ``reset`` races them.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self._controller = None
        # pynput keys currently held down (hold-mode targets), in press order.
        self._held: list = []
        # Key lists of toggle-mode targets tapped on start, to re-tap on stop.
        self._toggles: list[list] = []
        self._active = False
        self._lock = threading.Lock()

    # ------------------------------------------------------- config helpers

    def _settings(self) -> dict:
        value = self.cfg.data.get("integrations")
        return value if isinstance(value, dict) else {}

    def _active_targets(self) -> list[dict]:
        """Enabled targets with a non-empty keybind, or [] when the master
        switch is off. Read fresh each time so Settings changes take effect on
        the next recording without any reload step."""
        settings = self._settings()
        if not settings.get("mute_while_recording", True):
            return []
        targets = []
        for target in settings.get("targets") or []:
            if not isinstance(target, dict) or not target.get("enabled"):
                continue
            if (target.get("hotkey") or "").strip():
                targets.append(target)
        return targets

    # ------------------------------------------------------------ lifecycle

    def on_recording_start(self) -> None:
        """Activate every enabled target's mute keybind. No-op (and no pynput
        import) when nothing is configured."""
        targets = self._active_targets()
        if not targets:
            return
        with self._lock:
            if self._active:
                return
            try:
                from pynput.keyboard import Controller, HotKey, KeyCode
            except Exception:
                log.exception("mute integration: pynput unavailable — skipping")
                return
            self._active = True
            self._held = []
            self._toggles = []
            if self._controller is None:
                self._controller = Controller()

            activated = 0
            for target in targets:
                name = target.get("name") or "target"
                try:
                    combo = (target.get("hotkey") or "").strip()
                    keys = _synth_keys(HotKey.parse(combo), KeyCode)
                except (ValueError, KeyError):
                    log.warning(
                        "mute integration: invalid keybind %r for %s — skipping",
                        target.get("hotkey"), name,
                    )
                    continue
                mode = "toggle" if target.get("mode") == "toggle" else "hold"
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
            if activated == 0 and not self._held and not self._toggles:
                # Nothing was actually sent (all targets failed to parse/press):
                # drop back to inactive so a later stop won't try to undo it.
                self._active = False
            else:
                log.info("mute integration: activated %d target(s) for recording", activated)

    def on_recording_stop(self) -> None:
        """Undo whatever ``on_recording_start`` did: release held keys and
        re-tap toggle keybinds. Safe to call when inactive."""
        with self._lock:
            if not self._active:
                return
            self._active = False
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

    def reset(self) -> None:
        """Release anything still held — used on shutdown so a quit mid-record
        never leaves a target application stuck muted."""
        self.on_recording_stop()

    # --------------------------------------------------------------- helpers

    def _tap(self, keys) -> None:
        """Press then release a full combination once (modifiers released last)."""
        for key in keys:
            self._controller.press(key)
        for key in reversed(keys):
            self._controller.release(key)
