"""Small line-art icons painted with QPainter (no SVG plugin required).

The navigation sidebar and the Home page use these glyphs. They are drawn
in code — not loaded from files — so they always render, follow the theme
colours exactly and stay crisp on any display scale (painted at 2× and
tagged with a device pixel ratio).

Kept separate from icons.py, which is deliberately Qt-free (Pillow only).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

log = logging.getLogger(__name__)

# Logical canvas the glyph paths are drawn on; pixmaps are rendered at 2×.
_CANVAS = 20.0
_STROKE = 1.7


def _path_home(p: QPainterPath) -> None:
    p.moveTo(3.2, 9.4)
    p.lineTo(10.0, 3.4)
    p.lineTo(16.8, 9.4)
    p.moveTo(5.0, 8.6)
    p.lineTo(5.0, 16.4)
    p.lineTo(15.0, 16.4)
    p.lineTo(15.0, 8.6)
    p.moveTo(8.4, 16.4)
    p.lineTo(8.4, 12.0)
    p.lineTo(11.6, 12.0)
    p.lineTo(11.6, 16.4)


def _path_sliders(p: QPainterPath) -> None:
    for y, knob_x in ((5.0, 13.0), (10.0, 7.0), (15.0, 11.0)):
        p.moveTo(3.0, y)
        p.lineTo(17.0, y)
        p.addEllipse(QPointF(knob_x, y), 2.0, 2.0)


def _path_wave(p: QPainterPath) -> None:
    for x, half in ((4.0, 2.5), (7.0, 4.5), (10.0, 6.5), (13.0, 4.0), (16.0, 2.0)):
        p.moveTo(x, 10.0 - half)
        p.lineTo(x, 10.0 + half)


def _path_mic(p: QPainterPath) -> None:
    p.addRoundedRect(QRectF(7.4, 3.0, 5.2, 8.6), 2.6, 2.6)
    p.moveTo(4.6, 9.6)
    p.arcTo(QRectF(4.6, 4.4, 10.8, 10.4), 180.0, 180.0)
    p.moveTo(10.0, 14.8)
    p.lineTo(10.0, 17.0)
    p.moveTo(7.0, 17.0)
    p.lineTo(13.0, 17.0)


def _path_layers(p: QPainterPath) -> None:
    p.addRoundedRect(QRectF(3.0, 3.0, 10.5, 10.5), 2.0, 2.0)
    p.moveTo(16.0, 7.5)
    p.lineTo(17.0, 7.5)
    p.moveTo(17.0, 7.0)
    p.lineTo(17.0, 15.0)
    p.quadTo(17.0, 17.0, 15.0, 17.0)
    p.lineTo(7.0, 17.0)
    p.moveTo(6.5, 16.0)
    p.lineTo(6.5, 16.5)


def _path_link(p: QPainterPath) -> None:
    p.addRoundedRect(QRectF(2.6, 8.0, 8.5, 4.0), 2.0, 2.0)
    p.addRoundedRect(QRectF(8.9, 8.0, 8.5, 4.0), 2.0, 2.0)


def _path_spark(p: QPainterPath) -> None:
    p.moveTo(10.0, 2.8)
    p.quadTo(10.9, 8.1, 17.2, 10.0)
    p.quadTo(10.9, 11.9, 10.0, 17.2)
    p.quadTo(9.1, 11.9, 2.8, 10.0)
    p.quadTo(9.1, 8.1, 10.0, 2.8)


def _path_clock(p: QPainterPath) -> None:
    p.addEllipse(QPointF(10.0, 10.0), 7.0, 7.0)
    p.moveTo(10.0, 5.8)
    p.lineTo(10.0, 10.0)
    p.lineTo(13.2, 12.2)


def _path_download(p: QPainterPath) -> None:
    p.moveTo(10.0, 3.0)
    p.lineTo(10.0, 12.0)
    p.moveTo(6.4, 8.8)
    p.lineTo(10.0, 12.4)
    p.lineTo(13.6, 8.8)
    p.moveTo(3.6, 15.0)
    p.lineTo(3.6, 16.6)
    p.lineTo(16.4, 16.6)
    p.lineTo(16.4, 15.0)


def _path_help(p: QPainterPath) -> None:
    p.addEllipse(QPointF(10.0, 10.0), 7.0, 7.0)
    p.moveTo(7.8, 8.2)
    p.quadTo(7.8, 5.9, 10.0, 5.9)
    p.quadTo(12.2, 5.9, 12.2, 8.0)
    p.quadTo(12.2, 9.6, 10.0, 10.2)
    p.lineTo(10.0, 11.6)
    p.moveTo(10.0, 13.8)
    p.lineTo(10.0, 14.1)


def _path_keyboard(p: QPainterPath) -> None:
    p.addRoundedRect(QRectF(2.6, 5.4, 14.8, 9.2), 2.0, 2.0)
    for x in (5.4, 8.4, 11.4, 14.4):
        p.moveTo(x, 8.2)
        p.lineTo(x + 0.3, 8.2)
    p.moveTo(6.4, 11.6)
    p.lineTo(13.6, 11.6)


def _path_record(p: QPainterPath) -> None:
    p.addEllipse(QPointF(10.0, 10.0), 6.2, 6.2)


_PATHS = {
    "home": _path_home,
    "sliders": _path_sliders,
    "wave": _path_wave,
    "mic": _path_mic,
    "layers": _path_layers,
    "link": _path_link,
    "spark": _path_spark,
    "clock": _path_clock,
    "download": _path_download,
    "help": _path_help,
    "keyboard": _path_keyboard,
    "record": _path_record,
}

GLYPH_NAMES = tuple(_PATHS)


def glyph_pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    """The glyph `name` stroked in `color`, rendered at 2× for crispness."""
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size * scale / _CANVAS, size * scale / _CANVAS)
        pen = QPen(QColor(color))
        pen.setWidthF(_STROKE)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        _PATHS[name](path)
        painter.drawPath(path)
    finally:
        painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def glyph_icon(name: str, color: str, selected_color: str | None = None, size: int = 20) -> QIcon:
    """A QIcon of the glyph; `selected_color` (if given) is used for the
    Selected icon mode, so a highlighted nav row recolours its icon."""
    icon = QIcon()
    icon.addPixmap(glyph_pixmap(name, color, size), QIcon.Mode.Normal)
    if selected_color:
        icon.addPixmap(glyph_pixmap(name, selected_color, size), QIcon.Mode.Selected)
    return icon
