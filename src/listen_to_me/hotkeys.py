"""Global hotkey registration via pynput.

Two modes:
- "toggle": the classic behaviour — the combo fires once per press. A
            modifier-only combo (Ctrl+Alt) fires on its release instead, and
            only if no other key went down meanwhile: otherwise every
            Ctrl+Alt+X shortcut would start or stop a take unnoticed.
- "hold":   true push-to-talk — on_press fires when the full combo goes down,
            on_release fires as soon as any key of the combo comes back up.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

# X11 key auto-repeat delivers release+press pairs while a key is held. A
# release only counts as a real release if the key is not pressed again
# within this window (Windows/macOS repeats send no release, so the tiny
# extra latency there is the only cost).
_RELEASE_DEBOUNCE_S = 0.05


def _modifier_keys(keyboard) -> set:
    """Ctrl/Alt/Shift/Cmd in every variant this pynput version knows."""
    return {
        key
        for name in (
            "ctrl", "ctrl_l", "ctrl_r",
            "alt", "alt_l", "alt_r", "alt_gr",
            "shift", "shift_l", "shift_r",
            "cmd", "cmd_l", "cmd_r",
        )
        if (key := getattr(keyboard.Key, name, None)) is not None
    }


class Hotkeys:
    def __init__(self, on_press: Callable[[], None], on_release: Callable[[], None] | None = None):
        self._on_press = on_press
        self._on_release = on_release or (lambda: None)
        self._listener = None
        self._combo: set = set()
        self._pressed: set = set()
        self._active = False
        # Modifier-only toggle: armed while the combo is fully down, spoiled by
        # any other key pressed before every combo key is up again.
        self._armed = self._spoiled = False
        self._release_timer: threading.Timer | None = None
        # Guards the hold-mode and modifier-only state above, touched by the
        # pynput listener thread, the debounce Timer thread and stop().
        self._lock = threading.Lock()

    def register(self, combo: str, mode: str = "toggle") -> None:
        """(Re-)register the global hotkey, e.g. "<ctrl>+<alt>+<space>"."""
        from pynput import keyboard

        self.stop()
        combo_keys = set(keyboard.HotKey.parse(combo))  # parse before locking
        tap = mode != "hold" and combo_keys <= _modifier_keys(keyboard)
        if mode == "hold" or tap:
            with self._lock:
                self._combo = combo_keys
                self._pressed = set()
                self._active = False
            self._listener = keyboard.Listener(
                on_press=self._tap_press if tap else self._handle_press,
                on_release=self._tap_release if tap else self._handle_release,
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

    def _tap_press(self, key) -> None:
        key = self._canonical(key)
        with self._lock:
            if key in self._combo:
                self._pressed.add(key)
                self._armed = self._pressed == self._combo and not self._spoiled
            elif self._pressed:  # Ctrl+Alt+X: a shortcut sharing the modifiers
                self._armed, self._spoiled = False, True

    def _tap_release(self, key) -> None:
        key = self._canonical(key)
        if key not in self._combo:
            return
        with self._lock:
            fire, self._armed = self._armed, False
            self._pressed.discard(key)
            if not self._pressed:
                self._spoiled = False
        if fire:
            self._on_press()

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
            self._active = self._armed = self._spoiled = False

    @staticmethod
    def validate(combo: str) -> bool:
        from pynput import keyboard

        try:
            keyboard.HotKey.parse(combo)
            return True
        except (ValueError, KeyError):
            return False

    @staticmethod
    def combo_flags(combo: str) -> tuple[bool, bool]:
        """(has_modifier, has_typable) for a hotkey string.

        has_modifier: the combo contains Ctrl/Alt/Shift/Cmd — while such a key
        is physically held, injected characters could form chords.
        has_typable: the combo contains a key that simulated typing itself can
        produce (a plain character key or Space) — in hold mode the listener
        would mistake our injected text for a hotkey release.
        Both drive app._live_typing_gate(); an unparseable combo reports the
        unsafe case so live typing stays off rather than guessing.
        """
        from pynput import keyboard

        try:
            keys = keyboard.HotKey.parse(combo)
        except (ValueError, KeyError):
            return True, True
        modifier_keys = _modifier_keys(keyboard)
        has_modifier = any(key in modifier_keys for key in keys)
        # pynput >= 1.8 parses non-modifier special keys ("<f9>", "<space>") to
        # KeyCode.from_vk(...) instead of Key members, so "is a KeyCode" no
        # longer implies "plain character key". A char-less KeyCode is typable
        # only if its vk is Space's; other vks belonging to Key members
        # (F-keys, arrows, ...) are not. Unknown raw vks ("<66>") stay unsafe —
        # they may denote character keys.
        special_vks = {
            key.value.vk
            for key in keyboard.Key
            if getattr(key.value, "vk", None) is not None
        }
        space_vk = getattr(keyboard.Key.space.value, "vk", None)

        def typable(key) -> bool:
            if key == keyboard.Key.space:  # pynput < 1.8 parses "<space>" to Key.space
                return True
            if not isinstance(key, keyboard.KeyCode):
                return False
            if key.char is not None:
                return True
            if key.vk is None or key.vk == space_vk:
                return True
            return key.vk not in special_vks

        has_typable = any(typable(key) for key in keys)
        return has_modifier, has_typable

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
