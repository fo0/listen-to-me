"""Global hotkey registration via pynput.

Two modes:
- "toggle": the classic behaviour — the combo fires once per press.
- "hold":   true push-to-talk — on_press fires when the full combo goes down,
            on_release fires as soon as any key of the combo comes back up.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

# X11 key auto-repeat delivers release+press pairs while a key is held. A
# release only counts as a real release if the key is not pressed again
# within this window (Windows/macOS repeats send no release, so the tiny
# extra latency there is the only cost).
_RELEASE_DEBOUNCE_S = 0.05


class Hotkeys:
    def __init__(self, on_press, on_release=None):
        self._on_press = on_press
        self._on_release = on_release or (lambda: None)
        self._listener = None
        self._combo: set = set()
        self._pressed: set = set()
        self._active = False
        self._release_timer: threading.Timer | None = None
        # Guards the hold-mode state below, which is touched by both the pynput
        # listener thread and the debounce Timer thread.
        self._lock = threading.Lock()

    def register(self, combo: str, mode: str = "toggle") -> None:
        """(Re-)register the global hotkey, e.g. "<ctrl>+<alt>+<space>"."""
        from pynput import keyboard

        self.stop()
        if mode == "hold":
            combo_keys = set(keyboard.HotKey.parse(combo))  # parse before locking
            with self._lock:
                self._combo = combo_keys
                self._pressed = set()
                self._active = False
            self._listener = keyboard.Listener(
                on_press=self._handle_press, on_release=self._handle_release
            )
        else:
            self._listener = keyboard.GlobalHotKeys({combo: self._on_press})
        self._listener.start()
        log.info("hotkey registered: %s (mode=%s)", combo, mode)

    # ------------------------------------------------- hold-mode tracking

    def _canonical(self, key):
        try:
            return self._listener.canonical(key)
        except Exception:
            return key

    def _handle_press(self, key) -> None:
        key = self._canonical(key)
        if key not in self._combo:
            return
        fire = False
        with self._lock:
            self._pressed.add(key)
            if self._active:
                self._cancel_release_timer()  # auto-repeat pair — key is still held
            elif self._pressed == self._combo:
                self._active = True
                fire = True
        if fire:
            self._on_press()

    def _handle_release(self, key) -> None:
        key = self._canonical(key)
        if key not in self._combo:
            return
        with self._lock:
            self._pressed.discard(key)
            if self._active:
                self._cancel_release_timer()
                self._release_timer = threading.Timer(_RELEASE_DEBOUNCE_S, self._deactivate)
                self._release_timer.daemon = True
                self._release_timer.start()

    def _deactivate(self) -> None:
        fire = False
        with self._lock:
            # Re-check the real key state: if the combo is fully held again by
            # the time the timer fires (auto-repeat re-press, even when delayed
            # past the debounce under load), this was not a genuine release.
            if self._active and self._pressed != self._combo:
                self._active = False
                fire = True
            self._release_timer = None
        if fire:
            self._on_release()

    def _cancel_release_timer(self) -> None:
        """Cancel a pending release timer. Caller holds self._lock."""
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None

    # ------------------------------------------------------------- misc

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                log.debug("error stopping hotkey listener", exc_info=True)
            self._listener = None
        with self._lock:
            self._cancel_release_timer()
            self._pressed = set()
            self._active = False

    @staticmethod
    def validate(combo: str) -> bool:
        from pynput import keyboard

        try:
            keyboard.HotKey.parse(combo)
            return True
        except (ValueError, KeyError):
            return False

    @staticmethod
    def equal(combo_a: str, combo_b: str) -> bool:
        """Whether two hotkey strings denote the same combination, ignoring token
        order (so "<alt>+<ctrl>+m" == "<ctrl>+<alt>+m"). Falls back to a
        normalized string compare if either side doesn't parse."""
        from pynput import keyboard

        try:
            return set(keyboard.HotKey.parse(combo_a)) == set(keyboard.HotKey.parse(combo_b))
        except (ValueError, KeyError):
            return combo_a.strip().lower() == combo_b.strip().lower()
