"""Modern Qt look: Fusion base + a light/dark palette that follows the OS,
plus a compact stylesheet for rounded inputs, accent buttons and the settings
sidebar. Call apply_theme(app) once, right after the QApplication is created.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QColor, QImageReader, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

ACCENT = "#3d8bfd"
ACCENT_HOVER = "#5a9dfe"
ACCENT_DOWN = "#2f74d0"

# Palette tokens per scheme. Kept together so the QSS below and the QPalette
# stay in sync.
_LIGHT = {
    "window": "#f4f5f7",
    "base": "#ffffff",
    "alt": "#eceef1",
    "text": "#1f2023",
    "muted": "#5f6368",
    "border": "#cdd0d5",
    "hover": "#e6e8ec",
    "sidebar": "#e9ebef",
    "on_accent": "#ffffff",
    "disabled": "#a0a4aa",
    "danger": "#b3261e",
    "danger_hover": "#f7e7e5",
}
_DARK = {
    "window": "#202124",
    "base": "#2a2b2e",
    "alt": "#26272a",
    "text": "#e8eaed",
    "muted": "#9aa0a6",
    "border": "#3c4043",
    "hover": "#343639",
    "sidebar": "#1a1b1d",
    "on_accent": "#ffffff",
    "disabled": "#5f6368",
    "danger": "#f2b8b5",
    "danger_hover": "#3b2a29",
}


def is_dark(app: QApplication | None = None) -> bool:
    """Whether the OS is currently in dark mode (best-effort)."""
    app = app or QApplication.instance()
    try:
        from PySide6.QtCore import Qt

        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except Exception:
        log.debug("colorScheme() unavailable — falling back to palette luminance", exc_info=True)
    # Fallback for Qt < 6.5: guess from the current window colour.
    try:
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    except Exception:
        return False


def _palette(t: dict) -> QPalette:
    p = QPalette()
    C = QColor
    Role = QPalette.ColorRole
    Group = QPalette.ColorGroup
    p.setColor(Role.Window, C(t["window"]))
    p.setColor(Role.WindowText, C(t["text"]))
    p.setColor(Role.Base, C(t["base"]))
    p.setColor(Role.AlternateBase, C(t["alt"]))
    p.setColor(Role.Text, C(t["text"]))
    p.setColor(Role.Button, C(t["window"]))
    p.setColor(Role.ButtonText, C(t["text"]))
    p.setColor(Role.ToolTipBase, C(t["base"]))
    p.setColor(Role.ToolTipText, C(t["text"]))
    p.setColor(Role.Highlight, C(ACCENT))
    p.setColor(Role.HighlightedText, C(t["on_accent"]))
    p.setColor(Role.PlaceholderText, C(t["muted"]))
    p.setColor(Role.Link, C(ACCENT))
    for role in (Role.WindowText, Role.Text, Role.ButtonText):
        p.setColor(Group.Disabled, role, C(t["disabled"]))
    return p


# Combo-box / spin-box arrows -------------------------------------------------
#
# The stylesheet below paints the input backgrounds and borders, which switches
# Qt to stylesheet rendering for those widgets. The moment QComboBox::drop-down
# (or a spin-box button) is styled, Qt stops drawing the native arrow and expects
# one to be supplied as an image — without it the arrows silently vanish, which
# is barely noticeable on the light palette but completely invisible on the dark
# one. Qt style sheets can't load an inline / `data:` image, so we render tiny
# theme-coloured chevrons to SVG files in the cache dir once and point `image:`
# at them (SVG so they stay crisp at any display scale).

_CHEVRON_PATHS = {
    "down": "M4 6.5 L8 10.5 L12 6.5",
    "up": "M4 9.5 L8 5.5 L12 9.5",
}


def _chevron_svg(direction: str, color: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
        'width="16" height="16">'
        f'<path d="{_CHEVRON_PATHS[direction]}" fill="none" stroke="{color}" '
        'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


@lru_cache(maxsize=1)
def _svg_supported() -> bool:
    """Whether Qt can rasterise SVG here — i.e. the ``qsvg`` image plugin is
    present. A QSS ``image: url(….svg)`` renders through that same plugin, so if
    it's missing (e.g. a packaged build that didn't bundle it) our chevrons would
    silently fail to draw *and* the styled spin-box buttons would lose their
    native arrows. When this is False we emit no arrow rules at all and let Qt
    draw its native arrows instead. Constant per process, so cached."""
    try:
        formats = {bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()}
        return "svg" in formats
    except Exception:
        log.debug("could not query supported image formats", exc_info=True)
        return False


def _asset_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    root = Path(base) if base else Path(tempfile.gettempdir()) / "listen-to-me"
    d = root / "theme-arrows"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chevron_asset(direction: str, color: str) -> str | None:
    """Write a themed chevron SVG (idempotently) and return its path with forward
    slashes, ready to drop into a QSS ``url("…")``. Returns None if the file
    can't be written so the caller can fall back to Qt's native arrow."""
    try:
        svg = _chevron_svg(direction, color)
        digest = hashlib.md5(svg.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
        path = _asset_dir() / f"{direction}-{digest}.svg"
        if not path.exists():
            path.write_text(svg, encoding="utf-8")
        return path.as_posix()
    except Exception:
        log.debug("could not generate combo/spin arrow asset", exc_info=True)
        return None


def _arrows(t: dict) -> dict | None:
    """Paths for the four chevrons the inputs need — down/up in the normal text
    colour and in the disabled colour. None if SVG can't be rendered or any asset
    failed, so the QSS can fall back to Qt's native arrows instead of hiding
    them."""
    if not _svg_supported():
        return None
    assets = {
        "down": _chevron_asset("down", t["text"]),
        "up": _chevron_asset("up", t["text"]),
        "down_disabled": _chevron_asset("down", t["disabled"]),
        "up_disabled": _chevron_asset("up", t["disabled"]),
    }
    if any(v is None for v in assets.values()):
        return None
    return assets


def _arrow_qss(t: dict, arrows: dict | None) -> str:
    """Arrow rules for combo boxes and spin boxes. With generated chevrons the
    drop-down button stays borderless and shows our themed glyph; without them we
    emit nothing so Qt keeps drawing its native (palette-coloured) arrows."""
    if not arrows:
        return ""
    return f"""
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{ image: url("{arrows["down"]}"); width: 12px; height: 12px; }}
    QComboBox::down-arrow:disabled {{ image: url("{arrows["down_disabled"]}"); }}

    QSpinBox, QDoubleSpinBox {{ padding-right: 22px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border; subcontrol-position: top right;
        width: 20px; border: none; border-top-right-radius: 7px;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 20px; border: none; border-bottom-right-radius: 7px;
    }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {t["hover"]}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{arrows["up"]}"); width: 11px; height: 11px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{arrows["down"]}"); width: 11px; height: 11px; }}
    /* ':off' dims the arrow once a step reaches the min/max limit, matching the
       disabled look (and the native arrows this replaced). */
    QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off,
    QDoubleSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:off {{ image: url("{arrows["up_disabled"]}"); }}
    QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off,
    QDoubleSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:off {{ image: url("{arrows["down_disabled"]}"); }}
    """


def _qss(t: dict) -> str:
    return f"""
    QWidget {{ color: {t["text"]}; }}
    QDialog, QMainWindow {{ background: {t["window"]}; }}

    /* Sidebar navigation (settings) */
    QListWidget#nav {{
        background: {t["sidebar"]};
        border: none;
        outline: 0;
        padding: 8px 6px;
        min-width: 148px;
        max-width: 188px;
    }}
    QListWidget#nav::item {{
        padding: 9px 12px;
        border-radius: 7px;
        margin: 2px 2px;
        color: {t["muted"]};
    }}
    QListWidget#nav::item:selected {{ background: {ACCENT}; color: {t["on_accent"]}; }}
    QListWidget#nav::item:hover:!selected:!disabled {{ background: {t["hover"]}; color: {t["text"]}; }}
    /* Section headers are non-selectable (disabled) rows: muted, extra space above. */
    QListWidget#nav::item:disabled {{
        background: transparent;
        color: {t["muted"]};
        padding: 12px 12px 2px 12px;
    }}

    QStackedWidget > QWidget {{ background: {t["window"]}; }}

    QLabel[role="hint"] {{ color: {t["muted"]}; }}
    QLabel[role="title"] {{ font-size: 15pt; font-weight: 600; }}

    QGroupBox {{
        border: 1px solid {t["border"]};
        border-radius: 10px;
        margin-top: 14px;
        padding: 12px 12px 6px 12px;
        background: {t["base"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 0 4px;
        color: {t["muted"]};
        font-weight: 600;
    }}

    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {t["base"]};
        border: 1px solid {t["border"]};
        border-radius: 7px;
        padding: 6px 9px;
        selection-background-color: {ACCENT};
        selection-color: {t["on_accent"]};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
    QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
    /* A disabled input should read as inactive, not just grey its text. */
    QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
    QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        background: {t["alt"]};
        color: {t["disabled"]};
    }}
    QComboBox QAbstractItemView {{
        background: {t["base"]};
        border: 1px solid {t["border"]};
        selection-background-color: {ACCENT};
        selection-color: {t["on_accent"]};
        outline: 0;
    }}
    /* Breathing room in the dropdown list — the dense native rows make long
       lists (languages, models) hard to scan and easy to mis-click. */
    QComboBox QAbstractItemView::item {{ padding: 5px 8px; min-height: 22px; }}

    QPushButton {{
        background: {t["base"]};
        border: 1px solid {t["border"]};
        border-radius: 7px;
        padding: 7px 16px;
        min-height: 18px;
    }}
    QPushButton:hover {{ background: {t["hover"]}; }}
    QPushButton:pressed {{ background: {t["alt"]}; }}
    QPushButton:disabled {{ color: {t["disabled"]}; }}
    QPushButton[accent="true"] {{
        background: {ACCENT}; color: {t["on_accent"]}; border: 1px solid {ACCENT}; font-weight: 600;
    }}
    QPushButton[accent="true"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton[accent="true"]:pressed {{ background: {ACCENT_DOWN}; border-color: {ACCENT_DOWN}; }}
    /* Destructive actions (Clear history, Remove) are flagged in red so they
       can't be mistaken for a neutral action at a glance. */
    QPushButton[destructive="true"] {{ color: {t["danger"]}; }}
    QPushButton[destructive="true"]:hover {{
        background: {t["danger_hover"]};
        border-color: {t["danger"]};
    }}

    QCheckBox, QRadioButton {{ spacing: 8px; padding: 2px 0; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 17px; height: 17px; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t["border"]}; border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {t["muted"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    /* Match the horizontal bars (Help browser, changelog) to the vertical ones
       instead of leaving them native. */
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t["border"]}; border-radius: 5px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t["muted"]}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

    /* Tooltips carry most of the in-app documentation — style them to match
       the theme instead of the OS default. (No border-radius: QToolTip windows
       aren't translucent, rounded corners would show opaque black.) */
    QToolTip {{
        background: {t["base"]};
        color: {t["text"]};
        border: 1px solid {t["border"]};
        padding: 5px 7px;
    }}
    """ + _arrow_qss(t, _arrows(t))


def _apply_font(app: QApplication) -> None:
    """A consistent UI font at a comfortable size (the platform default is often
    a touch small); falls back through common families per OS."""
    font = app.font()
    try:
        font.setFamilies(["Segoe UI", "Inter", "SF Pro Text", "Noto Sans", "Cantarell", "sans-serif"])
    except Exception:
        log.debug("QFont.setFamilies unavailable", exc_info=True)
    font.setPointSizeF(10.0)
    app.setFont(font)


def apply_theme(app: QApplication) -> None:
    """Apply the Fusion style, a consistent font, an OS-matching palette and the QSS."""
    try:
        app.setStyle("Fusion")
    except Exception:
        log.debug("could not set Fusion style", exc_info=True)
    _apply_font(app)
    _refresh(app)
    # React to a live OS light/dark switch (Qt 6.5+); harmless if unsupported.
    try:
        app.styleHints().colorSchemeChanged.connect(lambda _scheme: _refresh(app))
    except Exception:
        log.debug("colorSchemeChanged signal unavailable", exc_info=True)


def _refresh(app: QApplication) -> None:
    tokens = _DARK if is_dark(app) else _LIGHT
    app.setPalette(_palette(tokens))
    app.setStyleSheet(_qss(tokens))
