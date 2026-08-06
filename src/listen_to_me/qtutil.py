"""Small Qt helpers: bridge the Pillow-drawn icons (icons.py) into Qt
pixmaps/icons, the wheel guard for value widgets on scrollable pages, the
width cap for combo boxes with unbounded item texts, and the one clipboard
path every "Copy" in the app uses — plus the button feedback that reports how
that copy went.

Kept separate from icons.py so that module stays Qt-free (the packaging
self-test and make_icon.py import it without pulling in PySide6).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap

from .icons import mic_image

log = logging.getLogger(__name__)


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


def elastic_label(*labels, min_chars: int = 24) -> None:
    """Stop wrapping `labels` from demanding the width of their widest word.

    Word wrap breaks at spaces only, so a QLabel's minimum width is the width
    of its longest single word — and a Windows path, a URL or a Hugging Face
    repo id is one unbreakable word (a realistic exe path measures ~550 px).
    A status line that reports one therefore pushes the whole settings page
    past its scroll viewport, and with the horizontal scroll bar off that
    clips the right edge of every card on the page — the label version of the
    trap `elastic_combo` handles for combo boxes.

    The explicit minimum is what does the work: Qt's `qSmartMinSize` uses it
    *instead of* the longest-word minimum, so the label asks for a fixed,
    modest width and stretches into whatever the layout offers. `Ignored`
    additionally drops the label out of the layout's preferred width, so one
    long word can't inflate the window's natural size either. The text stays
    untouched — a selectable label still copies the full path even when it is
    too long to render.
    """
    from PySide6.QtWidgets import QSizePolicy

    for label in labels:
        label.setWordWrap(True)
        policy = label.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        label.setSizePolicy(policy)
        label.setMinimumWidth(min_chars * label.fontMetrics().averageCharWidth())


def copy_to_clipboard(text: str) -> bool:
    """Put `text` on the system clipboard; True when it got there.

    Two backends because either one alone loses transcripts: pyperclip works
    without a Qt clipboard owner (and is what the paste injection already
    uses), but needs `xclip`/`xsel` on Linux and raises without them; Qt's own
    clipboard has no such requirement but is bound to this process. Trying the
    second when the first raises means a "Copy" only fails when both do — and
    then it says so (the caller reports it) instead of looking like it worked.

    The pyperclip write is read back, exactly like its worker-thread twin
    `Injector.copy_to_clipboard`: a returning `copy()` only means the call
    returned, and another application can own or overwrite the clipboard in the
    same moment. Every caller announces "Copied to the clipboard" on the
    strength of this return value, so a write that silently took nothing must
    not report True — it falls through to the Qt backend instead.

    Qt main thread only: the fallback touches QApplication.
    """
    if not text:
        return False
    try:
        import pyperclip

        pyperclip.copy(text)
        stored = pyperclip.paste()
        # Windows hands back \r\n for the \n that went in — compare normalized.
        if (stored or "").replace("\r\n", "\n") == text.replace("\r\n", "\n"):
            return True
        log.warning("the clipboard did not take the text (%d chars) — trying Qt", len(text))
    except Exception:
        log.debug("pyperclip clipboard write failed — trying Qt", exc_info=True)
    try:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        return True
    except Exception:
        log.exception("could not copy text to the clipboard")
        return False


def copy_with_feedback(text: str, button, *, label: str = "Copy") -> bool:
    """Copy `text` and say **on the button** whether it got there.

    Every in-window "Copy" used to flash "Copied ✓" on success and do nothing
    at all on failure — visually identical to a button that was never clicked,
    for the one action whose whole point is that the text is now somewhere
    else. The tray's "Copy last transcript" has always reported the failure
    (App._copy_last_transcript notifies); these buttons are where the user is
    looking, so they report it here instead.

    The failure state stays up longer than the confirmation: "Copied ✓" only
    has to be noticed, "Copy failed" has to be read and acted on.

    Qt main thread only — `copy_to_clipboard`'s fallback touches QApplication.
    """
    if not text:
        return False
    # Pin the width across every label this button can show, once. Without it
    # the button (and in a transcript row, the text beside it) reflows as the
    # label changes and again when it changes back — same trick as
    # SettingsWindow._pin_width, applied where the labels are known.
    if not button.property("copyWidthPinned"):
        button.setProperty("copyWidthPinned", True)
        widest = 0
        for candidate in (label, "Copied ✓", "Copy failed"):
            button.setText(candidate)
            widest = max(widest, button.sizeHint().width())
        button.setText(label)
        button.setMinimumWidth(widest)
    ok = copy_to_clipboard(text)
    button.setText("Copied ✓" if ok else "Copy failed")

    def restore():
        # The window (and with it this button) may be gone by now — a deleted
        # C++ object raises RuntimeError through the Python wrapper.
        try:
            button.setText(label)
        except RuntimeError:
            pass

    QTimer.singleShot(1200 if ok else 3000, restore)
    return ok


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
