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
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from .audio import SAMPLE_RATE, band_levels
from .keymap import hotkey_label
from .voice_mic_widget import VoiceMicWidget

log = logging.getLogger(__name__)

_ICON_SIZE = 64
_DRAG_THRESHOLD = 8  # px of net movement that turns a click into a drag
_BUBBLE_BG = "#202124"
_BUBBLE_FG = "#f1f3f4"
_LIVE_TAIL_CHARS = 240  # live preview shows only the most recent text
_BUBBLE_MAX_W = 320
_LEVEL_POLL_MS = 50  # feed mic band levels to the widget ~20x/s while recording
_LEVEL_WINDOW_FRAMES = SAMPLE_RATE // 10  # analyze the most recent 100 ms
_WATCHDOG_MS = 30_000  # re-assert the icon every 30 s while it should be visible
_PLACE_RETRY_MS = 2_000  # look again while the saved monitor is still missing
_PLACE_RETRY_LIMIT = 15  # …for ~30 s after start; later hot-plug arrives as a signal

_STATE_LABELS = {
    "idle": "Idle — click or press the hotkey to record",
    "recording": "Recording… click again to stop",
    "processing": "Transcribing…",
}


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
        else:
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

        self.win = _FloatingIcon(self)
        self.win.setToolTip(_idle_label(app.cfg) + "\nDrag to move • right-click for menu")

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
        # _reassert), so as long as the icon should be visible it is checked
        # and re-asserted periodically, and hard-reshown after events that are
        # known to eat it (resume from sleep, monitor changes).
        self._visible_wanted = False
        self._last_tick = time.monotonic()
        self._watchdog = QTimer(self.win)
        self._watchdog.timeout.connect(self._watchdog_tick)
        gui_app = QGuiApplication.instance()
        if gui_app is not None:
            gui_app.screenAdded.connect(self._on_screens_changed)
            gui_app.screenRemoved.connect(self._on_screens_changed)
            gui_app.primaryScreenChanged.connect(self._on_screens_changed)

        self._menu = QMenu()
        self._menu.addAction("Start / stop recording", lambda: app.post("toggle"))
        self._menu.addAction("Cancel recording", lambda: app.post("cancel"))
        self._menu.addAction("Copy last transcript", lambda: app.post("copy_last"))
        self._menu.addSeparator()
        self._menu.addAction("Settings…", lambda: app.post("settings"))
        # Right here as well as on the Overlay settings page: the icon you want
        # to move back is the one you are already right-clicking, and reaching
        # the settings page means finding the icon or the tray first.
        self._menu.addAction("Reset icon position", lambda: app.post("reset_overlay_position"))
        self._menu.addAction("Hide floating icon", lambda: app.post("toggle_overlay"))
        self._menu.addSeparator()
        self._menu.addAction("Quit", lambda: app.post("quit"))

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

    def set_visible(self, visible: bool) -> None:
        self._visible_wanted = bool(visible)
        if visible:
            self.win.show()
            self.win.raise_()
            self._last_tick = time.monotonic()
            self._watchdog.start(_WATCHDOG_MS)
        else:
            self._watchdog.stop()
            self._hide_bubble()
            self.win.hide()

    def _watchdog_tick(self) -> None:
        now = time.monotonic()
        gap, self._last_tick = now - self._last_tick, now
        # A tick arriving far too late means the machine was suspended —
        # display sleep is exactly when Windows drops layered windows.
        self._reassert(hard=gap > 2 * (_WATCHDOG_MS / 1000.0))

    def _on_screens_changed(self, *_args) -> None:
        # Monitor plugged/unplugged or primary changed: give the window
        # system a moment to settle the new geometry, then re-place and
        # re-assert.
        QTimer.singleShot(1000, self._on_screens_settled)

    def _on_screens_settled(self) -> None:
        if not self._alive:
            return  # a queued single-shot must not touch a destroyed overlay
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
            self.win.raise_()
        except Exception:
            log.debug("overlay re-assert failed", exc_info=True)

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
        self.win.setToolTip(
            (text or self._state_tooltip()) + "\nDrag to move • right-click for menu"
        )

    def _state_tooltip(self) -> str:
        state = self.state
        return _idle_label(self.app.cfg) if state == "idle" else _STATE_LABELS.get(state, state)

    def set_state(self, state: str) -> None:
        self.state = state
        # A download outlives a state change (the model is fetched during
        # "processing"), so it keeps the tooltip until it reports itself done.
        label = self._progress_text or self._state_tooltip()
        self.win.setToolTip(label + "\nDrag to move • right-click for menu")
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

    def show_menu(self, global_pos) -> None:
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
        self._visible_wanted = False
        gui_app = QGuiApplication.instance()
        if gui_app is not None:
            try:
                gui_app.screenAdded.disconnect(self._on_screens_changed)
                gui_app.screenRemoved.disconnect(self._on_screens_changed)
                gui_app.primaryScreenChanged.disconnect(self._on_screens_changed)
            except Exception:
                log.debug("error disconnecting screen signals", exc_info=True)
        try:
            self.bubble.close()
            self.win.close()
        except Exception:
            log.debug("error destroying overlay", exc_info=True)
