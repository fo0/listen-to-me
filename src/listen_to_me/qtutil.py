"""Small Qt helpers: bridge the Pillow-drawn icons (icons.py) into Qt
pixmaps/icons, the wheel guard for value widgets on scrollable pages, and
the width cap for combo boxes with unbounded item texts.

Kept separate from icons.py so that module stays Qt-free (the packaging
self-test and make_icon.py import it without pulling in PySide6).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap

from .icons import mic_image


class _WheelGuard(QObject):
    """Ignores wheel events on widgets that don't have keyboard focus.

    ``event.ignore()`` + returning True stops the widget from handling the
    wheel itself while letting Qt propagate the (unaccepted) event to the
    parent — so the surrounding scroll area scrolls instead.
    """

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return super().eventFilter(obj, event)


_wheel_guard: _WheelGuard | None = None


def guard_wheel(*widgets) -> None:
    """Stop `widgets` (combo/spin boxes) from reacting to a passing mouse wheel.

    On a scrollable settings page, Qt routes wheel events to whatever value
    widget the cursor happens to hover, silently changing it mid-scroll. After
    guarding, the wheel scrolls the page; the widget only responds to the wheel
    once it was deliberately focused (clicked), and an *open* combo popup keeps
    scrolling normally (its list view receives those events, not the combo).
    StrongFocus additionally stops the wheel itself from focusing the widget.
    """
    global _wheel_guard
    if _wheel_guard is None:
        _wheel_guard = _WheelGuard()
    for widget in widgets:
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.installEventFilter(_wheel_guard)


def elastic_combo(*combos, min_chars: int = 24) -> None:
    """Stop `combos` from demanding the width of their longest item.

    A QComboBox's size hint grows with its widest entry, and a QScrollArea
    never shrinks its content below that hint — so a single long item (a
    Hugging Face model id, an audio device name) silently forces the whole
    page wider than the viewport, and with the horizontal scroll bar off the
    right edge of every card is clipped. After this, the combo only asks for
    `min_chars` characters and stretches into whatever width the layout
    offers; long entries are elided in the closed combo but stay fully
    readable in the tooltip and while editing.
    """
    from PySide6.QtWidgets import QComboBox, QSizePolicy

    for combo in combos:
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        combo.setMinimumContentsLength(min_chars)
        policy = combo.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        combo.setSizePolicy(policy)
        # An editable combo keeps its cursor at the end, scrolling the start of
        # a long value out of view — show the value from its beginning instead.
        if combo.isEditable() and combo.lineEdit() is not None:
            combo.lineEdit().setCursorPosition(0)


def pil_to_pixmap(img) -> QPixmap:
    """Convert a Pillow RGBA image to a QPixmap.

    QImage wraps the given buffer without owning it, so we take a deep copy
    before the local `data` bytes go out of scope — otherwise the pixmap would
    reference freed memory.
    """
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


def tray_icon(state: str = "idle", size: int = 64) -> QIcon:
    """QIcon of the plain microphone glyph for the system tray."""
    return QIcon(pil_to_pixmap(mic_image(state, size)))
