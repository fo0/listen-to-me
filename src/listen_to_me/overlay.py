"""Floating always-on-top status icon with an optional transcript bubble (Qt).

A small frameless, translucent, draggable window that mirrors the app state
through the animated VoiceMicWidget (idle = gently shimmering ring, recording
= ring pulsing with the live microphone band levels + red mic glyph,
transcribing = orange mic glyph):
- left click (without dragging): start/stop recording
- drag: move the icon; the position is saved
- right click: context menu

Next to the icon a "bubble" window can show text: a rolling live preview while
recording (if enabled) and/or the finished transcript for a few seconds.

Both windows are created with WindowDoesNotAcceptFocus + WA_ShowWithoutActivating
so clicking or showing them never steals keyboard focus from the window the
transcript is meant to be typed into. All methods run on the Qt main thread.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget

from .audio import SAMPLE_RATE, band_levels
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

_STATE_LABELS = {
    "idle": "Idle — click or press the hotkey to record",
    "recording": "Recording… click again to stop",
    "processing": "Transcribing…",
}

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

        self.win = _FloatingIcon(self)
        self.win.setToolTip(_STATE_LABELS["idle"] + "\nDrag to move • right-click for menu")

        self.bubble = _Bubble()

        self._level_timer = QTimer(self.win)
        self._level_timer.timeout.connect(self._poll_levels)
        self._flash_timer = QTimer(self.win)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._hide_bubble)

        self._menu = QMenu()
        self._menu.addAction("Start / stop recording", lambda: app.post("toggle"))
        self._menu.addAction("Cancel recording", lambda: app.post("cancel"))
        self._menu.addSeparator()
        self._menu.addAction("Settings…", lambda: app.post("settings"))
        self._menu.addAction("Hide floating icon", lambda: app.post("toggle_overlay"))
        self._menu.addSeparator()
        self._menu.addAction("Quit", lambda: app.post("quit"))

        self._place_initial()

    # --------------------------------------------------------- visibility

    def _screen_geometry(self):
        screen = self.win.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _place_initial(self) -> None:
        ocfg = self.app.cfg["overlay"]
        geo = QGuiApplication.primaryScreen().availableGeometry()
        x = ocfg.get("x")
        y = ocfg.get("y")
        if x is None or y is None:
            x = geo.right() - _ICON_SIZE - 24
            y = geo.bottom() - _ICON_SIZE - 120
        x = max(geo.left(), min(int(x), geo.right() - _ICON_SIZE))
        y = max(geo.top(), min(int(y), geo.bottom() - _ICON_SIZE))
        self.win.move(int(x), int(y))

    def set_visible(self, visible: bool) -> None:
        if visible:
            self.win.show()
            self.win.raise_()
        else:
            self._hide_bubble()
            self.win.hide()

    # -------------------------------------------------------------- state

    def set_state(self, state: str) -> None:
        self.state = state
        self.win.setToolTip(
            _STATE_LABELS.get(state, state) + "\nDrag to move • right-click for menu"
        )
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
        seconds = max(2, int(self.app.cfg["overlay"].get("preview_seconds", 6)))
        self._flash_timer.start(seconds * 1000)

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
        ocfg = self.app.cfg["overlay"]
        ocfg["x"], ocfg["y"] = self.win.x(), self.win.y()
        try:
            self.app.cfg.save()
        except Exception:
            log.exception("could not save overlay position")

    # ------------------------------------------------------------ cleanup

    def destroy(self) -> None:
        self._level_timer.stop()
        self._flash_timer.stop()
        try:
            self.bubble.close()
            self.win.close()
        except Exception:
            log.debug("error destroying overlay", exc_info=True)
