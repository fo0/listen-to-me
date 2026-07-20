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
import threading

log = logging.getLogger(__name__)


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
                from pynput.keyboard import Controller, HotKey
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
                    keys = HotKey.parse((target.get("hotkey") or "").strip())
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
