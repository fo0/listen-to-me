"""Bridge the Pillow-drawn icons (icons.py) into Qt pixmaps/icons.

Kept separate from icons.py so that module stays Qt-free (the packaging
self-test and make_icon.py import it without pulling in PySide6).
"""

from __future__ import annotations

from PySide6.QtGui import QIcon, QImage, QPixmap

from .icons import mic_image


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
