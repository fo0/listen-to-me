"""Floating always-on-top status icon with an optional transcript bubble (Qt).

A small frameless, translucent, draggable window that mirrors the app state
through the animated VoiceMicWidget (idle = gently shimmering ring, recording
= ring pulsing with the live microphone band levels + red mic glyph,
transcribing = orange mic glyph):
- left click (without dragging): start/stop recording
- drag: move the icon; the position is saved, anchored to the monitor it was
  dropped on, so it comes back there across restarts and monitor changes
- right click: context menu

Next to the icon a "bubble" window can show text: a rolling live preview while
recording (if enabled) and/or the finished transcript for a few seconds.

Both windows are created with WindowDoesNotAcceptFocus + WA_ShowWithoutActivating
so clicking or showing them never steals keyboard focus from the window the
transcript is meant to be typed into. All methods run on the Qt main thread.
"""

from __future__ import annotations

import logging
import sys
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from .audio import SAMPLE_RATE, band_levels
from .history import entry_timestamp
from .keymap import hotkey_label

# From the tray on purpose, private constant included: the take clock and the
# "Recent transcripts" submenu exist on both surfaces and must render the same
# second and list the same transcripts. A second copy here would be a second
# thing to keep in step. (tray.py imports nothing from overlay.py — no cycle.)
from .tray import _RECENT_LIMIT, format_duration, recent_entry_label
from .voice_mic_widget import VoiceMicWidget

log = logging.getLogger(__name__)

_ICON_SIZE = 64
_DRAG_THRESHOLD = 8  # px of net movement that turns a click into a drag
_TOGGLE_DEBOUNCE_S = 0.4  # ignore a second click this soon after one (see mouseReleaseEvent)
_BUBBLE_BG = "#202124"
_BUBBLE_FG = "#f1f3f4"
_LIVE_TAIL_CHARS = 240  # live preview shows only the most recent text
_BUBBLE_MAX_W = 320
_LEVEL_POLL_MS = 50  # feed mic band levels to the widget ~20x/s while recording
_LEVEL_WINDOW_FRAMES = SAMPLE_RATE // 10  # analyze the most recent 100 ms
_WATCHDOG_MS = 5_000  # probe the icon every 5 s while it should be visible
_RESUME_GAP_S = 30.0  # a tick this late means the machine was suspended, not busy
_REPAIR_RETRY_TICKS = 6  # a drop that survives a repair retries only every ~30 s
# A lost z-order is repaired in place (SetWindowPos), never by a hide()/show():
# the window is fine, only buried — see _watchdog_tick.
_TOPMOST_LOST = "no longer above other windows"
# Reported only once it has persisted for a second tick — see _dropped_reason.
_UNEXPOSED = "no longer exposed"
_PLACE_RETRY_MS = 2_000  # look again while the saved monitor is still missing
_PLACE_RETRY_LIMIT = 15  # …for ~30 s after start; later hot-plug arrives as a signal

_STATE_LABELS = {
    "idle": "Idle — click or press the hotkey to record",
    "recording": "Recording… click again to stop",
    "processing": "Transcribing…",
}


def _recording_label(elapsed=None) -> str:
    """The recording tooltip, counting the running take up once a second.

    The tray has carried this clock since the take-length cap became visible
    there; the floating icon — the always-on-top control the same user is
    looking at while they speak — kept a frozen "Recording…" for the whole
    take, so the one place that never leaves the screen was the one place the
    elapsed time was missing. `format_duration` is shared with the tray so the
    two can never render the same second differently.

    `None` (no clock yet, e.g. the state change that starts the take) keeps the
    wording the label always had.
    """
    if elapsed is None:
        return _STATE_LABELS["recording"]
    return f"Recording {format_duration(elapsed)}… click again to stop"


def _idle_label(cfg) -> str:
    """The idle tooltip, naming the configured combination when it renders —
    the floating icon is as likely a place to look up a forgotten hotkey as
    the tray is."""
    try:
        combo = hotkey_label(cfg["hotkey"])
    except Exception:
        log.debug("could not render the hotkey for the overlay tooltip", exc_info=True)
        return _STATE_LABELS["idle"]
    return f"Idle — click or press {combo} to record" if combo else _STATE_LABELS["idle"]


def _screen_key(screen) -> str:
    """A stable identity for one physical monitor.

    Desktop coordinates are not one: a monitor's geometry moves whenever the
    arrangement, a resolution or the primary screen changes, and Windows hands
    out the device names (``\\\\.\\DISPLAY1``, …) in whatever order it
    enumerates the adapters, which is not guaranteed to survive a reboot. The
    EDID identity does survive all of that, so the saved position is anchored
    to it. Falls back to the device name for screens that report no EDID at all
    (virtual displays, the offscreen platform), and to nothing when even that is
    empty — a key every screen shares would "match" the wrong monitor, so an
    empty one has to disable the anchor and leave the coordinates in charge.
    """
    parts = [
        (screen.manufacturer() or "").strip(),
        (screen.model() or "").strip(),
        (screen.serialNumber() or "").strip(),
    ]
    key = "|".join(parts)
    return key if key.strip("|") else (screen.name() or "").strip()


