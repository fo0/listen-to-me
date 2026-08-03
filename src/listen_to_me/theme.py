"""Modern Qt look: Fusion base + a light/dark palette that follows the OS,
plus a compact stylesheet for rounded inputs, accent buttons and the settings
sidebar. Call apply_theme(app) once, right after the QApplication is created.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QColor, QImageReader, QPalette
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

ACCENT = "#4f6ef7"
ACCENT_HOVER = "#6a84f8"
ACCENT_DOWN = "#3c56cf"
# Second stop of the hero gradient on the Home page (indigo → violet).
ACCENT_ALT = "#7b5bf5"

# Palette tokens per scheme. Kept together so the QSS below and the QPalette
# stay in sync. "accent_soft" is the tinted selection/hover surface modern
# sidebars use instead of a solid accent block.
_LIGHT = {
    "window": "#f5f6fa",
    "base": "#ffffff",
    "alt": "#eceef4",
    "text": "#1b1d26",
    "muted": "#5c6270",
    "border": "#d8dbe4",
    "hover": "#e8eaf1",
    "sidebar": "#eceff5",
    # Scroll-bar handle. Deliberately NOT "border": at ~1.3:1 against the page
    # the handle was invisible, and with the horizontal bar switched off it is
    # the only hint that a settings page continues below the fold. These clear
    # the 3:1 WCAG minimum for non-text UI components (asserted by gui_smoke).
    "scroll": "#868c9c",
    "accent_soft": "#e2e8fd",
    "on_accent": "#ffffff",
    "disabled": "#a2a7b3",
    # Surface of a disabled button. Its own token rather than "alt"/"window":
    # it has to read as inert against BOTH the page background and a card, and
    # dropping the accent fill onto it is the main "this control is dead" cue.
    "disabled_bg": "#e6e8ef",
    "danger": "#b3261e",
    "danger_hover": "#f7e7e5",
}
_DARK = {
    "window": "#17181c",
    "base": "#1f2127",
    "alt": "#24262d",
    "text": "#e7e9ee",
    "muted": "#9aa1ad",
    "border": "#33363f",
    "hover": "#2a2d35",
    "sidebar": "#101114",
    "scroll": "#6e7381",  # see the light palette's note
    "accent_soft": "#28304f",
    "on_accent": "#ffffff",
    "disabled": "#5b6069",
    "disabled_bg": "#1a1c21",  # see the light palette's note
    "danger": "#f2b8b5",
    "danger_hover": "#3b2a29",
}


def tokens() -> dict:
    """The palette tokens for the current OS scheme — for widgets that paint
    or build icons in code (nav glyphs, Home page) and must match the QSS."""
    return _DARK if is_dark() else _LIGHT


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
    can't be written so the caller can fall back to Qt's native arrow.

    Written via a temp sibling + ``os.replace`` like config.atomic_write_json:
    the existence check never re-validates the content, so a write cut short
    (crash, full disk) would otherwise leave a truncated SVG that every later
    run happily reuses — arrows silently broken for good.
    """
    try:
        svg = _chevron_svg(direction, color)
        digest = hashlib.md5(svg.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
        path = _asset_dir() / f"{direction}-{digest}.svg"
        if not path.exists():
            tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            try:
                tmp.write_text(svg, encoding="utf-8")
                os.replace(tmp, path)
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
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
        width: 20px; border: none; border-top-right-radius: 8px;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right;
        width: 20px; border: none; border-bottom-right-radius: 8px;
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

    /* Sidebar: branding header + navigation. The selected row uses a tinted
       accent surface with accent text (not a solid accent block) — the modern
       "pill" look, and the icon recolours via its Selected pixmap. */
    QWidget#sidebar {{ background: {t["sidebar"]}; }}
    QLabel#brandName {{ font-size: 12.5pt; font-weight: 700; }}
    QLabel#brandTag {{ color: {t["muted"]}; font-size: 8.5pt; }}
    QListWidget#nav {{
        background: transparent;
        border: none;
        outline: 0;
        padding: 4px 8px;
        min-width: 172px;
        max-width: 210px;
    }}
    QListWidget#nav::item {{
        padding: 9px 12px;
        border-radius: 8px;
        margin: 2px 2px;
        color: {t["muted"]};
    }}
    QListWidget#nav::item:selected {{ background: {t["accent_soft"]}; color: {ACCENT}; }}
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

    /* Home page ------------------------------------------------------- */
    /* Hero card: accent gradient with white content; its children must not
       inherit an opaque background. */
    QFrame#hero {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 {ACCENT}, stop:1 {ACCENT_ALT});
        border: none;
        border-radius: 14px;
    }}
    /* While recording the hero flips to a warm "live" gradient. Deliberately a
       shade deeper than the tray/icon red: the white hero text sits on the
       upper-left stop, and the brighter red it started from left the secondary
       hint line barely legible. */
    QFrame#hero[state="recording"] {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #cf3a34, stop:1 #e2582f);
    }}
    QFrame#hero QLabel {{ background: transparent; color: #ffffff; }}
    QLabel#heroState {{ font-size: 16pt; font-weight: 700; }}
    /* Secondary line: dimmed enough to keep the hierarchy, bright enough to
       read on the gradient — and warm-tinted on the red one, where a cool
       tint washes out. */
    QLabel#heroHint {{ color: #eef1ff; }}
    QFrame#hero[state="recording"] QLabel#heroHint {{ color: #fff0ed; }}
    QLabel#keycap {{
        background: #30ffffff;
        border: 1px solid #55ffffff;
        border-radius: 6px;
        padding: 3px 10px;
        font-weight: 600;
    }}
    QPushButton#recordBtn {{
        background: #ffffff;
        color: {ACCENT};
        border: none;
        border-radius: 10px;
        padding: 11px 24px;
        font-weight: 700;
    }}
    QPushButton#recordBtn:hover {{ background: #eef1ff; }}
    QPushButton#recordBtn:pressed {{ background: #dbe2fe; }}
    QFrame#hero[state="recording"] QPushButton#recordBtn {{ color: #d93a3f; }}
    QPushButton#recordBtn:disabled {{ background: #66ffffff; color: {ACCENT_DOWN}; }}
    QPushButton#heroCancel {{
        background: transparent;
        color: #ffffff;
        border: 1px solid #66ffffff;
        border-radius: 10px;
        padding: 11px 18px;
    }}
    QPushButton#heroCancel:hover {{ background: #22ffffff; }}

    /* Clickable at-a-glance stat cards + quick-action tiles. */
    QFrame[card="stat"] {{
        background: {t["base"]};
        border: 1px solid {t["border"]};
        border-radius: 12px;
    }}
    QFrame[card="stat"]:hover {{ border: 1px solid {ACCENT}; }}
    /* The at-a-glance cards are clickable controls and take keyboard focus —
       ring them like a button (same width, so nothing shifts). */
    QFrame[card="stat"]:focus {{ border: 1px solid {ACCENT}; }}
    QFrame[card="stat"] QLabel {{ background: transparent; }}
    QLabel[role="cardTitle"] {{
        color: {t["muted"]};
        font-size: 8.5pt;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QLabel[role="cardValue"] {{ font-weight: 600; }}
    QFrame[role="divider"] {{ background: {t["border"]}; border: none; }}
    QPushButton[quick="true"] {{
        background: {t["base"]};
        border: 1px solid {t["border"]};
        border-radius: 10px;
        padding: 10px 14px;
        text-align: left;
    }}
    QPushButton[quick="true"]:hover {{ background: {t["hover"]}; border-color: {ACCENT}; }}
    QPushButton[quick="true"]:pressed {{ background: {t["alt"]}; }}
    /* Section headings between the Home card groups. */
    QLabel[role="section"] {{
        color: {t["muted"]};
        font-size: 9pt;
        font-weight: 700;
        letter-spacing: 1px;
    }}

    QGroupBox {{
        border: 1px solid {t["border"]};
        border-radius: 12px;
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
        border-radius: 8px;
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
        border-radius: 8px;
        padding: 7px 16px;
        min-height: 18px;
    }}
    QPushButton:hover {{ background: {t["hover"]}; }}
    QPushButton:pressed {{ background: {t["alt"]}; }}
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
    /* A disabled button MUST look disabled. This used to be a single
       `QPushButton:disabled {{ color: ... }}` placed ABOVE the variant rules —
       and `:disabled` and `[accent="true"]` carry the same CSS specificity, so
       the later variant rule simply won: the accent and destructive buttons
       rendered pixel-identically enabled and disabled. Settings → Updates
       disables "Download & install" while it queries GitHub, so users clicked a
       button that still looked live, got nothing, and reported having to press
       every button twice.

       Position is what fixes that — the block now sits after every variant, so
       even the bare selector outranks them. The per-variant selectors are the
       belt to that braces: `[accent="true"]:hover` and friends are *more*
       specific than a bare `:disabled`, so should any Qt version start
       reporting a hover state on a disabled widget, the accent fill would come
       straight back. Each one drops the variant's colour cue (accent fill,
       danger red) rather than only dimming the label. Border width and padding
       stay untouched so enabling/disabling never nudges the layout; gui_smoke
       asserts both. #recordBtn is the one deliberate omission — its own
       :disabled rule above outranks anything here by id. */
    QPushButton:disabled,
    QPushButton[accent="true"]:disabled,
    QPushButton[destructive="true"]:disabled,
    QPushButton[quick="true"]:disabled {{
        background: {t["disabled_bg"]};
        border: 1px solid {t["border"]};
        color: {t["disabled"]};
    }}
    /* Keyboard focus must stay visible. Giving a button a border above switches
       Qt to stylesheet rendering, which drops the native focus rect — without a
       :focus rule of their own, tabbing through the window highlights nothing at
       all (the inputs already carry one). Every ring keeps the border WIDTH of
       the unfocused state, so gaining focus never nudges the layout. Placed
       after the variant rules: equal specificity, so the later rule wins. */
    QPushButton:focus {{ border: 1px solid {ACCENT}; }}
    QPushButton[accent="true"]:focus {{ border: 1px solid {t["on_accent"]}; }}
    QPushButton[destructive="true"]:focus {{ border: 1px solid {t["danger"]}; }}
    /* Hero buttons sit on the accent gradient, where the accent ring would
       disappear — ring them in the button's own foreground colour instead. */
    QPushButton#recordBtn:focus {{ border: 2px solid {ACCENT_DOWN}; padding: 9px 22px; }}
    QPushButton#heroCancel:focus {{ border: 1px solid #ffffff; }}

    /* The transparent border reserves the ring's space, so :focus only
       recolours it and the label never shifts. */
    QCheckBox, QRadioButton {{
        spacing: 8px;
        padding: 2px 0;
        border: 1px solid transparent;
        border-radius: 6px;
    }}
    QCheckBox:focus, QRadioButton:focus {{ border-color: {ACCENT}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 17px; height: 17px; }}
    /* The rule above switches check boxes to stylesheet rendering, and the
       palette's Disabled group stops applying: a greyed-out option rendered
       pixel-identically to a live one (same trap as the buttons below). The
       app disables options that another setting overrules — "restore the
       previous clipboard" under clipboard_copy = "always" — so it has to be
       visible that they no longer apply. */
    QCheckBox:disabled, QRadioButton:disabled {{ color: {t["disabled"]}; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t["scroll"]}; border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {t["muted"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    /* Match the horizontal bars (Help browser, changelog) to the vertical ones
       instead of leaving them native. */
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t["scroll"]}; border-radius: 5px; min-width: 28px; }}
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
    t = tokens()  # not a local dict lookup: keep the single source in tokens()
    app.setPalette(_palette(t))
    app.setStyleSheet(_qss(t))