_WIN_FLAGS = (
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.Tool
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


class _FloatingIcon(QWidget):
    """The round icon window. Hosts the animated mic widget and forwards
    clicks/drag/menu to the Overlay."""

    def __init__(self, overlay: "Overlay"):
        super().__init__(None)
        self._overlay = overlay
        self.setWindowFlags(_WIN_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # The animation fills the whole window; mouse events must stay with
        # this window so click/drag/menu handling keeps working.
        self.mic = VoiceMicWidget(self)
        self.mic.setGeometry(0, 0, _ICON_SIZE, _ICON_SIZE)
        self.mic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._drag_start = None  # (global QPoint at press, window QPoint at press)
        self._dragged = False
        # Monotonic seconds of the last click that was turned into a toggle.
        self._last_toggle = 0.0

    @property
    def dragging(self) -> bool:
        """Whether a mouse button is currently held on the icon. The Overlay
        asks before re-placing it: a restore firing mid-drag would move the
        window out from under the pointer."""
        return self._drag_start is not None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = (event.globalPosition().toPoint(), self.pos())
            self._dragged = False
        elif event.button() == Qt.MouseButton.RightButton:
            self._overlay.show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is None:
            return
        start_global, start_pos = self._drag_start
        delta = event.globalPosition().toPoint() - start_global
        if delta.manhattanLength() > _DRAG_THRESHOLD:
            self._dragged = True
        if self._dragged:
            self.move(start_pos + delta)
            self._overlay.reposition_bubble()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._drag_start is None:
            return
        self._drag_start = None
        # _dragged latches once motion passes the threshold, so small click
        # jitter never latches (toggles) and a real move always does (saves).
        if self._dragged:
            self._overlay.save_position()
            return
        # Debounced like the Home page's record button: a double-click delivers
        # two releases well before App's 100 ms event poll runs, so both land in
        # the queue and start + stop the same take — which then dies as
        # "Recording too short — nothing inserted". The icon is round, small and
        # the most click-like thing on the screen, so it is double-clicked.
        now = time.monotonic()
        if now - self._last_toggle < _TOGGLE_DEBOUNCE_S:
            return
        self._last_toggle = now
        self._overlay.app.post("toggle")


class _Bubble(QWidget):
    """A frameless label window shown next to the icon."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(_WIN_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # Transparent window so only the label's rounded rectangle shows (no
        # opaque square corners behind the border-radius).
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("")
        # Plain text, never Qt's AutoText guess: what lands here is a Whisper
        # transcript or an assistant response, and Qt renders a label as HTML as
        # soon as its first line looks like markup ("<b>", "&lt;"). The bubble
        # would then show something other than what was dictated — tags eaten,
        # entities decoded, and a rich-text label resolving whatever resource an
        # <img> names.
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(_BUBBLE_MAX_W)
        self._label.setStyleSheet(
            f"background: {_BUBBLE_BG}; color: {_BUBBLE_FG};"
            "border-radius: 8px; padding: 8px 10px; font-size: 12px;"
        )
        layout.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
        self.adjustSize()


class Overlay:
    def __init__(self, app):
        self.app = app
        self.state = "idle"
        self._progress_text: str | None = None  # running download, see set_progress
        # Seconds of the running take, fed once a second by App's poll timer
        # (see set_elapsed). None whenever no take is being counted.
        self._elapsed: int | None = None

        self.win = _FloatingIcon(self)
        # The icon is a real control (click = start/stop, right-click = menu)
        # drawn as a glyph with no text anywhere on it, and its tooltip — the
        # only thing that says what a click does — is not something assistive
        # tech reads. A stable name plus a state description gives it the same
        # identity the tray icon gets for free from its own tooltip.
        self.win.setAccessibleName("Listen To Me — floating recording control")
        self._apply_status(_idle_label(app.cfg))

        self.bubble = _Bubble()

        self._level_timer = QTimer(self.win)
        self._level_timer.timeout.connect(self._poll_levels)
        self._flash_timer = QTimer(self.win)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._hide_bubble)
        # Retries the saved position while the monitor it names is still coming
        # up — see _restore_position.
        self._alive = True
        self._place_retries = 0
        self._place_timer = QTimer(self.win)
        self._place_timer.timeout.connect(self._retry_place)

        # Watchdog: Windows drops the icon in ways Qt never notices (see
        # _reassert), so as long as the icon should be visible it is probed
        # and repaired periodically, and hard-reshown after events that are
        # known to eat it (resume from sleep, monitor changes).
        self._visible_wanted = False
        self._last_tick = time.monotonic()
        self._drop_streak = 0  # consecutive ticks a probe reported the icon gone
        self._always_on_top = True  # real value applied below, from the config
        self._topmost_lost = False  # only log a lost z-order once per episode
        self._unexposed = False  # an un-exposed window counts on the 2nd tick
        self._watchdog = QTimer(self.win)
        self._watchdog.timeout.connect(self._watchdog_tick)
        # Coalesces bursts of screen signals (a resolution change fires
        # geometryChanged once per affected screen) into one settle pass.
        self._settle_timer = QTimer(self.win)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._on_screens_settled)
        gui_app = QGuiApplication.instance()
        if gui_app is not None:
            gui_app.screenAdded.connect(self._on_screen_added)
            gui_app.screenRemoved.connect(self._on_screens_changed)
            gui_app.primaryScreenChanged.connect(self._on_screens_changed)
            for screen in gui_app.screens():
                self._watch_screen(screen)

        self._menu = QMenu()
        # The two entries that depend on what the app is doing right now. Both
        # used to be static, which made the menu say things that were not true:
        # "Start / stop recording" never named which of the two the click would
        # do, and "Cancel recording" sat there while idle, where App drops it
        # as a no-op — an entry that does nothing reads as a broken one. The
        # tray menu has always labelled itself after the state; this is the
        # same treatment for the icon that never leaves the screen, and the
        # wording is taken from there so the two menus stay in step.
        self._act_toggle = self._menu.addAction("Start recording", lambda: app.post("toggle"))
        self._act_cancel = self._menu.addAction("Cancel recording", lambda: app.post("cancel"))
        self._menu.addAction("Copy last transcript", lambda: app.post("copy_last"))
        # …and the ones before it, exactly as in the tray menu. Reaching the
        # second-newest transcript from here meant opening Settings and walking
        # the sidebar to History — and someone working from the floating icon
        # is the one user who may have the tray icon switched off entirely, so
        # the shortcut the tray offers has to exist on this menu too.
        self._recent_menu = QMenu("Recent transcripts", self._menu)
        self._recent_menu.setToolTipsVisible(True)
        # Filled when it opens, not when it is built: a recording appends to
        # the history while this menu sits idle, so a list built at startup
        # would be stale within one dictation.
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        act_recent = self._menu.addMenu(self._recent_menu)
        act_recent.setToolTip("Copy any of the last few transcripts back to the clipboard.")
        # QMenu ignores its actions' tooltips unless asked.
        self._menu.setToolTipsVisible(True)
        self._menu.addSeparator()
        self._menu.addAction("Settings…", lambda: app.post("settings"))
        # Right here as well as on the Overlay settings page: the icon you want
        # to move back is the one you are already right-clicking, and reaching
        # the settings page means finding the icon or the tray first.
        self._menu.addAction("Reset icon position", lambda: app.post("reset_overlay_position"))
        self._menu.addAction("Hide floating icon", lambda: app.post("toggle_overlay"))
        self._menu.addSeparator()
        self._menu.addAction("Quit", lambda: app.post("quit"))
        self._sync_menu_state()

        self.apply_always_on_top()
        self._restore_position()

    # ---------------------------------------------------------- placement

    def _screen_geometry(self):
        screen = self.win.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    @staticmethod
    def _default_corner(geo) -> tuple[int, int]:
        """The icon's home position for `geo`: bottom right, clear of the
        taskbar. Shared by the first-run placement and "Reset position", so the
        two can never drift apart."""
        return geo.right() - _ICON_SIZE - 24, geo.bottom() - _ICON_SIZE - 120

    def reset_position(self) -> None:
        """Put the icon back in the default corner of the primary screen and
        persist that.

        Dragging is deliberately unconstrained — the always-on-top icon is
        allowed to park over a taskbar — and a saved position is kept as long
        as the icon's *centre* lands on any screen. Together that leaves the
        icon strandable: dragged until only a sliver is on screen it becomes
        hard to grab again, and a position on a monitor that is later
        rearranged can put it somewhere awkward on every launch. Until now the
        only ways out were dragging it back (if you can hit it) or hand-editing
        overlay.x/y in config.json.
        """
        geo = QGuiApplication.primaryScreen().availableGeometry()
        x, y = self._default_corner(geo)
        self.win.move(int(x), int(y))
        self.reposition_bubble()
        self.save_position()

    def reapply_position(self) -> None:
        """Place the icon by the *current* config again.

        For the factory reset, where the settings were replaced wholesale: the
        saved position is gone with them, so the icon has to land where a fresh
        install puts it. Unlike reset_position() this persists nothing — with
        no coordinates in the config the first-run corner stays unsaved, which
        is exactly what a first launch leaves behind.
        """
        self._restore_position()

    def _saved_int(self, key: str) -> int | None:
        """One saved coordinate, or None when it is missing or unusable.

        The overlay coordinates all default to None, so `_coerce` passes
        hand-edited values through unvalidated (Infinity raises OverflowError
        in int()), and Qt geometry is C-int — an out-of-range value would raise
        from move()/contains() far from here. A broken value must cost the
        saved position, never the whole floating icon.
        """
        value = self.app.cfg["overlay"].get(key)
        if value is None:
            return None
        try:
            coord = int(value)
            if abs(coord) >= 2**31:
                raise ValueError("coordinate out of C-int range")
        except (TypeError, ValueError, OverflowError):
            log.warning("ignoring an unusable saved overlay %s %r", key, value)
            return None
        return coord

    def _saved_screen(self, x: int | None, y: int | None):
        """The monitor the icon was last left on, matched by identity — or None
        when none was saved or that monitor is not connected right now."""
        key = self.app.cfg["overlay"].get("screen")
        if not isinstance(key, str) or not key.strip():
            return None
        matches = [s for s in QGuiApplication.screens() if _screen_key(s) == key]
        if len(matches) > 1 and x is not None and y is not None:
            # Two monitors of the same model without an EDID serial share an
            # identity; the saved desktop coordinates break the tie.
            center = QPoint(x + _ICON_SIZE // 2, y + _ICON_SIZE // 2)
            for screen in matches:
                if screen.geometry().contains(center):
                    return screen
        return matches[0] if matches else None

    def _apply_saved_position(self) -> bool:
        """Move the icon where the user last left it. Returns whether that
        position could be honoured — False means the monitor it names is not
        there (yet) and the icon had to be parked somewhere else meanwhile.

        The saved monitor identity wins over the saved desktop coordinates: the
        coordinates of a screen move whenever the arrangement, a resolution or
        the primary screen changes, while the monitor someone dragged the icon
        onto is what they actually chose.
        """
        x, y = self._saved_int("x"), self._saved_int("y")
        rel_x, rel_y = self._saved_int("rel_x"), self._saved_int("rel_y")
        screen = self._saved_screen(x, y)
        if screen is not None and rel_x is not None and rel_y is not None:
            geo = screen.geometry()
            # Clamped to that monitor: a resolution smaller than at save time
            # would otherwise put the icon outside the screen it belongs on.
            self.win.move(
                max(geo.left(), min(geo.left() + rel_x, geo.right() - _ICON_SIZE)),
                max(geo.top(), min(geo.top() + rel_y, geo.bottom() - _ICON_SIZE)),
            )
            return True
        if x is None or y is None:
            geo = QGuiApplication.primaryScreen().availableGeometry()
            self.win.move(*self._default_corner(geo))  # never saved: first-run corner
            return True
        if self._on_any_screen(x, y):
            # No usable identity (a position saved by an older build) but the
            # coordinates still land on a screen: keep them verbatim. Clamping
            # against the primary would drag an icon parked on a secondary
            # monitor back onto the primary's edge on every launch. Full
            # geometry(), same criterion as the watchdog — the drag path lets
            # the always-on-top icon park over a taskbar on purpose.
            self.win.move(x, y)
            return True
        # The saved spot is on no screen at the moment: a monitor unplugged,
        # asleep, or simply not up yet. Park it on the primary for now and
        # report the position as unhonoured so the caller looks again.
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.win.move(
            max(geo.left(), min(x, geo.right() - _ICON_SIZE)),
            max(geo.top(), min(y, geo.bottom() - _ICON_SIZE)),
        )
        return False

    def _restore_position(self) -> None:
        """Put the icon where the user left it, and keep looking for a while if
        the monitor it belongs on is not up yet.

        At logon the app is running before Windows has finished bringing up the
        secondary displays, so a position on one of them lands on no screen and
        falls back to the primary. Without the retry that fallback is permanent
        — which is why the icon used to be back on the main screen after every
        reboot even though the position had been saved correctly.
        """
        if self.win.dragging:
            # Whatever the drag ends on is saved on release; moving the window
            # now would only fight the pointer.
            return
        if self._apply_saved_position():
            self._place_timer.stop()
            self._anchor_a_legacy_position()
        else:
            self._place_retries = 0
            self._place_timer.start(_PLACE_RETRY_MS)
        # Only while it is up: the bubble is positioned right before it is
        # shown anyway, and moving that never-shown translucent window during
        # startup upsets Qt (it segfaults the offscreen platform outright).
        if self.bubble.isVisible():
            self.reposition_bubble()

    def _retry_place(self) -> None:
        if self.win.dragging:
            return  # try again on the next tick, once the pointer is free
        self._place_retries += 1
        placed = self._apply_saved_position()
        if placed and self.bubble.isVisible():
            self.reposition_bubble()
        if placed or self._place_retries >= _PLACE_RETRY_LIMIT:
            # Give up quietly: a monitor that returns later still arrives as a
            # screenAdded / primaryScreenChanged signal, which restores the
            # position from scratch.
            self._place_timer.stop()

    def _anchor_a_legacy_position(self) -> None:
        """Record which monitor a position saved before this anchor existed
        belongs to — once, on the first launch that can place it correctly.

        Without it an upgraded config keeps relying on desktop coordinates
        alone, and the icon would still be misplaced the first time the
        monitors are rearranged. Only for a position the user actually chose:
        with nothing saved the first-run corner stays unsaved, exactly as
        before. Runs after a *successful* placement, so the icon is provably
        where the saved position wanted it and this cannot overwrite it with a
        fallback spot.
        """
        ocfg = self.app.cfg["overlay"]
        if ocfg.get("screen") is not None or ocfg.get("x") is None or ocfg.get("y") is None:
            return
        self.save_position()

    # --------------------------------------------------------- visibility

    def apply_always_on_top(self) -> None:
        """Put the `overlay.always_on_top` setting into effect, now.

        Toggling the flag makes Qt drop and rebuild the native window (and hide
        the widget with it), so a visible icon has to be shown again — which is
        also why this only touches the windows when the setting actually
        changed. The bubble follows the icon: a transcript popping up above a
        window the icon itself sits behind would look like a stray artefact.
        """
        wanted = bool(self.app.cfg["overlay"].get("always_on_top", True))
        if wanted == self._always_on_top and self.win.windowHandle() is not None:
            return  # already in that state (and past the first, pre-show call)
        self._always_on_top = wanted
        self._topmost_lost = False
        hint = Qt.WindowType.WindowStaysOnTopHint
        try:
            for window in (self.win, self.bubble):
                was_visible = window.isVisible()
                window.setWindowFlag(hint, wanted)
                if was_visible:
                    window.show()
        except Exception:
            log.exception("could not change the floating icon's always-on-top state")
        if self._visible_wanted:
            self._reassert()

    def set_visible(self, visible: bool) -> None:
        self._visible_wanted = bool(visible)
        if visible:
            self.win.show()
            self.win.raise_()
            self._last_tick = time.monotonic()
            self._drop_streak = 0
            self._watchdog.start(_WATCHDOG_MS)
        else:
            self._watchdog.stop()
            self._hide_bubble()
            self.win.hide()

    def _watchdog_tick(self) -> None:
        now = time.monotonic()
        gap, self._last_tick = now - self._last_tick, now
        if self.win.dragging:
            # The pointer is holding the icon, so it is provably on screen —
            # and a hide()/show() now would abort the drag mid-move.
            return
        if gap > _RESUME_GAP_S:
            # A tick arriving far too late means the machine was suspended —
            # display sleep is exactly when Windows drops layered windows.
            self._drop_streak = 0
            self._reassert(hard=True)
            return
        reason = self._dropped_reason()
        if reason == _TOPMOST_LOST:
            # The window is intact, only buried — the usual reason the icon
            # "disappears". A plain SetWindowPos puts it back on top; a
            # hide()/show() here would only add a flicker.
            if not self._topmost_lost:
                self._topmost_lost = True
                log.info("the floating icon lost its always-on-top state — re-applying it")
            self._drop_streak = 0
            self._reassert()
            return
        self._topmost_lost = False
        if reason is None:
            self._drop_streak = 0
            self._reassert()
            return
        # Escalation ladder, throttled: repair immediately once, rebuild the
        # native window if that did not stick, then keep retrying slowly. A
        # probe that is wrong on some setup (a compositor that never reports
        # the window exposed, say) must not hide()/show() the icon every 5 s.
        self._drop_streak += 1
        if self._drop_streak == 1:
            log.info("the floating icon was dropped (%s) — re-showing it", reason)
            self._reassert(hard=True)
        elif self._drop_streak % _REPAIR_RETRY_TICKS == 1:
            log.debug("the floating icon is still dropped (%s) — retrying", reason)
            if self._drop_streak == _REPAIR_RETRY_TICKS + 1:
                self._recreate_window()
            else:
                self._reassert(hard=True)

    def _dropped_reason(self) -> str | None:
        """Why the icon is not actually showing although it should be — None
        when every check passes (or nothing more can be checked here).

        isVisible() only reports the *requested* Qt state, so it catches
        nothing the OS did behind Qt's back; the probes below ask the window
        system itself. All of them fail soft: a probe that cannot answer never
        counts as a drop.
        """
        if not self.win.isVisible():
            return "hidden at the Qt level"
        if not self._on_any_screen():
            # A resolution or arrangement change stranded the position outside
            # every screen (and fired no screenAdded/Removed to repair it).
            return "outside every screen"
        if sys.platform != "win32":
            return None
        # An un-exposed window only counts once it stays that way: Qt clears
        # the expose state until the platform has delivered the expose event,
        # so it is briefly false right after every show() — including the one
        # a repair just did. Reporting that immediately would make the
        # watchdog chase its own tail (repair → "still dropped" → escalate).
        was_unexposed, self._unexposed = self._unexposed, False
        handle = self.win.windowHandle()
        if handle is not None and not handle.isExposed():
            # Qt saw the native window go (display sleep, DWM restart) and
            # stopped painting it, but isVisible() keeps saying True — the
            # expose state is the only Qt-side flag that tracks the OS.
            self._unexposed = True
            # One tick of grace, then it counts. Nothing else is probed
            # meanwhile: a window the platform has not painted yet says little
            # about the rest, and the next tick asks again 5 s later.
            return _UNEXPOSED if was_unexposed else None
        try:
            import ctypes

            hwnd = ctypes.c_void_p(int(self.win.winId()))
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return "natively hidden"  # WS_VISIBLE cleared outside Qt
            cloaked = ctypes.c_int(0)
            got = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)  # DWMWA_CLOAKED
            )
            if got == 0 and cloaked.value:
                # DWM keeps composing the window but does not draw it — e.g.
                # it was left behind on another virtual desktop.
                return "cloaked by the compositor"
            if self._always_on_top:
                # WS_EX_TOPMOST can be stripped without Qt ever hearing about
                # it (explorer restarts do it to every topmost window), and
                # then the icon is merely buried under whatever has focus.
                ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                if ex_style and not ex_style & 0x00000008:  # WS_EX_TOPMOST
                    return _TOPMOST_LOST  # 0 = the call failed → say nothing
        except Exception:
            log.debug("native visibility probe failed", exc_info=True)
        return None

    def _on_screen_added(self, screen) -> None:
        self._watch_screen(screen)
        self._on_screens_changed()

    def _watch_screen(self, screen) -> None:
        # A pure resolution/arrangement change (a game switching modes, RDP,
        # scaling) fires no screenAdded/screenRemoved/primaryScreenChanged at
        # all — only the screen's own geometryChanged says the desktop just
        # moved under the icon. Qt disconnects these itself when a screen goes.
        screen.geometryChanged.connect(self._on_screens_changed)

    def _on_screens_changed(self, *_args) -> None:
        # Monitor plugged/unplugged, primary changed or a geometry change:
        # give the window system a moment to settle (restarting the timer
        # coalesces the burst these arrive in), then re-place and re-assert.
        self._settle_timer.start(1000)

    def _on_screens_settled(self) -> None:
        if not self._alive:
            return  # a queued timeout must not touch a destroyed overlay
        # The saved position is re-applied on every topology change, not only
        # while one is still pending: Windows moves windows off a monitor that
        # goes away — a DisplayPort monitor dropping out on standby is enough —
        # and never moves them back when it returns.
        self._restore_position()
        self._reassert(hard=True)

    def _reassert(self, hard: bool = False) -> None:
        """Keep the icon truly on screen.

        Windows can drop it without Qt noticing: display sleep / DWM restarts
        hide layered (translucent) windows, explorer restarts and fullscreen
        apps eat the always-on-top status, and unplugging a monitor can strand
        the position outside every screen. Qt may still report isVisible() ==
        True in those cases, making a plain show() a no-op — so the hard path
        cycles hide()/show() to rebuild the native window state, and raise_()
        restores the z-order either way (never steals focus:
        WindowDoesNotAcceptFocus + WA_ShowWithoutActivating)."""
        if not self._visible_wanted:
            return
        try:
            if hard:
                if not self._on_any_screen():
                    self._restore_position()
                self.win.hide()
                self.win.show()
            elif not self.win.isVisible():
                self.win.show()
            elif not self._always_on_top:
                # Healthy, and the user does not want it forced on top: leave
                # the z-order alone. Raising it on every 5 s tick would fight
                # whatever they just brought to the front.
                return
            self.win.raise_()
            self._reassert_topmost()
        except Exception:
            log.debug("overlay re-assert failed", exc_info=True)

    def _reassert_topmost(self) -> None:
        """Re-apply always-on-top + shown at the OS level (Windows only).

        An explorer.exe restart strips WS_EX_TOPMOST from every topmost
        window, and Qt's raise_() never puts it back (it assumes the style is
        still set) — the icon then sits buried under normal windows while
        every Qt-side check reports it visible. SetWindowPos with
        HWND_TOPMOST | SWP_SHOWWINDOW is idempotent: on a healthy window it
        changes nothing (so ticking it every 5 s costs no flicker), on a
        stripped or natively hidden one it repairs the state in place.

        Skipped when the user turned always-on-top off — forcing the icon back
        over their windows is then exactly what they asked us not to do.
        """
        if not self._always_on_top or sys.platform != "win32" or not self.win.isVisible():
            return
        try:
            import ctypes

            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(int(self.win.winId())),
                ctypes.c_void_p(-1),  # HWND_TOPMOST
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0010 | 0x0040,  # NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW
            )
        except Exception:
            log.debug("native topmost re-assert failed", exc_info=True)

    def _recreate_window(self) -> None:
        """Last rung of the repair ladder: throw the native window away and
        let show() build a fresh one — for handles a hide()/show() cycle could
        not repair (a DWM surface lost across a driver reset, say). Qt keeps
        the widget, its children, attributes and geometry; only the window
        system resources are rebuilt."""
        try:
            self.win.destroy()
        except Exception:
            log.exception("recreating the floating icon window failed")
        self._reassert(hard=True)

    def _on_any_screen(self, x: int | None = None, y: int | None = None) -> bool:
        """Whether the icon's centre lands on a screen — for the position at
        `x`/`y` when given, for where the icon is now otherwise."""
        if x is None or y is None:
            center = self.win.frameGeometry().center()
        else:
            center = QPoint(x + _ICON_SIZE // 2, y + _ICON_SIZE // 2)
        return any(s.geometry().contains(center) for s in QGuiApplication.screens())

    # -------------------------------------------------------------- state

    def set_progress(self, fraction: float | None, text: str | None) -> None:
        """Show a running download on the icon: a progress ring plus the
        percentage in place of the mic glyph, or an indeterminate sweep when
        the total size is unknown (#110). `text` (None ends the display) also
        becomes the tooltip, so the icon says *what* is downloading.

        Main thread only — workers report through App.progress().
        """
        self._progress_text = text
        self.win.mic.set_progress(fraction, active=text is not None)
        # Back to whatever the state line says once the download is over.
        self._apply_status(text or self._state_tooltip())

    def _apply_status(self, label: str) -> None:
        """Put `label` on the icon as tooltip *and* accessible description.

        One place, so the two can never say different things: the tooltip is
        what a mouse user sees, the description is what assistive tech reads —
        and an icon-only control that only carries the former is unreadable to
        anyone who never hovers it.
        """
        text = label + "\nDrag to move • right-click for menu"
        self.win.setToolTip(text)
        self.win.setAccessibleDescription(text)

    def _state_tooltip(self) -> str:
        state = self.state
        if state == "idle":
            return _idle_label(self.app.cfg)
        if state == "recording":
            return _recording_label(self._elapsed)
        return _STATE_LABELS.get(state, state)

    def set_elapsed(self, seconds) -> None:
        """Put the running take's clock on the icon (tooltip + accessible
        description), the tray's counterpart for the floating icon.

        Ignored unless a take is actually running: the clock arrives from
        App's 100 ms poll and a tick that lands just after a recording ended
        must not re-label an idle icon with a frozen counter. A running
        download keeps the icon it owns — same rule as `set_state`.
        """
        if self.state != "recording":
            return
        self._elapsed = seconds
        self._apply_status(self._progress_text or self._state_tooltip())

    def _sync_menu_state(self, state: str | None = None) -> None:
        """Name the toggle entry after what a click on it will do, and offer
        "Cancel recording" only while there is a take to cancel.

        `state` is the transition being applied, for the call inside
        `set_state`. Without it the state is read back from the app, which is
        what the call right before the menu pops up needs: whatever happened
        since the last transition, the entries then describe the app as it is
        at the moment they become visible. getattr keeps the self-test's App
        stub (state-only, like the tray's) working.
        """
        if state is None:
            state = getattr(self.app, "state", self.state)
        try:
            self._act_toggle.setText(
                "Stop recording (insert text)" if state == "recording" else "Start recording"
            )
            self._act_cancel.setVisible(state == "recording")
        except Exception:
            log.debug("could not update the floating icon menu entries", exc_info=True)

    def set_state(self, state: str) -> None:
        self.state = state
        # A new state owns a fresh clock: leaving "recording" clears the
        # counter, and entering it starts from the wording without one until
        # the first tick arrives.
        self._elapsed = None
        # A download outlives a state change (the model is fetched during
        # "processing"), so it keeps the tooltip until it reports itself done.
        self._apply_status(self._progress_text or self._state_tooltip())
        # …and the menu, for the case where it is open while the take ends.
        self._sync_menu_state(state)
        self.win.mic.set_recording(state == "recording")
        self.win.mic.set_processing(state == "processing")
        if state == "recording":
            self._level_timer.start(_LEVEL_POLL_MS)
            if self.app.cfg["overlay"]["live_preview"]:
                self.show_live("● Listening…")
            else:
                # Clear any leftover flash so a stale transcript doesn't linger.
                self._hide_bubble()
            return
        self._level_timer.stop()
        if state == "processing":
            if self._bubble_visible():
                self.show_live("Transcribing…")
        elif not self._flash_timer.isActive():
            self._hide_bubble()

    def _poll_levels(self) -> None:
        """Feed the animated icon with band levels of the live recording.
        Recorder.snapshot() is thread-safe, so reading it from the Qt main
        thread while the audio callback appends chunks is fine."""
        recorder = getattr(self.app, "recorder", None)
        if recorder is None or not recorder.active:
            return
        if not self.win.isVisible():
            # Recording with the overlay hidden — skip the FFT, nobody sees it.
            # The animation picks the levels back up if the icon is re-shown.
            return
        try:
            samples = recorder.snapshot(max_frames=_LEVEL_WINDOW_FRAMES)
            if len(samples) < _LEVEL_WINDOW_FRAMES // 4:
                return  # wait until there is enough audio for a useful FFT
            self.win.mic.set_levels(*band_levels(samples))
        except Exception:
            log.debug("overlay level poll failed", exc_info=True)

    # ------------------------------------------------------------- bubble

    def show_live(self, text: str) -> None:
        """Show/update the bubble with live text (stays until state changes)."""
        self._flash_timer.stop()
        if len(text) > _LIVE_TAIL_CHARS:
            text = "…" + text[-_LIVE_TAIL_CHARS:]
        self._show_bubble(text)

    def flash(self, text: str) -> None:
        """Show the final transcript briefly, then hide the bubble."""
        self._flash_timer.stop()
        self._show_bubble(text)
        try:
            seconds = int(self.app.cfg["overlay"].get("preview_seconds", 6))
        except (TypeError, ValueError):
            seconds = 6  # untrusted config: a non-numeric value costs the option
        # Upper bound too: a hand-edited huge number would overflow
        # QTimer.start's C int and the bubble would never auto-hide.
        self._flash_timer.start(min(max(2, seconds), 600) * 1000)

    def _bubble_visible(self) -> bool:
        return self.bubble.isVisible()

    def _show_bubble(self, text: str) -> None:
        if not text or not self.win.isVisible():
            return
        self.bubble.set_text(text)
        self.reposition_bubble()
        self.bubble.show()
        self.bubble.raise_()

    def reposition_bubble(self) -> None:
        # Safe to run whether the bubble is shown or hidden (moving a hidden
        # window is a no-op on screen); callers position it right before showing.
        icon_x, icon_y = self.win.x(), self.win.y()
        width = self.bubble.width()
        height = self.bubble.height()
        geo = self._screen_geometry()
        x = icon_x + _ICON_SIZE // 2 - width // 2
        x = max(geo.left() + 4, min(x, geo.right() - width - 3))
        y = icon_y + _ICON_SIZE + 8
        if y + height > geo.bottom() - 4:
            y = icon_y - height - 8
        y = max(geo.top() + 4, y)
        self.bubble.move(x, y)

    def _hide_bubble(self) -> None:
        self._flash_timer.stop()
        self.bubble.hide()

    # ------------------------------------------------------------ menu

    def _fill_recent_menu(self) -> None:
        """(Re-)build the "Recent transcripts" submenu from the history file.

        The tray's twin, and deliberately the same behaviour rather than a
        second interpretation of it: newest first, bounded to the same few, one
        elided line each, the timestamp in the tooltip so two similar-looking
        dictations can be told apart, and the raw transcript — line breaks and
        single "&" intact — handed to the same `copy_text` event.

        A history that cannot be read says so instead of showing an empty list:
        an app that offers nothing looks exactly like one that stored nothing.
        Runs on the Qt main thread every time the submenu opens.
        """
        menu = self._recent_menu
        if menu is None:
            return
        menu.clear()
        try:
            entries = self.app.history.entries()[:_RECENT_LIMIT]
        except Exception:
            log.exception("could not read the transcript history for the overlay menu")
            failed = menu.addAction("Could not read the history")
            failed.setEnabled(False)
            return
        if not entries:
            empty = menu.addAction("No transcripts yet")
            empty.setEnabled(False)
            return
        for entry in entries:
            text = str(entry.get("text", ""))
            action = menu.addAction(recent_entry_label(entry))
            stamp = entry_timestamp(entry)
            action.setToolTip(
                f"{stamp} — copy this transcript" if stamp else "Copy this transcript"
            )
            action.triggered.connect(
                lambda _checked=False, t=text: self.app.post("copy_text", t)
            )

    def show_menu(self, global_pos) -> None:
        # Right before it becomes visible, not only on the last state change:
        # the menu is built once and lives for the whole session.
        self._sync_menu_state()
        self._menu.popup(global_pos)

    def save_position(self) -> None:
        """Persist where the icon is — as desktop coordinates *and* as the
        monitor it sits on plus the offset inside it, so the next start finds
        that monitor again even when its desktop coordinates have changed."""
        ocfg = self.app.cfg["overlay"]
        x, y = self.win.x(), self.win.y()
        ocfg["x"], ocfg["y"] = x, y
        center = QPoint(x + _ICON_SIZE // 2, y + _ICON_SIZE // 2)
        screen = QGuiApplication.screenAt(center) or self.win.screen()
        key = _screen_key(screen) if screen is not None else ""
        if key:
            geo = screen.geometry()
            ocfg["screen"] = key
            ocfg["rel_x"], ocfg["rel_y"] = x - geo.left(), y - geo.top()
        else:
            # Nothing to anchor to (no screen there, or one that reports no
            # identity at all): drop a stale anchor rather than keep one that
            # now points somewhere else.
            ocfg["screen"] = ocfg["rel_x"] = ocfg["rel_y"] = None
        # Wherever the icon is now is what the user chose: a pending restore of
        # the older position must not move it away again.
        self._place_timer.stop()
        if not self.app.cfg.save():  # logs its own reason
            log.warning("the overlay position was not persisted")

    # ------------------------------------------------------------ cleanup

    def destroy(self) -> None:
        self._alive = False
        self._level_timer.stop()
        self._flash_timer.stop()
        self._watchdog.stop()
        self._place_timer.stop()
        self._settle_timer.stop()
        self._visible_wanted = False
        gui_app = QGuiApplication.instance()
        if gui_app is not None:
            try:
                gui_app.screenAdded.disconnect(self._on_screen_added)
                gui_app.screenRemoved.disconnect(self._on_screens_changed)
                gui_app.primaryScreenChanged.disconnect(self._on_screens_changed)
                for screen in gui_app.screens():
                    screen.geometryChanged.disconnect(self._on_screens_changed)
            except Exception:
                log.debug("error disconnecting screen signals", exc_info=True)
        try:
            self.bubble.close()
            self.win.close()
        except Exception:
            log.debug("error destroying overlay", exc_info=True)
