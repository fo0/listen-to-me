"""Main window (PySide6/Qt): a branded sidebar with a Home entry hub and the
settings pages as grouped cards."""

from __future__ import annotations

import logging
import threading
import time
import webbrowser

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, REPO_URL, __version__
from .assistant import config_problem as assistant_config_problem
from .choices import (
    BACKENDS,
    CLIPBOARD_COPY_MODES,
    COMPUTE_TYPES,
    CUSTOM_MODEL_LABEL,
    DEVICES,
    GERMAN_TURBO_CT2,
    LANGUAGES,
    MODEL_CHOICES,
    MUTE_PRESETS,
    OPENVINO_DEVICES,
    OPENVINO_PRECISIONS,
    PARAKEET_QUANTIZATIONS,
    backend_from_label,
    backend_label,
    clipboard_copy_from_label,
    clipboard_copy_label,
    clipboard_copy_mode,
    input_device_choices,
    input_device_from_label,
    language_from_label,
    language_label,
    model_from_label,
    model_label,
    mute_preset_note,
)
from .config import DEFAULT_ASSISTANT_PROMPT, default_model_dir, open_path
from .diagnostics import DiagnosticsEngine
from .glyphs import glyph_icon
from .home_page import HomePage
from .hotkeys import Hotkeys
from .keymap import hotkey_label
from .qtutil import copy_with_feedback, elastic_combo, elastic_label, guard_wheel
from .widgets import HotkeyCaptureDialog

log = logging.getLogger(__name__)

# Sidebar glyph per page title (glyphs.py).
_NAV_GLYPHS = {
    "Home": "home",
    "General": "sliders",
    "Whisper": "wave",
    "Audio": "mic",
    "Overlay": "layers",
    "Integrations": "link",
    "Assistant": "spark",
    "History": "clock",
    "Updates": "download",
    "Help": "help",
}


class _UpdateSignals(QObject):
    """Marshals results from updater worker threads back to the Qt main thread."""

    checked = Signal(list)  # list[updater.Release]
    check_failed = Signal(str)
    progress = Signal(int, int)  # bytes done, total (0 = unknown)
    downloaded = Signal(str)  # path to the downloaded exe
    download_failed = Signal(str)
    download_cancelled = Signal()


class _DiagSignals(QObject):
    """Marshals diagnostics results (model download, microphone/transcription
    test, hotkey test, hardware probe) from worker threads back to the Qt main
    thread. The leading int is the diagnostic generation the worker was started
    with — a handler ignores the payload when it no longer matches, so a worker
    detached by Cancel (or superseded by a newer run) can't touch the UI."""

    model_status = Signal(int, str)
    model_done = Signal(int, str)
    model_failed = Signal(int, str)
    mic_level = Signal(int, float)  # recent peak 0.0-1.0 while the mic test records
    mic_done = Signal(int, object)  # diagnostics.clip_stats() dict
    mic_failed = Signal(int, str)
    tx_status = Signal(int, str)
    tx_level = Signal(int, float)
    tx_done = Signal(int, str)  # recognized text ("" = nothing understood)
    tx_failed = Signal(int, str)
    hotkey_detected = Signal()
    hw_done = Signal(int, object)  # diagnostics.hardware_status() dict


# How long the hotkey test waits for the combination before giving up.
_HOTKEY_TEST_TIMEOUT_MS = 10_000

# Status line under the Whisper page's model/transcription test buttons while
# nothing runs — restored whenever a "please wait" note is cleared.
_DIAG_STATUS_IDLE = "Both buttons use the values currently entered — no Save needed."
# Shown on the page that is NOT running the diagnostic: its test buttons are
# disabled meanwhile, and a greyed-out button with no reason reads as broken.
_DIAG_BUSY_NOTE = "Another test is still running — it has to finish first."
# How long the diagnostic start buttons stay disabled after a Cancel, so a
# restart can't race the worker that was just detached (see _cancel_diagnostic).
_DIAG_COOLDOWN_MS = 400

# Updates page: the check button's idle and running labels. Equal character
# counts prove nothing in a proportional font ("Checking…" is 3 px wider), so
# the button is pinned to the wider of the two — see _pin_width.
_CHECK_LABEL = "Check now"
_CHECKING_LABEL = "Checking…"


# The choice lists (models, languages, backends, …) live in choices.py, shared
# with the first-run onboarding wizard.

# Cap how many transcript rows the History page renders at once. The store keeps
# up to `history_max`; rendering every one as widgets would be slow for large
# histories, so only the most recent are shown (with a note about the rest).
_HISTORY_RENDER_LIMIT = 300


class MuteTargetRow(QGroupBox):
    """One configurable app to mute while recording (Integrations page).

    Holds an enabled toggle, a display name, the mute keybind (with the shared
    key picker) and the mode. ``values()`` returns the config dict; removal is
    delegated to the owning page via ``on_remove``.
    """

    def __init__(self, data: dict, capture_hotkey, on_remove):
        super().__init__()
        self._capture_hotkey = capture_hotkey
        self._on_remove = on_remove

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.chk_enabled = QCheckBox("Enabled")
        self.chk_enabled.setChecked(bool(data.get("enabled")))
        self.chk_enabled.setToolTip("Send this app its mute keybind while recording.")
        header.addWidget(self.chk_enabled)
        self.name_edit = QLineEdit(str(data.get("name", "")))
        self.name_edit.setPlaceholderText("App name (e.g. Discord)")
        self.name_edit.setToolTip("A label for this app — shown here only.")
        header.addWidget(self.name_edit, 1)
        remove = QPushButton("Remove")
        remove.setProperty("destructive", True)
        remove.setToolTip("Delete this app from the list.")
        remove.setAutoDefault(False)
        remove.clicked.connect(lambda: self._on_remove(self))
        header.addWidget(remove)
        outer.addLayout(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Push-to-mute — hold the key while recording", "hold")
        self.mode_combo.addItem("Toggle mute — tap once at start and once at stop", "toggle")
        self.mode_combo.setCurrentIndex(1 if data.get("mode") == "toggle" else 0)
        self.mode_combo.setToolTip(
            "Match this to the kind of keybind the app uses:\n"
            "• Push-to-mute (recommended): the key is held down for the whole "
            "recording — stateless, it can never get stuck muted.\n"
            "• Toggle mute: the key is tapped to mute at start and again to "
            "unmute at stop."
        )
        guard_wheel(self.mode_combo)  # rows are created after the window's sweep
        form.addRow("Mode:", self.mode_combo)

        key_row = QWidget()
        kh = QHBoxLayout(key_row)
        kh.setContentsMargins(0, 0, 0, 0)
        self.hotkey_edit = QLineEdit(str(data.get("hotkey", "")))
        self.hotkey_edit.setPlaceholderText("e.g. <ctrl>+<alt>+m")
        self.hotkey_edit.setToolTip(
            "The exact combination this app has bound to mute / push-to-mute. "
            "Set the SAME combination in the app's own keybind settings."
        )
        kh.addWidget(self.hotkey_edit, 1)
        change = QPushButton("Change…")
        change.setToolTip("Press the key combination to use — no typing needed.")
        change.setAutoDefault(False)
        change.clicked.connect(self._change_hotkey)
        kh.addWidget(change)
        form.addRow("Mute keybind:", key_row)
        outer.addLayout(form)

        # What the key combination alone can't tell you: most of these apps
        # only listen for their mute keybind while they have focus, which would
        # make this target a silent no-op. Looked up by name, so a custom or
        # renamed entry simply shows nothing.
        note = mute_preset_note(str(data.get("name", "")))
        if note:
            hint = QLabel(note)
            hint.setProperty("role", "hint")  # muted styling, see theme.py
            hint.setWordWrap(True)
            outer.addWidget(hint)

    def _change_hotkey(self) -> None:
        combo = self._capture_hotkey()
        if combo:
            self.hotkey_edit.setText(combo)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or "App",
            "enabled": self.chk_enabled.isChecked(),
            "mode": self.mode_combo.currentData() or "hold",
            "hotkey": self.hotkey_edit.text().strip(),
        }


class SettingsWindow(QDialog):
    def __init__(self, app):
        super().__init__(None)
        self.app = app
        self.cfg = app.cfg
        # No " — Settings" suffix: with the Home hub this is the app's main
        # window, not just a preferences dialog.
        self.setWindowTitle(APP_NAME)
        # …and a main window must be minimizable/maximizable. A QDialog gets
        # only a close button by default, so the app's primary window couldn't
        # be sent to the taskbar or enlarged (its pages scroll, so extra height
        # is genuinely useful).
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(980, 720)
        self.setMinimumSize(840, 600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        body.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        # Keep the detail pane comfortably wide so fields aren't cramped and the
        # user doesn't have to drag the window wider.
        self.stack.setMinimumWidth(600)
        body.addWidget(self.stack, 1)

        # Updater state, wired before the Updates page is built below.
        self._usig = _UpdateSignals()
        self._usig.checked.connect(self._on_update_check_done)
        self._usig.check_failed.connect(self._on_update_check_failed)
        self._usig.progress.connect(self._on_update_progress)
        self._usig.downloaded.connect(self._on_update_downloaded)
        self._usig.download_failed.connect(self._on_update_download_failed)
        self._usig.download_cancelled.connect(self._on_update_download_cancelled)
        self._releases_newer: list = []
        self._update_busy = False
        self._updates_auto_checked = False
        self._update_download_label = ""  # version named in the progress lines

        # Diagnostics state (Download model / Test transcription on the Whisper
        # page, Test microphone on the Audio page, Test hotkey on General),
        # wired before the pages are built below.
        self._diag = DiagnosticsEngine()
        self._dsig = _DiagSignals()
        self._dsig.model_status.connect(self._on_diag_status)
        self._dsig.model_done.connect(self._on_model_done)
        self._dsig.model_failed.connect(self._on_model_failed)
        self._dsig.mic_level.connect(self._on_mic_level)
        self._dsig.mic_done.connect(self._on_mic_done)
        self._dsig.mic_failed.connect(self._on_mic_failed)
        self._dsig.tx_status.connect(self._on_diag_status)
        self._dsig.tx_level.connect(self._on_tx_level)
        self._dsig.tx_done.connect(self._on_tx_done)
        self._dsig.tx_failed.connect(self._on_tx_failed)
        self._dsig.hotkey_detected.connect(self._on_hotkey_detected)
        self._dsig.hw_done.connect(self._on_hw_done)
        self._diag_busy = False
        self._diag_kind: str | None = None  # "model" | "tx" | "mic" while busy
        # Bumped when a diagnostic starts AND when one is cancelled, so signals
        # from a detached worker are recognized as stale and ignored.
        self._diag_gen = 0
        self._diag_cancel_event: threading.Event | None = None
        self._hotkey_paused = False  # app listener paused for a mic-owning test
        # Hardware/model status probe (Whisper page status card).
        self._hw_gen = 0
        self._hw_busy = False
        self._status_probed = False  # first probe runs when the page is opened
        self._update_cancel_event: threading.Event | None = None
        self._hotkey_test: Hotkeys | None = None
        # Bumped on every test start so a stale timeout timer from an earlier
        # (already finished) test can't cancel a later one.
        self._hotkey_test_gen = 0

        # Set by force_close(): skip the unsaved-changes prompt when the app
        # itself closes the window (shutdown, updater restart).
        self._force_close = False

        # Debounces the History page's search field (see
        # _on_history_filter_changed). Created before the pages are built, so
        # the field's textChanged handler can never reach a missing timer.
        self._history_filter_timer = QTimer(self)
        self._history_filter_timer.setSingleShot(True)
        self._history_filter_timer.setInterval(200)
        self._history_filter_timer.timeout.connect(self._refresh_history)

        # The sidebar groups the pages into sections: the Home hub (no header),
        # the settings proper, and the "around the app" pages
        # (History/Updates/Help). Section headers are non-selectable rows, so a
        # sidebar row is NOT a stack index — every nav item carries its stack
        # index in UserRole instead.
        from .theme import ACCENT, tokens

        colors = tokens()
        self._page_index: dict[str, int] = {}  # page title -> stack index
        self._nav_row: dict[str, int] = {}  # page title -> sidebar row
        sections = [
            ("", [
                ("Home", self._build_home),
            ]),
            ("Settings", [
                ("General", self._build_general),
                ("Whisper", self._build_whisper),
                ("Audio", self._build_audio),
                ("Overlay", self._build_overlay),
                ("Integrations", self._build_integrations),
                ("Assistant", self._build_assistant),
            ]),
            ("More", [
                ("History", self._build_history),
                ("Updates", self._build_updates),
                ("Help", self._build_help),
            ]),
        ]
        self.nav.setIconSize(QSize(18, 18))
        for section, pages in sections:
            if section:
                header = QListWidgetItem(section.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)  # not selectable/enabled
                font = header.font()
                font.setPointSizeF(max(font.pointSizeF() - 1.5, 6.0))
                font.setBold(True)
                header.setFont(font)
                self.nav.addItem(header)
            for title, builder in pages:
                index = self.stack.addWidget(builder(title))
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, index)
                glyph = _NAV_GLYPHS.get(title)
                if glyph:
                    # Selected rows recolour their glyph to the accent (the
                    # tinted row keeps the muted glyph unreadable otherwise).
                    item.setIcon(glyph_icon(glyph, colors["muted"], ACCENT, size=18))
                self.nav.addItem(item)
                self._page_index[title] = index
                self._nav_row[title] = self.nav.count() - 1

        self._home_index = self._page_index["Home"]
        self._history_index = self._page_index["History"]
        self._whisper_index = self._page_index["Whisper"]
        self._updates_index = self._page_index["Updates"]
        self._help_index = self._page_index["Help"]
        self.nav.currentRowChanged.connect(self._on_page_changed)
        self.nav.setCurrentRow(self._nav_row["Home"])

        # Re-check the "Selected model" status line when an input it depends on
        # changes — debounced so typing in the model-folder field probes once,
        # not per keystroke. Connected after every page is built (the model
        # combo lives on General, the rest on Whisper).
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(600)
        self._status_timer.timeout.connect(self._maybe_refresh_status)
        # Cool-down after a Cancel (see _cancel_diagnostic). A child QTimer, so
        # it dies with the window instead of firing into a deleted one.
        self._diag_cooldown_timer = QTimer(self)
        self._diag_cooldown_timer.setSingleShot(True)
        self._diag_cooldown_timer.setInterval(_DIAG_COOLDOWN_MS)
        self._diag_cooldown_timer.timeout.connect(self._end_diag_cooldown)
        # currentTextChanged (not currentIndexChanged): the custom-model dialog
        # can rename the selected custom item in place without an index change.
        self.model_combo.currentTextChanged.connect(self._on_status_inputs_changed)
        self.backend_combo.currentIndexChanged.connect(self._on_status_inputs_changed)
        self.ov_precision_combo.currentIndexChanged.connect(self._on_status_inputs_changed)
        self.model_dir_edit.textChanged.connect(self._on_status_inputs_changed)

        # Footer with the version and the action buttons.
        footer = QHBoxLayout()
        footer.setContentsMargins(14, 10, 14, 12)
        version_label = QLabel(f"{APP_NAME} {__version__}")
        version_label.setProperty("role", "hint")
        footer.addWidget(version_label)
        # Next to the version: the link to the GitHub project page — the same
        # target as the tray's "Project page" entry, but reachable from the
        # window the user is already in. A QPushButton, not a QLabel carrying
        # an <a href>: a link label gives no hover, focus or keyboard
        # affordance, and this row shows on every page. Named "GitHub" rather
        # than hiding behind the version, so where it leads needs no hover.
        self.repo_button = QPushButton("GitHub")
        self.repo_button.setProperty("link", True)
        self.repo_button.setIcon(glyph_icon("link", colors["muted"], ACCENT, size=14))
        self.repo_button.setIconSize(QSize(14, 14))
        self.repo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.repo_button.setToolTip(f"Open the project page on GitHub — {REPO_URL}")
        self.repo_button.setAccessibleName("Open the project page on GitHub")
        # No mnemonic and no auto-default: Enter belongs to Save, and this is
        # the one footer control that reaches outside the app.
        self.repo_button.setAutoDefault(False)
        self.repo_button.clicked.connect(self._open_repo)
        footer.addWidget(self.repo_button)
        footer.addSpacing(10)
        self.footer_status = QLabel("")
        self.footer_status.setProperty("role", "hint")
        footer.addWidget(self.footer_status)
        footer.addStretch(1)
        # "Close", not "Cancel": this is the app's main window, and the app
        # keeps running in the tray afterwards — "Cancel" reads like undoing
        # something. Unsaved edits are still confirmed (see reject()).
        # "&" mnemonics: the footer is the one control row visible on every
        # page, so it's the highest-value place for a keyboard user to jump
        # straight to Close/Apply/Save with Alt+key instead of Tab-cycling
        # through the whole page first. No other label in this window uses a
        # mnemonic, so C/A/S can't collide with one.
        close = QPushButton("&Close")
        close.setToolTip(
            "Close this window — the app keeps running in the tray. "
            "Unsaved changes ask for confirmation first."
        )
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        apply_btn = QPushButton("&Apply")
        apply_btn.setToolTip("Save and apply all settings now — the window stays open.")
        apply_btn.setAutoDefault(False)
        apply_btn.clicked.connect(self._apply)
        footer.addWidget(apply_btn)
        save = QPushButton("&Save")
        save.setProperty("accent", True)
        save.setToolTip("Save all settings, apply them immediately and close — no restart needed.")
        # Make Enter (e.g. from a text field) trigger Save, not the first
        # auto-default button (Cancel), which would silently discard changes.
        save.setDefault(True)
        save.clicked.connect(self._save)
        footer.addWidget(save)
        outer.addLayout(footer)

        # Fades the "Settings applied ✓" footer note; restarted per Apply so a
        # quick second Apply isn't wiped early by the first one's timeout.
        self._footer_status_timer = QTimer(self)
        self._footer_status_timer.setSingleShot(True)
        self._footer_status_timer.setInterval(2500)
        self._footer_status_timer.timeout.connect(lambda: self.footer_status.setText(""))

        # Wheel-scrolling a page must never edit a value it happens to pass
        # over: every combo/spin box only reacts to the wheel once focused.
        # Rows added later (MuteTargetRow) guard their own widgets.
        guard_wheel(*self.findChildren(QComboBox), *self.findChildren(QAbstractSpinBox))

        # A live OS light/dark switch re-applies the palette and the QSS
        # (theme.py), but every pixmap painted in code keeps the colours it was
        # built with — repaint those instead of leaving them wrong until the
        # window is reopened. Qt drops the connection when this window is
        # destroyed, so it can't outlive it.
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.instance().styleHints().colorSchemeChanged.connect(
                self._on_color_scheme_changed
            )
        except Exception:
            log.debug("colorSchemeChanged signal unavailable", exc_info=True)

        # Baseline for the unsaved-changes guard — taken after every page is
        # built, so "dirty" means the user actually changed something.
        self._saved_snapshot = self._collect()

    # ------------------------------------------------------ page helpers

    def _build_sidebar(self) -> QWidget:
        """The branded sidebar: app logo + name on top, the nav list below.
        Creates self.nav; the caller fills it with sections and pages."""
        from .icons import mic_image
        from .qtutil import pil_to_pixmap

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)

        brand = QWidget()
        bh = QHBoxLayout(brand)
        bh.setContentsMargins(16, 16, 12, 10)
        bh.setSpacing(10)
        logo = QLabel()
        pixmap = pil_to_pixmap(mic_image("idle", 64))
        pixmap.setDevicePixelRatio(2)  # 32 logical px, crisp on hidpi
        logo.setPixmap(pixmap)
        bh.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        brand_name = QLabel(APP_NAME)
        brand_name.setObjectName("brandName")
        names.addWidget(brand_name)
        brand_tag = QLabel("Local voice typing")
        brand_tag.setObjectName("brandTag")
        names.addWidget(brand_tag)
        bh.addLayout(names)
        bh.addStretch(1)
        sv.addWidget(brand)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        sv.addWidget(self.nav, 1)
        return sidebar

    def _build_home(self, title: str) -> QWidget:
        self.home = HomePage(self)
        return self.home

    def set_app_state(self, state: str) -> None:
        """Mirror the app state into the Home hero (called by App._set_state
        on the Qt main thread)."""
        try:
            self.home.set_state(state)
            if state == "idle":
                # A finished dictation may have added a transcript. If the
                # History page is on screen right now, re-render it live;
                # otherwise just mark it stale so its next visit re-renders
                # instead of showing the pre-dictation list.
                if self.isVisible() and self.stack.currentIndex() == self._history_index:
                    self._refresh_history()
                else:
                    self._history_rendered = False
        except Exception:
            log.debug("could not update the Home state", exc_info=True)

    @staticmethod
    def _page(title: str) -> tuple[QWidget, QVBoxLayout]:
        """A scrollable page with a heading; returns (page, content layout)."""
        page = QWidget()
        wrap = QVBoxLayout(page)
        wrap.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        wrap.addWidget(scroll)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setProperty("role", "title")
        layout.addWidget(heading)
        scroll.setWidget(inner)
        return page, layout

    @staticmethod
    def _card(title: str) -> tuple[QGroupBox, QFormLayout]:
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        return box, form

    @staticmethod
    def _pin_width(button: QPushButton, *labels: str) -> None:
        """Stop `button` from resizing when its label is swapped at runtime.

        A control that changes width while the user is pressing it can move out
        from under the cursor, so the release lands nowhere and the click is
        lost — the very failure the Updates page was already reported for.
        Measured through the real size hint (style, padding and font all count)
        rather than by comparing string lengths.
        """
        original = button.text()
        widest = 0
        for label in labels:
            button.setText(label)
            widest = max(widest, button.sizeHint().width())
        button.setText(original)
        button.setMinimumWidth(widest)

    @staticmethod
    def _hint(text: str, *, elastic: bool = False) -> QLabel:
        """A muted, wrapping note. Pass `elastic=True` for every hint whose
        text is composed at runtime from a path, a URL or an exception — those
        carry unbreakable words that would otherwise widen the whole page."""
        label = QLabel(text)
        label.setProperty("role", "hint")
        label.setWordWrap(True)
        if elastic:
            elastic_label(label)
        return label

    @staticmethod
    def _status_value(text: str) -> QLabel:
        """A wrapping, selectable value label for the status card — device
        names and error messages can be long, and selectable text lets the
        user copy an error into a search. Always elastic: every value on the
        card comes from a probe and can be a path or a driver error."""
        label = QLabel(text)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        elastic_label(label)
        return label

    @staticmethod
    def _select_combo(combo: QComboBox, value: str) -> None:
        """Show `value` in a (non-editable) combo even if it isn't a preset, so a
        hand-edited/unlisted config value is preserved instead of resetting to
        item 0 (setCurrentText is a no-op for a missing item on a fixed combo)."""
        if value and combo.findText(value) < 0:
            combo.addItem(value)
        combo.setCurrentText(value)

    @staticmethod
    def _to_int(value, default: int) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # -------------------------------------------------------------- pages

    def _build_general(self, title: str) -> QWidget:
        page, layout = self._page(title)

        rec, form = self._card("Recording")
        hotkey_row = QWidget()
        hk = QHBoxLayout(hotkey_row)
        hk.setContentsMargins(0, 0, 0, 0)
        self.hotkey_edit = QLineEdit(self.cfg["hotkey"])
        self.hotkey_edit.setToolTip(
            "The key combination that starts/stops recording from any application. "
            "pynput format, e.g. <ctrl>+<alt>+<space>. Easiest: click “Change…” and press the keys."
        )
        hk.addWidget(self.hotkey_edit, 1)
        pick = QPushButton("Change…")
        pick.setToolTip("Records the next key combination you press — no typing needed.")
        pick.clicked.connect(self._pick_hotkey)
        hk.addWidget(pick)
        form.addRow("Global hotkey:", hotkey_row)

        modes = QWidget()
        mv = QVBoxLayout(modes)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(2)
        self.rb_toggle = QRadioButton("Toggle — press once to start, press again to stop")
        self.rb_toggle.setToolTip("One press starts the recording, the next press stops it and inserts the text.")
        self.rb_hold = QRadioButton("Hold (push-to-talk) — record only while the keys are held down")
        self.rb_hold.setToolTip("Recording runs while the full combination is held and stops the moment you release it.")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.rb_toggle)
        mode_group.addButton(self.rb_hold)
        (self.rb_hold if self.cfg["hotkey_mode"] == "hold" else self.rb_toggle).setChecked(True)
        mv.addWidget(self.rb_toggle)
        mv.addWidget(self.rb_hold)
        form.addRow("Hotkey mode:", modes)

        hotkey_test = QWidget()
        ht = QHBoxLayout(hotkey_test)
        ht.setContentsMargins(0, 0, 0, 0)
        ht.setSpacing(8)
        self.hotkey_test_button = QPushButton("Test hotkey")
        self.hotkey_test_button.setAutoDefault(False)
        self.hotkey_test_button.setToolTip(
            "Listen for the combination above for 10 seconds and confirm it "
            "arrives — recording stays paused during the test, nothing is transcribed."
        )
        self.hotkey_test_button.clicked.connect(self._test_hotkey)
        ht.addWidget(self.hotkey_test_button)
        self.hotkey_test_status = self._hint("", elastic=True)
        ht.addWidget(self.hotkey_test_status, 1)
        form.addRow("", hotkey_test)

        insert = QWidget()
        iv = QVBoxLayout(insert)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(2)
        self.rb_paste = QRadioButton("Paste via clipboard (recommended)")
        self.rb_paste.setToolTip("Copies the text to the clipboard and sends Ctrl+V. Fast and reliable in almost every app.")
        self.rb_type = QRadioButton("Simulate typing")
        self.rb_type.setToolTip("Types the text key by key. Works where pasting is blocked, but slower.")
        insert_group = QButtonGroup(self)
        insert_group.addButton(self.rb_paste)
        insert_group.addButton(self.rb_type)
        (self.rb_type if self.cfg["injection_mode"] == "type" else self.rb_paste).setChecked(True)
        iv.addWidget(self.rb_paste)
        iv.addWidget(self.rb_type)
        self.chk_live_typing = self._checkbox(
            "Type while you speak (live, experimental)",
            self.cfg["live_typing"],
            "Start typing stable parts of the transcript at the cursor while the recording "
            "is still running, instead of inserting everything at the end. Types plain text "
            "only — never Enter/Tab and never a Ctrl/Alt/Win combination (typing pauses while "
            "such a key is held). Already-typed words are final: they are never corrected, and "
            "the assistant post-processing is skipped. Words typed live use the faster preview "
            "decoding, so their accuracy can be slightly lower. faster-whisper backend only; "
            "with a hold (push-to-talk) hotkey it needs a modifier-free key such as F9.",
        )
        iv.addWidget(self.chk_live_typing)
        form.addRow("Insert text by:", insert)
        layout.addWidget(rec)

        speech, sform = self._card("Speech recognition")
        self.language_combo = QComboBox()
        self.language_combo.addItems([language_label(code) for code, _ in LANGUAGES])
        self._select_combo(self.language_combo, language_label(self.cfg["language"]))
        self.language_combo.setToolTip(
            "The language you dictate in. Fixing it improves accuracy and speed over auto-detect."
        )
        sform.addRow("Spoken language:", self.language_combo)

        # Read-only on purpose: when this combo was editable (for custom model
        # ids), accidental typing was saved verbatim as the model id and only
        # failed at model load. Custom CTranslate2 ids now go through the
        # explicit "Custom model id…" sentinel entry (_on_model_activated).
        self.model_combo = QComboBox()
        self.model_combo.addItems([model_label(m) for m, _ in MODEL_CHOICES])
        if self.model_combo.findText(model_label(self.cfg["model"])) < 0:
            # Unlisted id from the config (custom dialog / hand-edited file):
            # keep it selectable verbatim instead of resetting to item 0.
            self.model_combo.addItem(self.cfg["model"])
        self.model_combo.addItem(CUSTOM_MODEL_LABEL)
        self.model_combo.setCurrentText(model_label(self.cfg["model"]))
        self._model_index = self.model_combo.currentIndex()
        self.model_combo.activated.connect(self._on_model_activated)
        self.model_combo.setToolTip(
            "The speech-recognition model. Bigger = more accurate but slower and larger. "
            "“Custom model id…” accepts any CTranslate2 model id from Hugging Face."
        )
        # Long preset labels / custom model ids must not dictate the page's
        # minimum width — that clips every card at the right edge (see qtutil).
        elastic_combo(self.model_combo)
        sform.addRow("Whisper model:", self.model_combo)
        # Text swapped by _on_backend_changed: greying these fields out without
        # saying why would just look broken.
        self._speech_hint = self._hint("")
        sform.addRow(self._speech_hint)
        layout.addWidget(speech)

        behavior = QGroupBox("Behavior")
        bv = QVBoxLayout(behavior)
        bv.setSpacing(4)
        clipboard_row = QWidget()
        cr = QHBoxLayout(clipboard_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        cr.addWidget(QLabel("Copy the transcript to the clipboard:"))
        self.clipboard_combo = QComboBox()
        self.clipboard_combo.addItems([label for _, label in CLIPBOARD_COPY_MODES])
        # Normalized, not raw: a hand-edited value must show the mode that will
        # actually run, otherwise the dropdown promises something else.
        self.clipboard_combo.setCurrentText(
            clipboard_copy_label(clipboard_copy_mode(self.cfg["clipboard_copy"]))
        )
        self.clipboard_combo.setToolTip(
            "Where a finished transcript ends up besides the cursor. “Only when inserting "
            "fails” copies it exactly when the app could not paste or type it into the "
            "focused window — press Ctrl+V yourself instead of fetching it from "
            "Settings → History. “Always” keeps every transcript on the clipboard, "
            "which is the setting for dictating with no text field focused. "
            "A notification confirms every transcript that stays on the clipboard."
        )
        elastic_combo(self.clipboard_combo)
        cr.addWidget(self.clipboard_combo, 1)
        bv.addWidget(clipboard_row)
        self.chk_restore = self._checkbox(
            "Restore previous clipboard content after pasting",
            self.cfg["restore_clipboard"],
            "After inserting the transcript, put whatever was on the clipboard before back again.",
        )
        self._clipboard_hint = self._hint("")
        self.chk_notifications = self._checkbox(
            "Show desktop notifications",
            self.cfg["notifications"],
            "Tray notifications for status messages (downloads, errors, limits …). Errors always show.",
        )
        self.chk_beep = self._checkbox(
            "Beep on start/stop of a recording",
            self.cfg["beep"],
            "Short beep when a recording starts (high tone) and stops (low tone). Windows only.",
        )
        bv.addWidget(self.chk_restore)
        bv.addWidget(self._clipboard_hint)
        for chk in (self.chk_notifications, self.chk_beep):
            bv.addWidget(chk)
        # Wired after both widgets exist; the initial call sets the hint/state.
        self.clipboard_combo.currentIndexChanged.connect(self._on_clipboard_mode_changed)
        self._on_clipboard_mode_changed()
        layout.addWidget(behavior)

        startup = QGroupBox("Startup")
        sv = QVBoxLayout(startup)
        sv.setSpacing(4)
        self.chk_autostart = self._checkbox(
            "Start with the system (run in background)",
            self.cfg["autostart"],
            "Launch the app automatically when you log in, so the hotkey is always available.",
        )
        self.chk_start_in_tray = self._checkbox(
            "Start minimized to the system tray",
            self.cfg["start_in_tray"],
            "When enabled the app starts silently into the tray with no window. "
            "When disabled (default) this settings window opens on launch.",
        )
        for chk in (self.chk_autostart, self.chk_start_in_tray):
            sv.addWidget(chk)
        # What the OS *actually* has on file. Without it, a registration that
        # never took looks exactly like a working one — until the next reboot
        # starts nothing.
        self.autostart_status = self._hint("", elastic=True)
        sv.addWidget(self.autostart_status)
        self.chk_autostart.toggled.connect(lambda _checked: self._refresh_autostart_status())
        self._refresh_autostart_status()
        layout.addWidget(startup)

        network = QGroupBox("Network")
        nv = QVBoxLayout(network)
        nv.setSpacing(4)
        self.chk_insecure_ssl = self._checkbox(
            "Ignore SSL certificate errors (corporate proxy) — insecure",
            self.cfg["insecure_ssl"],
            "Skip TLS certificate verification for model downloads and the assistant. "
            "Only enable behind a corporate proxy that intercepts HTTPS with its own "
            "(self-signed) certificate — connections are then encrypted but no longer "
            "authenticated. Updates are excluded: they always verify the certificate, "
            "because an update replaces the program file.",
        )
        nv.addWidget(self.chk_insecure_ssl)
        nv.addWidget(self._hint(
            "⚠ Only for corporate proxies that intercept HTTPS with their own certificate. "
            "Connections stay encrypted but are no longer authenticated. Updates are "
            "excluded and keep verifying — behind such a proxy, download them manually "
            "from the release page."
        ))
        layout.addWidget(network)

        layout.addStretch(1)
        return page

    def _build_whisper(self, title: str) -> QWidget:
        page, layout = self._page(title)

        engine, form = self._card("Engine")
        self.backend_combo = QComboBox()
        self.backend_combo.addItems([label for _, label in BACKENDS])
        self._select_combo(self.backend_combo, backend_label(self.cfg["backend"]))
        self.backend_combo.setToolTip(
            "The transcription engine. faster-whisper accelerates on NVIDIA GPUs (CUDA); "
            "OpenVINO accelerates on Intel GPUs and NPUs and needs the optional "
            "openvino-genai package (pip install openvino-genai); Parakeet is a "
            "non-Whisper engine (NVIDIA Parakeet TDT, 25 languages) that transcribes "
            "many times faster and needs the optional onnx-asr package "
            '(pip install "onnx-asr[cpu,hub]"). The portable Windows build ships '
            "both optional packages already."
        )
        form.addRow("Backend:", self.backend_combo)

        self.device_combo = QComboBox()
        self.device_combo.addItems(DEVICES)
        self._select_combo(self.device_combo, self.cfg["device"])
        self.device_combo.setToolTip(
            "Where the model runs. auto picks an NVIDIA GPU (CUDA) when available, otherwise the CPU."
        )
        form.addRow("Device:", self.device_combo)

        self.compute_combo = QComboBox()
        self.compute_combo.addItems(COMPUTE_TYPES)
        self._select_combo(self.compute_combo, self.cfg["compute_type"])
        self.compute_combo.setToolTip(
            "Numeric precision. int8 is fastest on CPU; float16 needs a GPU; float32 is the slow reference."
        )
        form.addRow("Compute type:", self.compute_combo)

        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 10)
        self.beam_spin.setValue(max(1, int(self.cfg["beam_size"] or 5)))
        self.beam_spin.setToolTip(
            "How many decoding hypotheses faster-whisper explores. 5 (default) is "
            "the accuracy sweet spot; 1 (greedy) is roughly 1.5–2× faster with "
            "slightly lower accuracy."
        )
        form.addRow("Beam size:", self.beam_spin)

        self.ov_device_combo = QComboBox()
        self.ov_device_combo.addItems(OPENVINO_DEVICES)
        self._select_combo(self.ov_device_combo, self.cfg["openvino_device"])
        self.ov_device_combo.setToolTip(
            "Which Intel device runs the model. auto prefers the GPU, then the NPU "
            "(Core Ultra “AI Boost”), then the CPU. GPU/NPU need a current Intel driver."
        )
        form.addRow("Intel device:", self.ov_device_combo)

        self.ov_precision_combo = QComboBox()
        self.ov_precision_combo.addItems(OPENVINO_PRECISIONS)
        self._select_combo(self.ov_precision_combo, self.cfg["openvino_precision"])
        self.ov_precision_combo.setToolTip(
            "Which pre-converted variant of the model to download: int8 is small and fast "
            "(recommended), fp16 the most accurate, int4 the smallest. Changing this "
            "downloads the model again in the new precision."
        )
        form.addRow("Model precision:", self.ov_precision_combo)

        self.pk_quant_combo = QComboBox()
        self.pk_quant_combo.addItems(PARAKEET_QUANTIZATIONS)
        self._select_combo(self.pk_quant_combo, self.cfg["parakeet_quantization"])
        self.pk_quant_combo.setToolTip(
            "Which ONNX variant of the Parakeet model to download: int8 is small and "
            "fast on the CPU (recommended), fp32 the most accurate — best with a GPU. "
            "Changing this downloads the model again."
        )
        form.addRow("Parakeet precision:", self.pk_quant_combo)

        self.chk_vad = self._checkbox(
            "Filter silence with VAD (recommended)",
            self.cfg["vad_filter"],
            "Voice activity detection removes silent stretches — faster and avoids hallucinated "
            "text in silence. faster-whisper backend only.",
        )
        form.addRow("", self.chk_vad)
        self._engine_form = form
        layout.addWidget(engine)
        layout.addWidget(self._hint(
            "Running on the GPU (CUDA) needs the NVIDIA CUDA 12 libraries "
            "(cuBLAS + cuDNN). If they're missing, transcription switches to the "
            "CPU automatically — see the Help page for how to enable the GPU. "
            "The OpenVINO backend accelerates on Intel GPUs and NPUs instead; "
            "models are fetched pre-converted from Hugging Face (OpenVINO/whisper-…-ov). "
            "The Parakeet backend runs NVIDIA's Parakeet TDT model (not Whisper): "
            "many times faster, 25 languages with automatic detection — the model "
            "preset, language, initial prompt and VAD options don't apply to it."
        ))

        status, sform = self._card("Detected hardware && model status")
        self.hw_cuda_label = self._status_value("Not checked yet.")
        sform.addRow("NVIDIA GPU (CUDA):", self.hw_cuda_label)
        self.hw_ov_label = self._status_value("Not checked yet.")
        sform.addRow("Intel (OpenVINO):", self.hw_ov_label)
        self.hw_model_label = self._status_value("Not checked yet.")
        sform.addRow("Selected model:", self.hw_model_label)
        status_row = QWidget()
        sh = QHBoxLayout(status_row)
        sh.setContentsMargins(0, 0, 0, 0)
        self.hw_refresh_button = QPushButton("Refresh status")
        self.hw_refresh_button.setAutoDefault(False)
        self.hw_refresh_button.setToolTip(
            "Probe again — e.g. after installing a GPU driver, openvino-genai "
            "or downloading a model."
        )
        self.hw_refresh_button.clicked.connect(self._refresh_hw_status)
        sh.addWidget(self.hw_refresh_button)
        sh.addStretch(1)
        sform.addRow("", status_row)
        layout.addWidget(status)

        folder = QGroupBox("Model download folder")
        fv = QVBoxLayout(folder)
        fv.setSpacing(8)
        dir_row = QWidget()
        dh = QHBoxLayout(dir_row)
        dh.setContentsMargins(0, 0, 0, 0)
        # str(): model_dir defaults to None, so _coerce passes any hand-edited
        # value through unlaundered — a non-string here would fail the whole
        # window construction, and Settings would silently never open again.
        self.model_dir_edit = QLineEdit(str(self.cfg["model_dir"] or ""))
        # Empty is the deliberate default (= the Hugging Face cache). Show the
        # resolved cache path as a greyed-out placeholder so the empty field
        # reads as "using this" instead of looking unset — without persisting
        # it, which would break the "Use default" button and cache relocation.
        self.model_dir_edit.setPlaceholderText(str(default_model_dir()))
        self.model_dir_edit.setToolTip(
            "Where Whisper models are downloaded to and loaded from. "
            "Leave empty to use the Hugging Face cache shown below."
        )
        dh.addWidget(self.model_dir_edit, 1)
        browse = QPushButton("Browse…")
        browse.setToolTip("Pick the folder models are downloaded to and loaded from.")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse_model_dir)
        default_btn = QPushButton("Use default")
        default_btn.setToolTip(
            "Clear the field and go back to the Hugging Face cache shown below."
        )
        default_btn.setAutoDefault(False)
        default_btn.clicked.connect(lambda: self.model_dir_edit.setText(""))
        open_btn = QPushButton("Open folder")
        open_btn.setToolTip(
            "Open this folder in the file manager — e.g. to check its size or "
            "delete a model you no longer need. It is created if missing."
        )
        open_btn.setAutoDefault(False)
        open_btn.clicked.connect(self._open_model_dir)
        for b in (browse, default_btn, open_btn):
            dh.addWidget(b)
        fv.addWidget(dir_row)
        fv.addWidget(self._hint(
            "Models are fetched from Hugging Face on first use and stored here.\n"
            f"Empty = default cache: {default_model_dir()}", elastic=True
        ))
        layout.addWidget(folder)

        tools = QGroupBox("Model check && transcription test")
        tv = QVBoxLayout(tools)
        tv.setSpacing(8)
        tools_row = QHBoxLayout()
        self.model_download_button = QPushButton("Download / load model")
        self.model_download_button.setAutoDefault(False)
        self.model_download_button.setToolTip(
            "Fetch the selected model now (first use downloads, later runs load "
            "from disk) instead of waiting for your first recording. Uses the "
            "values above and the model from the General page — no Save needed."
        )
        self.model_download_button.clicked.connect(self._download_model)
        tools_row.addWidget(self.model_download_button)
        self.tx_test_button = QPushButton("Test transcription (5 s)")
        self.tx_test_button.setAutoDefault(False)
        self.tx_test_button.setToolTip(
            "End-to-end check: record five seconds from the microphone (Audio "
            "page) and transcribe them with the settings above. The result is "
            "shown below only — nothing is inserted or saved to the history."
        )
        self.tx_test_button.clicked.connect(self._test_transcription)
        tools_row.addWidget(self.tx_test_button)
        self.diag_cancel_button = QPushButton("Cancel")
        self.diag_cancel_button.setAutoDefault(False)
        self.diag_cancel_button.setEnabled(False)
        self.diag_cancel_button.setToolTip(
            "Stop the running model download / transcription test."
        )
        self.diag_cancel_button.clicked.connect(self._cancel_diagnostic)
        tools_row.addWidget(self.diag_cancel_button)
        tools_row.addStretch(1)
        tv.addLayout(tools_row)
        self.diag_progress = QProgressBar()
        self.diag_progress.setTextVisible(False)
        self.diag_progress.setVisible(False)
        # Standalone bars have no form-row label to borrow a name from, so a
        # screen reader would announce a bare "progress bar" with no idea what
        # is running. (The Audio page's level bar sits in a labelled row.)
        self.diag_progress.setAccessibleName("Model download and transcription test progress")
        tv.addWidget(self.diag_progress)
        self.diag_status = self._hint(_DIAG_STATUS_IDLE, elastic=True)
        self.diag_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tv.addWidget(self.diag_status)
        layout.addWidget(tools)

        prompt = QGroupBox("Initial prompt (domain vocabulary hint)")
        pv = QVBoxLayout(prompt)
        self.initial_prompt_edit = QPlainTextEdit(self.cfg["initial_prompt"])
        self.initial_prompt_edit.setToolTip(
            "Names, acronyms and spellings Whisper should prefer (e.g. “Kubernetes, PostgreSQL, Jira”). "
            "It biases recognition — it is NOT an instruction prompt."
        )
        self.initial_prompt_edit.setFixedHeight(80)
        pv.addWidget(self.initial_prompt_edit)
        pv.addWidget(self._hint(
            "Names, jargon and spellings Whisper should prefer — not an instruction prompt. "
            "Use the Assistant page for rewriting/cleanup."
        ))
        layout.addWidget(prompt)

        # Wired last: _on_backend_changed also greys out the Whisper-only
        # fields on the General page and the initial prompt above, so every
        # widget it touches must already exist when it first runs.
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self._on_backend_changed()

        layout.addStretch(1)
        return page

    def _build_audio(self, title: str) -> QWidget:
        page, layout = self._page(title)

        card, form = self._card("Microphone")
        device_row = QWidget()
        dh = QHBoxLayout(device_row)
        dh.setContentsMargins(0, 0, 0, 0)
        self.input_combo = QComboBox()
        self.input_combo.setToolTip(
            "The microphone used for recording. “System default” follows the OS sound settings."
        )
        # Device names come from the OS and can be arbitrarily long.
        elastic_combo(self.input_combo)
        dh.addWidget(self.input_combo, 1)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-scan the audio devices, e.g. after plugging in a headset.")
        refresh.clicked.connect(self._load_devices)
        dh.addWidget(refresh)
        form.addRow("Input device:", device_row)
        self._load_devices()

        self.max_seconds_spin = QSpinBox()
        self.max_seconds_spin.setRange(10, 3600)
        self.max_seconds_spin.setSingleStep(10)
        self.max_seconds_spin.setValue(self._to_int(self.cfg["max_seconds"], 300))
        self.max_seconds_spin.setToolTip(
            "Safety cap for a single recording — it stops automatically when the limit is reached."
        )
        form.addRow("Max recording length (s):", self.max_seconds_spin)

        mic_test = QWidget()
        mh = QHBoxLayout(mic_test)
        mh.setContentsMargins(0, 0, 0, 0)
        self.mic_test_button = QPushButton("Test microphone (3 s)")
        self.mic_test_button.setAutoDefault(False)
        self.mic_test_button.setToolTip(
            "Record three seconds from the selected device and check that a "
            "signal arrives. Speak normally — the level bar should move."
        )
        self.mic_test_button.clicked.connect(self._test_microphone)
        mh.addWidget(self.mic_test_button)
        self.mic_cancel_button = QPushButton("Cancel")
        self.mic_cancel_button.setAutoDefault(False)
        self.mic_cancel_button.setEnabled(False)
        self.mic_cancel_button.setToolTip("Stop the running microphone test.")
        self.mic_cancel_button.clicked.connect(self._cancel_diagnostic)
        mh.addWidget(self.mic_cancel_button)
        mh.addStretch(1)
        form.addRow("", mic_test)
        self.mic_level_bar = QProgressBar()
        self.mic_level_bar.setRange(0, 100)
        self.mic_level_bar.setValue(0)
        self.mic_level_bar.setTextVisible(False)
        self.mic_level_bar.setToolTip("Input level while the microphone test records.")
        form.addRow("Level:", self.mic_level_bar)
        self.mic_status = self._hint("", elastic=True)
        form.addRow("", self.mic_status)
        layout.addWidget(card)

        layout.addWidget(self._hint("Recording stops automatically when the limit is reached."))
        layout.addStretch(1)
        return page

    def _build_overlay(self, title: str) -> QWidget:
        page, layout = self._page(title)
        ocfg = self.cfg["overlay"]

        card = QGroupBox("Floating icon")
        cv = QVBoxLayout(card)
        cv.setSpacing(4)
        self.chk_o_enabled = self._checkbox(
            "Show floating microphone icon (always on top)",
            ocfg["enabled"],
            "A small round always-on-top icon showing the state. Click = start/stop, drag = move, right-click = menu.",
        )
        cv.addWidget(self.chk_o_enabled)
        cv.addWidget(self._hint("Click = start/stop • drag = move (position is saved) • right-click = menu."))
        self.chk_o_preview = self._checkbox(
            "Show the transcribed text next to the icon after each recording",
            ocfg["show_preview"],
            "After a recording, the text pops up in a small bubble next to the icon for a few seconds.",
        )
        cv.addWidget(self.chk_o_preview)
        self.chk_o_live = self._checkbox(
            "Live transcript preview while recording (experimental)",
            ocfg["live_preview"],
            "Transcribes in the background while you speak and shows a rolling preview. Costs extra CPU.",
        )
        cv.addWidget(self.chk_o_live)
        cv.addWidget(self._hint(
            "The live preview transcribes in parallel while you speak — it needs a fast machine "
            "(or a small model) and shows only the most recent sentences."
        ))
        layout.addWidget(card)

        timing, form = self._card("Timing")
        self.preview_seconds_spin = QSpinBox()
        self.preview_seconds_spin.setRange(2, 60)
        self.preview_seconds_spin.setValue(self._to_int(ocfg["preview_seconds"], 6))
        self.preview_seconds_spin.setToolTip("How long the finished transcript bubble stays visible.")
        form.addRow("Preview display time (s):", self.preview_seconds_spin)
        layout.addWidget(timing)

        layout.addStretch(1)
        return page

    def _build_integrations(self, title: str) -> QWidget:
        page, layout = self._page(title)
        icfg = self.cfg["integrations"] if isinstance(self.cfg.data.get("integrations"), dict) else {}

        self.chk_mute_enabled = self._checkbox(
            "Mute other apps while recording",
            icfg.get("mute_while_recording", True),
            "Master switch. While you dictate, each enabled app below is sent its "
            "mute keybind so your dictation isn't transmitted into a voice call — "
            "then restored the moment the recording stops.",
        )
        layout.addWidget(self.chk_mute_enabled)
        layout.addWidget(self._hint(
            "For each app, the SAME key combination has to be set here and in "
            "that app. “Add app” offers the common ones with their documented "
            "mute keybind already filled in — each says underneath what it still "
            "needs, because most apps listen for their keybind only while they "
            "have focus and would otherwise do nothing at all here.\n"
            "For a custom entry prefer a modifier chord or an F-key, so the combo "
            "stays inert in the app you're dictating into."
        ))

        box = QGroupBox("Apps to mute")
        bv = QVBoxLayout(box)
        bv.setSpacing(8)
        self._targets_layout = QVBoxLayout()
        self._targets_layout.setSpacing(8)
        bv.addLayout(self._targets_layout)

        self._target_rows: list[MuteTargetRow] = []
        for target in icfg.get("targets") or []:
            if isinstance(target, dict):
                self._add_target_row(target)

        add_row = QHBoxLayout()
        add_btn = QPushButton("Add app")
        add_btn.setToolTip(
            "Add an app to mute while recording. The presets come with that "
            "app's documented mute keybind already filled in."
        )
        add_btn.setAutoDefault(False)
        # A menu rather than a blank row: an existing config keeps its own
        # target list on upgrade (a stored list replaces the defaults), so this
        # is the only way the presets reach anyone who is not a fresh install.
        add_menu = QMenu(add_btn)
        for preset in MUTE_PRESETS:
            keys = hotkey_label(preset["hotkey"]) or "no default key"
            action = add_menu.addAction(f"{preset['name']} ({keys})")
            action.triggered.connect(
                lambda _checked=False, p=preset: self._add_target_row({
                    "name": p["name"],
                    "enabled": True,
                    "mode": p["mode"],
                    "hotkey": p["hotkey"],
                })
            )
        add_menu.addSeparator()
        custom = add_menu.addAction("Other app…")
        custom.triggered.connect(
            lambda: self._add_target_row({"name": "", "enabled": True, "mode": "hold", "hotkey": ""})
        )
        add_btn.setMenu(add_menu)
        add_row.addWidget(add_btn)
        add_row.addStretch(1)
        bv.addLayout(add_row)
        layout.addWidget(box)

        layout.addStretch(1)
        return page

    def _add_target_row(self, data: dict) -> None:
        row = MuteTargetRow(data, self._capture_hotkey, self._remove_target_row)
        self._target_rows.append(row)
        self._targets_layout.addWidget(row)

    def _remove_target_row(self, row: MuteTargetRow) -> None:
        if row in self._target_rows:
            self._target_rows.remove(row)
        self._targets_layout.removeWidget(row)
        row.deleteLater()

    def _build_assistant(self, title: str) -> QWidget:
        page, layout = self._page(title)
        acfg = self.cfg["assistant"]

        self.chk_a_enabled = self._checkbox(
            "Post-process the transcript with an assistant (LLM)",
            acfg["enabled"],
            "Send the raw transcript through a language model for cleanup before it is inserted. "
            "Needs a running OpenAI-compatible endpoint.",
        )
        layout.addWidget(self.chk_a_enabled)
        layout.addWidget(self._hint(
            "Optional. Sends the transcript to an OpenAI-compatible API for cleanup — "
            "e.g. a local Ollama (default), LM Studio, llama.cpp or a hosted service."
        ))

        conn, form = self._card("Connection")
        self.a_url_edit = QLineEdit(acfg["base_url"])
        self.a_url_edit.setToolTip("Base URL of the OpenAI-compatible API, e.g. http://localhost:11434/v1 for Ollama.")
        form.addRow("API base URL:", self.a_url_edit)
        self.a_model_edit = QLineEdit(acfg["model"])
        self.a_model_edit.setToolTip("Model name as the endpoint knows it, e.g. llama3.2, qwen2.5:14b or gpt-4o-mini.")
        form.addRow("Model:", self.a_model_edit)
        self.a_key_edit = QLineEdit(acfg["api_key"])
        self.a_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.a_key_edit.setToolTip("Only needed for hosted services. Local Ollama/LM Studio usually run without a key.")
        form.addRow("API key (optional):", self.a_key_edit)
        self.a_temp_spin = QDoubleSpinBox()
        self.a_temp_spin.setRange(0.0, 2.0)
        self.a_temp_spin.setSingleStep(0.1)
        self.a_temp_spin.setDecimals(2)
        self.a_temp_spin.setValue(self._to_float(acfg["temperature"], 0.2))
        self.a_temp_spin.setToolTip("Keep low (0.0–0.3) for faithful cleanup; higher values rewrite more freely.")
        form.addRow("Temperature:", self.a_temp_spin)
        layout.addWidget(conn)

        prompt = QGroupBox("System prompt")
        pv = QVBoxLayout(prompt)
        header = QHBoxLayout()
        header.addStretch(1)
        reset = QPushButton("Reset to default")
        reset.setToolTip("Replace the prompt below with the built-in default cleanup prompt.")
        reset.clicked.connect(self._reset_prompt)
        header.addWidget(reset)
        pv.addLayout(header)
        self.a_prompt_edit = QPlainTextEdit(acfg["system_prompt"])
        self.a_prompt_edit.setToolTip(
            "Instructions for the assistant. The transcript is sent as the user message; "
            "whatever the model returns is inserted instead of the raw transcript."
        )
        self.a_prompt_edit.setMinimumHeight(160)
        pv.addWidget(self.a_prompt_edit)
        layout.addWidget(prompt, 1)

        return page

    def _build_history(self, title: str) -> QWidget:
        page, layout = self._page(title)

        top, form = self._card("History")
        self.chk_history_enabled = self._checkbox(
            "Keep a history of transcribed text",
            self.cfg["history_enabled"],
            "Store the transcribed text (never the audio) locally so you can copy it again here. "
            "Turn off to stop recording new entries; existing entries stay until cleared.",
        )
        form.addRow("", self.chk_history_enabled)
        self.history_max_spin = QSpinBox()
        self.history_max_spin.setRange(10, 5000)
        self.history_max_spin.setSingleStep(10)
        self.history_max_spin.setValue(self._to_int(self.cfg["history_max"], 200))
        self.history_max_spin.setToolTip("How many of the most recent transcripts to keep. Older ones are dropped.")
        form.addRow("Keep last:", self.history_max_spin)
        layout.addWidget(top)

        layout.addWidget(self._hint(
            "Stored locally on this computer only. Click a transcript's “Copy” button to put it back on the clipboard."
        ))

        # Find a transcript. Up to `history_max` (5000) entries are kept and 300
        # are rendered — scrolling for the one dictation you remember a few words
        # from is the only way to get at it otherwise.
        find_row = QWidget()
        fh = QHBoxLayout(find_row)
        fh.setContentsMargins(0, 0, 0, 0)
        fh.setSpacing(8)
        self.history_filter_edit = QLineEdit()
        self.history_filter_edit.setPlaceholderText("Search transcripts…")
        self.history_filter_edit.setClearButtonEnabled(True)
        # No form-row label to borrow a name from — see the progress bars.
        self.history_filter_edit.setAccessibleName("Search transcripts")
        self.history_filter_edit.setToolTip(
            "Show only transcripts containing these words (in any order, "
            "upper/lower case ignored). Clear the field to see all of them again."
        )
        self.history_filter_edit.textChanged.connect(self._on_history_filter_changed)
        fh.addWidget(self.history_filter_edit, 1)
        self.history_count_label = self._hint("")
        fh.addWidget(self.history_count_label)
        layout.addWidget(find_row)

        # Scrollable list of past transcripts, rendered lazily on first view.
        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_inner = QWidget()
        self._history_layout = QVBoxLayout(self._history_inner)
        self._history_layout.setContentsMargins(2, 2, 2, 2)
        self._history_layout.setSpacing(6)
        self._history_layout.addStretch(1)
        self._history_scroll.setWidget(self._history_inner)
        self._history_rendered = False
        layout.addWidget(self._history_scroll, 1)

        bottom = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Reload the list — useful if you recorded something while this window was open.")
        refresh.clicked.connect(self._refresh_history)
        bottom.addWidget(refresh)
        bottom.addStretch(1)
        # Enabled state is set by _refresh_history, which always runs before this
        # page can be reached (lazy first render): clicking it on an empty
        # history used to do nothing at all, which reads as a broken button.
        self.history_clear_button = QPushButton("Clear history")
        self.history_clear_button.setProperty("destructive", True)
        self.history_clear_button.setToolTip("Permanently delete every stored transcript.")
        self.history_clear_button.clicked.connect(self._clear_history)
        bottom.addWidget(self.history_clear_button)
        layout.addLayout(bottom)

        return page

    def _build_help(self, title: str) -> QWidget:
        page, layout = self._page(title)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)  # http(s) links → default browser
        browser.setToolTip("Common problems and fixes. Links open in your web browser.")
        self._help_browser = browser
        self._render_help()
        layout.addWidget(browser, 1)
        return page

    def _render_help(self) -> None:
        """(Re-)render the Help page. The document's default style sheet is
        baked into the rendered HTML, so a theme change needs both set again."""
        from . import help_content

        self._help_browser.document().setDefaultStyleSheet(self._help_stylesheet())
        self._help_browser.setHtml(help_content.help_html())

    def _on_color_scheme_changed(self, *_args) -> None:
        """The OS switched between light and dark: repaint everything this
        window drew in code with the old palette. theme.py has already swapped
        the application palette and style sheet by the time this runs."""
        from .theme import ACCENT, tokens

        colors = tokens()
        try:
            for title, row in self._nav_row.items():
                glyph = _NAV_GLYPHS.get(title)
                item = self.nav.item(row)
                if glyph and item is not None:
                    item.setIcon(glyph_icon(glyph, colors["muted"], ACCENT, size=18))
            self.home.restyle_icons(colors["muted"], ACCENT)
            self.repo_button.setIcon(glyph_icon("link", colors["muted"], ACCENT, size=14))
            self._render_help()
        except Exception:
            log.debug("could not restyle the theme-dependent visuals", exc_info=True)

    @staticmethod
    def _help_stylesheet() -> str:
        """A tiny theme-aware style sheet for the Help browser: accent links and
        a subtle background behind inline <code> so DLL/command names stand out."""
        from .theme import ACCENT, is_dark

        code_bg = "#3a3d41" if is_dark() else "#eceef1"
        return (
            f"a {{ color: {ACCENT}; }}"
            f"h3 {{ margin-top: 4px; }}"
            f"code {{ background-color: {code_bg}; }}"
        )

    def show_help_page(self) -> None:
        """Open the Help / Troubleshooting page (used by the tray menu)."""
        self._show_page("Help")

    # ------------------------------------------------------ small helpers

    def _refresh_autostart_status(self) -> None:
        """Mirror the real OS autostart state below the checkbox — including
        the two states that are invisible in the config: an entry Windows has
        switched off, and one pointing at a program file that moved.

        The line itself names only the program file (a full path has nothing to
        wrap at and would widen the page); the command the OS really has on file
        goes into the tooltip, where its length costs nothing."""
        from . import autostart

        _healthy, text = autostart.describe(self.chk_autostart.isChecked())
        self.autostart_status.setText(text)
        self.autostart_status.setVisible(bool(text))
        try:
            stored = autostart.stored_command()
        except Exception:
            stored = None
        self.autostart_status.setToolTip(
            f"Registered command:\n{stored}" if stored else ""
        )

    def _checkbox(self, text: str, checked: bool, tip: str) -> QCheckBox:
        chk = QCheckBox(text)
        chk.setChecked(bool(checked))
        chk.setToolTip(tip)
        return chk

    def _on_page_changed(self, row: int) -> None:
        item = self.nav.item(row)
        index = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if index is None:
            return  # a section header, not a page
        self.stack.setCurrentIndex(index)
        # Home always re-reads config + history — cheap, and it may have gone
        # stale while the user edited other pages or dictated.
        if index == self._home_index:
            self.home.refresh()
        # Build the transcript rows only when the History page is first shown.
        if index == self._history_index and not self._history_rendered:
            self._refresh_history()
        # Probe the hardware/model status the first time the Whisper page is
        # opened (not at construction: the probe imports heavy libraries).
        if index == self._whisper_index and not self._status_probed:
            self._status_probed = True
            self._refresh_hw_status()
        # Check for updates the first time the Updates page is opened.
        if index == self._updates_index and not self._updates_auto_checked:
            self._updates_auto_checked = True
            self._check_updates()

    def _show_page(self, title: str) -> None:
        """Switch the sidebar (and with it the stack) to the page `title`."""
        self.nav.setCurrentRow(self._nav_row[title])

    def _capture_hotkey(self) -> str | None:
        """Open the key picker with the live global hotkey paused, otherwise
        pressing keys to pick a combo would trigger a real recording behind the
        dialog. Nothing is applied until Save, so the old hotkey is restored."""
        if self._app_busy():
            # Same guard as the tests: stopping the app's listener
            # mid-recording would lose a hold-mode release, leaving the
            # recording running until the max-length cap.
            self.app.notify("Finish the current recording first, then pick the hotkey.")
            return None
        if self._hotkey_test is not None:
            # A running hotkey test would swallow the picker's key presses.
            self._finish_hotkey_test("")
        self.app.hotkeys.stop()
        try:
            return HotkeyCaptureDialog.ask(self)
        finally:
            if not self._hotkey_paused:
                # Still paused = a recording diagnostic owns the listener and
                # re-registers it when it ends (same rule as the hotkey test) —
                # reviving the hotkey here would take the mic away from it.
                self.app._register_hotkey()

    def _pick_hotkey(self) -> None:
        combo = self._capture_hotkey()
        if combo:
            self.hotkey_edit.setText(combo)

    def _browse_model_dir(self) -> None:
        initial = self.model_dir_edit.text().strip() or str(default_model_dir())
        chosen = QFileDialog.getExistingDirectory(self, "Choose model download folder", initial)
        if chosen:
            self.model_dir_edit.setText(chosen)

    def _open_model_dir(self) -> None:
        from pathlib import Path

        path = Path(self.model_dir_edit.text().strip() or default_model_dir())
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # A hand-typed path can be invalid (no such drive) or unwritable —
            # a slot that raises leaves a button that looks alive and does
            # nothing.
            log.exception("could not create the model folder %s", path)
            self.app.notify(f"Could not open the model folder: {exc}", force=True)
            return
        open_path(path)

    def _load_devices(self) -> None:
        # Refresh keeps an unsaved on-screen choice: repopulating from the
        # saved config would silently revert the device the user just picked.
        stored = self.cfg["input_device"]
        if self.input_combo.count():
            stored = self._selected_input_device()
        values, current = input_device_choices(stored)
        self.input_combo.clear()
        self.input_combo.addItems(values)
        self.input_combo.setCurrentText(current)

    def _reset_prompt(self) -> None:
        self.a_prompt_edit.setPlainText(DEFAULT_ASSISTANT_PROMPT)

    # --------------------------------------------------------- diagnostics

    def _app_busy(self) -> bool:
        """Whether the app is recording or transcribing right now — the guard
        every test that borrows the microphone or the hotkey listener runs.

        A hotkey press posted by the listener thread can sit in App's event
        queue for up to one poll tick (100 ms), so App.state alone is stale:
        hold the combo and start a test within that window and the guard would
        pass, the test takes over, and the queued press then starts a recording
        whose release is never delivered. Draining the queue first applies the
        press before the state is read.
        """
        poll = getattr(self.app, "_poll", None)
        if callable(poll):
            try:
                poll()
            except Exception:
                log.debug("could not drain the app event queue", exc_info=True)
        return getattr(self.app, "state", "idle") != "idle"

    def _diag_snapshot(self) -> dict:
        """The UI values the transcribers read, as a plain dict — so the
        diagnostics test exactly what is entered right now, saved or not."""
        return {
            "backend": self._selected_backend(),
            "model": self._selected_model(),
            "device": self.device_combo.currentText(),
            "compute_type": self.compute_combo.currentText(),
            "beam_size": int(self.beam_spin.value()),
            "model_dir": self.model_dir_edit.text().strip() or None,
            "language": self._selected_language(),
            "initial_prompt": self.initial_prompt_edit.toPlainText().strip(),
            "vad_filter": self.chk_vad.isChecked(),
            "openvino_device": self.ov_device_combo.currentText(),
            "openvino_precision": self.ov_precision_combo.currentText(),
            "parakeet_quantization": self.pk_quant_combo.currentText(),
        }

    def _set_hotkey_paused(self, paused: bool) -> None:
        """Pause/resume the app's global hotkey listener around a diagnostic
        that records. Pressing the hotkey mid-test would open a second
        PortAudio input stream on the same device (both keep working in shared
        mode, but the statuses interleave) — the hotkey test pauses it for the
        same reason."""
        if paused == self._hotkey_paused:
            return
        self._hotkey_paused = paused
        if self._hotkey_test is not None:
            # The hotkey test already borrowed the listener and re-registers it
            # itself when it ends — handing out a second one would double it.
            return
        try:
            if paused:
                self.app.hotkeys.stop()
            else:
                self.app._register_hotkey()
        except Exception:
            log.debug("could not toggle the global hotkey for a diagnostic", exc_info=True)

    def _set_diag_busy(self, busy: bool, kind: str | None = None) -> None:
        # One diagnostic at a time: they share the recorder/model, and two
        # concurrent tests would interleave their status output anyway.
        self._diag_busy = busy
        self._diag_kind = kind if busy else None
        for button in (self.model_download_button, self.tx_test_button, self.mic_test_button):
            button.setEnabled(not busy)
        # Only the Cancel button next to the running diagnostic is active.
        self.diag_cancel_button.setEnabled(busy and kind in ("model", "tx"))
        self.mic_cancel_button.setEnabled(busy and kind == "mic")
        # Only the tests that record own the microphone; a model download can
        # run for minutes and must not take dictation away for that long.
        self._set_hotkey_paused(busy and kind in ("tx", "mic"))
        # The diagnostics share the recorder and the model, so starting one
        # disables the buttons on the *other* page too. Switching there and
        # finding them greyed out with an empty status line reads as broken —
        # say what is going on. The caller writes the running test's own status
        # after this, so only the idle page keeps the note.
        self._note_diag_wait(self.mic_status, busy and kind != "mic", "")
        self._note_diag_wait(self.diag_status, busy and kind == "mic", _DIAG_STATUS_IDLE)

    @staticmethod
    def _note_diag_wait(label: QLabel, waiting: bool, idle_text: str) -> None:
        """Show/clear the "another test is running" note without clobbering a
        result message: the text the note replaced is stashed on the label and
        put back when the note clears, so a mic result survives a model
        download on the other page."""
        if waiting:
            if label.text() != _DIAG_BUSY_NOTE:
                label.setProperty("_pre_note_text", label.text())
                label.setText(_DIAG_BUSY_NOTE)
        elif label.text() == _DIAG_BUSY_NOTE:
            stashed = label.property("_pre_note_text")
            label.setText(stashed if isinstance(stashed, str) and stashed else idle_text)

    def _begin_diag(self, kind: str) -> tuple[int, threading.Event]:
        """Mark a diagnostic as started; returns its (generation, cancel event).
        The worker captures both: results are delivered with the generation (so
        stale ones are dropped) and the event is its cooperative stop flag."""
        self._diag_gen += 1
        cancel = threading.Event()
        self._diag_cancel_event = cancel
        self._set_diag_busy(True, kind)
        return self._diag_gen, cancel

    def _cancel_diagnostic(self) -> None:
        """Stop the running diagnostic (Cancel buttons + the dialog-close path).

        Recording loops poll the cancel event and stop within ~100 ms. A model
        download can't be interrupted mid-request, so its worker is detached
        instead: the generation bump makes every signal it still emits stale,
        and the engine is replaced so the next diagnostic never shares a
        transcriber with it (the old worker finishes on the old engine
        harmlessly — see the done() comment)."""
        if not self._diag_busy:
            return
        kind = self._diag_kind
        self._diag_gen += 1
        if self._diag_cancel_event is not None:
            self._diag_cancel_event.set()
        self._diag = DiagnosticsEngine()
        self._set_diag_busy(False)
        self._begin_diag_cooldown()
        if kind == "mic":
            self.mic_level_bar.setValue(0)
            self.mic_status.setText("Microphone test cancelled.")
            return
        self.diag_progress.setVisible(False)
        if kind == "model":
            self.diag_status.setText(
                "Cancelled. A download that already started may finish in the "
                "background — anything already fetched is reused next time."
            )
        else:
            self.diag_status.setText("Transcription test cancelled.")

    def _begin_diag_cooldown(self) -> None:
        """Keep the start buttons disabled for a moment after a Cancel.

        The cancelled worker is detached, not stopped: a recording loop needs
        up to a poll tick to release its input stream (restarting instantly
        would briefly open a second one on the same device), and a model
        download keeps running, so an immediate retry would start a second
        snapshot_download of the same repo in parallel."""
        for button in (self.model_download_button, self.tx_test_button, self.mic_test_button):
            button.setEnabled(False)
        self._diag_cooldown_timer.start()

    def _end_diag_cooldown(self) -> None:
        if self._diag_busy:
            return  # a new diagnostic owns the buttons now
        for button in (self.model_download_button, self.tx_test_button, self.mic_test_button):
            button.setEnabled(True)

    def _on_diag_status(self, gen: int, message: str) -> None:
        if gen != self._diag_gen:
            return
        self.diag_status.setText(message)

    def _download_model(self) -> None:
        if self._diag_busy:
            return
        snapshot = self._diag_snapshot()
        gen, _cancel = self._begin_diag("model")
        self.diag_progress.setRange(0, 0)  # indeterminate — no byte progress
        self.diag_progress.setVisible(True)
        self.diag_status.setText(f"Preparing model '{snapshot['model']}'…")

        def work():
            try:
                message = self._diag.prepare_model(
                    snapshot,
                    notify=lambda text, force=False: self._dsig.model_status.emit(gen, str(text)),
                )
                self._dsig.model_done.emit(gen, message)
            except Exception as exc:  # surfaced in the UI
                log.exception("model download/load failed")
                self._dsig.model_failed.emit(gen, str(exc))

        threading.Thread(target=work, name="diag-model", daemon=True).start()

    def _on_model_done(self, gen: int, message: str) -> None:
        if gen != self._diag_gen:
            return
        self._set_diag_busy(False)
        self.diag_progress.setVisible(False)
        self.diag_status.setText(message)
        # The model just landed on disk — flip the status card's model line.
        if self._status_probed:
            self._status_timer.start()

    def _on_model_failed(self, gen: int, message: str) -> None:
        if gen != self._diag_gen:
            return
        self._set_diag_busy(False)
        self.diag_progress.setVisible(False)
        self.diag_status.setText(f"Model download/load failed: {message}")

    def _test_transcription(self) -> None:
        if self._diag_busy:
            return
        if self._app_busy():
            self.diag_status.setText("Finish the current recording first, then run the test.")
            return
        snapshot = self._diag_snapshot()
        device = self._selected_input_device()
        gen, cancel = self._begin_diag("tx")
        self.diag_progress.setRange(0, 0)  # indeterminate while the model loads
        self.diag_progress.setVisible(True)
        self.diag_status.setText("Preparing model…")

        def work():
            try:
                text = self._diag.transcription_test(
                    snapshot,
                    device,
                    seconds=5.0,
                    on_status=lambda message: self._dsig.tx_status.emit(gen, str(message)),
                    on_level=lambda level: self._dsig.tx_level.emit(gen, float(level)),
                    is_cancelled=cancel.is_set,
                )
                self._dsig.tx_done.emit(gen, text)
            except Exception as exc:  # surfaced in the UI
                log.exception("transcription test failed")
                self._dsig.tx_failed.emit(gen, str(exc))

        threading.Thread(target=work, name="diag-transcribe", daemon=True).start()

    def _on_tx_level(self, gen: int, level: float) -> None:
        if gen != self._diag_gen:
            return
        # First level tick = recording started: switch the bar from the
        # indeterminate "loading model" state to a live input level meter.
        if self.diag_progress.maximum() == 0:
            self.diag_progress.setRange(0, 100)
        self.diag_progress.setValue(int(level * 100))

    def _on_tx_done(self, gen: int, text: str) -> None:
        if gen != self._diag_gen:
            return
        self._set_diag_busy(False)
        self.diag_progress.setVisible(False)
        if text:
            self.diag_status.setText(f"Transcription works ✓ — result: “{text}”")
        else:
            self.diag_status.setText(
                "No speech detected in the test recording — try the microphone "
                "test on the Audio page."
            )

    def _on_tx_failed(self, gen: int, message: str) -> None:
        if gen != self._diag_gen:
            return
        self._set_diag_busy(False)
        self.diag_progress.setVisible(False)
        self.diag_status.setText(f"Transcription test failed: {message}")

    def _test_microphone(self) -> None:
        if self._diag_busy:
            return
        if self._app_busy():
            self.mic_status.setText("Finish the current recording first, then run the test.")
            return
        device = self._selected_input_device()
        gen, cancel = self._begin_diag("mic")
        self.mic_level_bar.setValue(0)
        self.mic_status.setText("Recording 3 s — speak now…")

        def work():
            try:
                result = self._diag.mic_test(
                    device,
                    seconds=3.0,
                    on_level=lambda level: self._dsig.mic_level.emit(gen, float(level)),
                    is_cancelled=cancel.is_set,
                )
                self._dsig.mic_done.emit(gen, result)
            except Exception as exc:  # surfaced in the UI
                log.exception("microphone test failed")
                self._dsig.mic_failed.emit(gen, str(exc))

        threading.Thread(target=work, name="diag-mic", daemon=True).start()

    def _on_mic_level(self, gen: int, level: float) -> None:
        if gen != self._diag_gen:
            return
        self.mic_level_bar.setValue(int(level * 100))

    def _on_mic_done(self, gen: int, result: dict) -> None:
        if gen != self._diag_gen:
            return
        self._set_diag_busy(False)
        peak = int(result["peak"] * 100)
        verdict = result["verdict"]
        if verdict == "silent":
            self.mic_status.setText(
                "No signal — check that the right device is selected and the "
                "OS allows microphone access."
            )
        elif verdict == "quiet":
            self.mic_status.setText(
                f"Signal is very quiet (peak {peak} %) — move closer to the "
                "microphone or raise its input volume."
            )
        else:
            self.mic_status.setText(f"Microphone works ✓ — peak level {peak} %.")

    def _on_mic_failed(self, gen: int, message: str) -> None:
        if gen != self._diag_gen:
            return
        self._set_diag_busy(False)
        self.mic_status.setText(f"Microphone test failed: {message}")

    def _test_hotkey(self) -> None:
        if self._hotkey_test is not None:
            return  # already listening
        if self._app_busy():
            # Stopping the app's listener mid-recording would lose a hold-mode
            # release, leaving the recording stuck until stopped via the overlay
            # — including a press still sitting in the queue (see _app_busy).
            self.hotkey_test_status.setText("Finish the current recording first, then run the test.")
            return
        combo = self.hotkey_edit.text().strip()
        if not Hotkeys.validate(combo):
            self.hotkey_test_status.setText("Invalid hotkey — fix the combination first.")
            return
        # Pause the app's real listener so the test press can't start a real
        # recording behind the dialog (same pattern as _capture_hotkey).
        self.app.hotkeys.stop()
        test = Hotkeys(lambda: self._dsig.hotkey_detected.emit())
        try:
            test.register(combo, mode="toggle")
        except Exception as exc:
            log.exception("could not register the test hotkey")
            self.app._register_hotkey()
            self.hotkey_test_status.setText(f"Could not listen for the hotkey: {exc}")
            return
        self._hotkey_test = test
        self._hotkey_test_gen += 1
        generation = self._hotkey_test_gen
        self.hotkey_test_button.setEnabled(False)
        self.hotkey_test_status.setText(f"Press {combo} now…")
        QTimer.singleShot(
            _HOTKEY_TEST_TIMEOUT_MS, lambda: self._hotkey_test_timeout(generation)
        )

    def _on_hotkey_detected(self) -> None:
        if self._hotkey_test is None:
            return
        self._finish_hotkey_test("Hotkey works ✓ — combination detected.")

    def _hotkey_test_timeout(self, generation: int) -> None:
        if self._hotkey_test is None or generation != self._hotkey_test_gen:
            return
        self._finish_hotkey_test(
            "Nothing detected within 10 s — check the combination, or set it "
            "via “Change…”."
        )

    def _finish_hotkey_test(self, message: str) -> None:
        """Stop the temporary test listener, give the global hotkey back to
        the app and show `message` (also used as the cancel path on close)."""
        test, self._hotkey_test = self._hotkey_test, None
        if test is not None:
            try:
                test.stop()
            except Exception:
                log.debug("error stopping the test hotkey listener", exc_info=True)
        if not self._hotkey_paused:
            # Still paused = a recording diagnostic is running and owns the
            # listener; it re-registers when it ends.
            self.app._register_hotkey()
        self.hotkey_test_button.setEnabled(True)
        self.hotkey_test_status.setText(message)

    def _cancel_diagnostics(self) -> None:
        """Stop any running diagnostic when the dialog closes: unblock the
        recording loops and give the global hotkey back to the app."""
        self._cancel_diagnostic()
        # Closing the window also aborts a running update download — silently
        # swapping the exe after the user dismissed the dialog would surprise.
        if self._update_cancel_event is not None:
            self._update_cancel_event.set()
        # Drop the cached test transcriber so a test model (potentially GBs of
        # RAM) doesn't stay loaded after the dialog closes — App keeps a
        # reference to the closed window until Settings is opened again. A
        # still-running worker holds its own reference and finishes on the old
        # engine harmlessly; the model is freed when the last reference goes.
        self._diag = DiagnosticsEngine()
        if self._hotkey_test is not None:
            self._finish_hotkey_test("")

    # ------------------------------------------------ hardware/model status

    def _refresh_hw_status(self) -> None:
        """Probe CUDA/OpenVINO/model-cache on a worker thread and fill the
        Whisper page's status card. Guarded like the other diagnostics: one
        probe at a time, stale results dropped via the generation."""
        if self._hw_busy:
            return
        self._hw_busy = True
        self._hw_gen += 1
        gen = self._hw_gen
        self.hw_refresh_button.setEnabled(False)
        for label in (self.hw_cuda_label, self.hw_ov_label, self.hw_model_label):
            label.setText("Checking…")
        snapshot = self._diag_snapshot()

        def work():
            from . import diagnostics

            # hardware_status never raises — each probe reports its own error.
            self._dsig.hw_done.emit(gen, diagnostics.hardware_status(snapshot))

        threading.Thread(target=work, name="diag-hw", daemon=True).start()

    def _on_status_inputs_changed(self, *_args) -> None:
        # Debounced: typing in the model-folder field triggers one probe, not
        # one per keystroke. Nothing happens until the card was first probed.
        if self._status_probed:
            self._status_timer.start()

    def _maybe_refresh_status(self) -> None:
        if self._hw_busy:
            self._status_timer.start()  # retry once the running probe returns
        else:
            self._refresh_hw_status()

    def _on_hw_done(self, gen: int, result: dict) -> None:
        if gen != self._hw_gen:
            return
        self._hw_busy = False
        self.hw_refresh_button.setEnabled(True)
        self.hw_cuda_label.setText(self._format_cuda_status(result["cuda"]))
        self.hw_ov_label.setText(self._format_openvino_status(result["openvino"]))
        self.hw_model_label.setText(self._format_model_status(result["model"]))

    @staticmethod
    def _format_cuda_status(info: dict) -> str:
        if info["available"]:
            count = info["count"]
            gpus = f"{count} CUDA GPU{'s' if count != 1 else ''}"
            return f"✓ {gpus} found — the faster-whisper backend can use it."
        if info["error"]:
            return f"✗ could not check: {info['error']}"
        return (
            "✗ no NVIDIA GPU / CUDA runtime found — the faster-whisper "
            "backend runs on the CPU (see Help to enable the GPU)."
        )

    @staticmethod
    def _format_openvino_status(info: dict) -> str:
        if not info["installed"]:
            detail = f": {info['error']}" if info["error"] else (
                " — pip install openvino-genai (the portable Windows build includes it)."
            )
            return f"✗ openvino-genai is not installed{detail}"
        if info["devices"]:
            parts = [
                f"{d['device']} ({d['name']})" if d["name"] else d["device"]
                for d in info["devices"]
            ]
            return f"✓ installed — devices: {', '.join(parts)}"
        if info["error"]:
            return f"⚠ installed, but the device probe failed: {info['error']}"
        return "⚠ installed, but no devices were reported — check the Intel driver."

    @staticmethod
    def _format_model_status(info: dict) -> str:
        if info["error"]:
            return f"⚠ {info['error']}"
        if info["cached"]:
            return f"✓ '{info['target']}' is downloaded — it loads straight from disk."
        return (
            f"'{info['target']}' is not downloaded yet — use “Download / load "
            "model” below, or it is fetched automatically on first use."
        )

    def done(self, result: int) -> None:
        # Covers every way the dialog closes: Save, Cancel, Esc and the
        # window's close button.
        self._cancel_diagnostics()
        super().done(result)

    # ------------------------------------------------------------- updates

    def _build_updates(self, title: str) -> QWidget:
        page, layout = self._page(title)

        card, form = self._card("This version")
        self.update_current_label = QLabel(__version__)
        form.addRow("Installed:", self.update_current_label)
        self.chk_update_on_start = self._checkbox(
            "Check for updates on startup",
            self.cfg["update_check_on_start"],
            "On launch, quietly check the GitHub releases and notify you if a newer version exists.",
        )
        form.addRow("", self.chk_update_on_start)
        self.chk_prereleases = self._checkbox(
            "Include pre-releases",
            self.cfg["include_prereleases"],
            "Also offer pre-release (beta) builds, not just stable releases.",
        )
        form.addRow("", self.chk_prereleases)
        self.update_check_button = QPushButton(_CHECK_LABEL)
        self.update_check_button.setAutoDefault(False)
        self._pin_width(self.update_check_button, _CHECK_LABEL, _CHECKING_LABEL)
        self.update_check_button.setToolTip("Fetch the latest releases from GitHub now.")
        self.update_check_button.clicked.connect(self._check_updates)
        form.addRow("", self.update_check_button)
        layout.addWidget(card)

        self.update_status = self._hint("Not checked yet.", elastic=True)
        layout.addWidget(self.update_status)

        self.update_list = QListWidget()
        self.update_list.setAccessibleName("Available releases")
        self.update_list.setMaximumHeight(140)
        self.update_list.currentRowChanged.connect(self._on_release_selected)
        self.update_list.setToolTip(
            "Newer releases, newest first. Pick one to read its changelog — you can jump "
            "straight to any of them, skipping the ones in between."
        )
        layout.addWidget(self.update_list)

        self.update_changelog = QTextBrowser()
        self.update_changelog.setAccessibleName("Changelog of the selected release")
        # NOT setOpenExternalLinks(True): that hands every non-local URL to
        # QDesktopServices, i.e. to the OS handler for whatever scheme it
        # carries — and the changelog body is whatever the releases API
        # returned, the same response updater.release_page_url() already
        # refuses to trust blindly. Links are opened by _open_changelog_link
        # instead, which only lets http(s) through.
        self.update_changelog.setOpenExternalLinks(False)
        self.update_changelog.setOpenLinks(False)
        self.update_changelog.anchorClicked.connect(self._open_changelog_link)
        layout.addWidget(self.update_changelog, 1)

        self.update_progress = QProgressBar()
        self.update_progress.setAccessibleName("Update download progress")
        self.update_progress.setVisible(False)
        layout.addWidget(self.update_progress)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.update_cancel_button = QPushButton("Cancel download")
        self.update_cancel_button.setAutoDefault(False)
        self.update_cancel_button.setVisible(False)
        self.update_cancel_button.setToolTip(
            "Stop the running download — nothing is installed, the partial "
            "file is deleted."
        )
        self.update_cancel_button.clicked.connect(self._cancel_update_download)
        actions.addWidget(self.update_cancel_button)
        self.update_button = QPushButton("Install selected")
        self.update_button.setProperty("accent", True)
        self.update_button.setAutoDefault(False)
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self._install_selected_update)
        actions.addWidget(self.update_button)
        layout.addLayout(actions)
        return page

    def show_updates_page(self) -> None:
        """Open the Updates page and start a fresh check (used by the tray)."""
        self._show_page("Updates")
        self._updates_auto_checked = True
        self._check_updates()

    def _check_updates(self) -> None:
        if self._update_busy:
            return
        self._update_busy = True
        # Opening the page starts this check automatically, so the buttons are
        # dead for the length of a GitHub round trip exactly when the user
        # reaches for them. The greyed-out styling says "not now"; the label
        # says why, right where they are clicking.
        self.update_check_button.setEnabled(False)
        self.update_check_button.setText(_CHECKING_LABEL)
        self.update_button.setEnabled(False)
        self.update_list.clear()
        self.update_changelog.clear()
        self.update_status.setText("Checking for updates…")
        include_pre = self.chk_prereleases.isChecked()

        def work():
            try:
                from . import updater

                releases = updater.fetch_releases(include_prerelease=include_pre)
                self._usig.checked.emit(updater.newer_releases(releases))
            except Exception as exc:  # surfaced in the UI
                self._usig.check_failed.emit(str(exc))

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _on_update_check_done(self, newer: list) -> None:
        from . import updater

        self._update_busy = False
        self._end_update_check()
        self._releases_newer = newer
        self.update_list.clear()
        if not newer:
            self.update_status.setText("You're on the latest version.")
            self.update_changelog.clear()
            self.update_button.setEnabled(False)
            return
        self.update_status.setText(
            f"{len(newer)} newer release{'s' if len(newer) != 1 else ''} available."
        )
        for release in newer:
            label = f"{release.tag or release.title}   ·   {release.date}"
            # How big the download is belongs next to the version, not only in
            # the confirmation — it is the deciding factor on a slow line.
            size = updater.format_size(release.asset_size)
            if size:
                label += f"   ·   {size}"
            if release.prerelease:
                label += "   (pre-release)"
            self.update_list.addItem(label)
        self.update_list.setCurrentRow(0)  # latest: shows changelog, enables the button

    def _on_update_check_failed(self, message: str) -> None:
        self._update_busy = False
        self._end_update_check()
        self.update_button.setEnabled(False)
        self.update_status.setText(f"Update check failed: {message}")

    def _end_update_check(self) -> None:
        """Hand the check button back to the user (both check outcomes)."""
        self.update_check_button.setEnabled(True)
        self.update_check_button.setText(_CHECK_LABEL)

    def _on_release_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._releases_newer):
            self.update_changelog.clear()
            self.update_button.setEnabled(False)
            return
        release = self._releases_newer[row]
        self.update_changelog.setMarkdown(release.body or "_No changelog provided._")
        from . import updater

        if updater.can_self_update() and release.asset_url:
            self.update_button.setText("Download && install")
            self.update_button.setToolTip("Download this version and restart to apply it.")
        else:
            self.update_button.setText("Open release page")
            self.update_button.setToolTip("Open this release on GitHub to download it manually.")
        self.update_button.setEnabled(True)

    def _open_repo(self) -> None:
        """Open the GitHub project page (footer button, bottom left).

        REPO_URL is a package constant, not network-supplied text, so it needs
        none of the scheme/host checks the changelog and release links get.
        The launch itself can still fail (no browser registered, a broken
        BROWSER env), and webbrowser.open() reports that as False instead of
        raising — unreported, the button would just look dead.
        """
        opened = False
        try:
            opened = webbrowser.open(REPO_URL)
        except Exception:
            log.exception("could not open the project page")
        if not opened:
            # The URL itself stays in the tooltip; a full URL here would
            # stretch the footer and push the action buttons around.
            self.footer_status.setText("Could not open your browser")
            self._footer_status_timer.start()

    def _open_changelog_link(self, url) -> None:
        """Open a link the user clicked inside a release changelog.

        Only http(s) is passed on. The changelog is markdown from the releases
        API, so its links are network-supplied text — and an OS URL handler
        takes far more than a web address (``file:``, ``mailto:``, vendor
        schemes). Same reasoning as :func:`updater.release_page_url`, which
        host-checks the release URL out of the very same API response; here the
        scheme is the part worth pinning, since a changelog may legitimately
        link anywhere on the web.
        """
        target = url.toString()
        if url.scheme().lower() not in ("http", "https"):
            log.warning("ignoring a changelog link with an unexpected scheme: %r", target)
            return
        webbrowser.open(target)

    def _install_selected_update(self) -> None:
        row = self.update_list.currentRow()
        if row < 0 or row >= len(self._releases_newer):
            return
        release = self._releases_newer[row]
        from . import updater

        if not (updater.can_self_update() and release.asset_url):
            # Via updater, not release.html_url directly: the URL comes from the
            # API response and webbrowser.open() would hand any scheme to the OS.
            webbrowser.open(updater.release_page_url(release))
            return
        size = updater.format_size(release.asset_size)
        confirm = QMessageBox.question(
            self,
            APP_NAME,
            f"Download {release.tag}{f' ({size})' if size else ''} and restart "
            f"{APP_NAME} to update?\n\n"
            f"{APP_NAME} will close, replace its program file and reopen automatically.\n\n"
            "The download is not code-signed (Windows SmartScreen may warn).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._start_update_download(release)

    def _start_update_download(self, release) -> None:
        if self._update_busy:
            return
        self._update_busy = True
        cancel = threading.Event()
        self._update_cancel_event = cancel
        self.update_button.setEnabled(False)
        self.update_check_button.setEnabled(False)
        self.update_cancel_button.setVisible(True)
        self.update_cancel_button.setEnabled(True)
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.update_progress.setVisible(True)
        # Named once here so every progress line can repeat which version is
        # being fetched without re-reading the (selectable) release list.
        self._update_download_label = release.tag or release.title
        self.update_status.setText(f"Downloading {self._update_download_label}…")
        from . import updater

        url = release.asset_url
        dest = updater.download_path_for()

        def work():
            try:
                updater.download_asset(
                    url,
                    dest,
                    progress_cb=lambda done, total: self._usig.progress.emit(done, total),
                    is_cancelled=cancel.is_set,
                )
                if cancel.is_set():
                    # Cancel raced the last chunk — still counts as cancelled.
                    raise updater.DownloadCancelled()
                # Still on the worker thread: hashing a ~200 MB exe must not
                # block the UI, and a bad file must never reach the swap.
                updater.verify_download(dest, release.asset_size, release.asset_digest)
                self._usig.downloaded.emit(str(dest))
            except updater.DownloadCancelled:
                try:  # never leave a partial download next to the exe
                    dest.unlink(missing_ok=True)
                except OSError:
                    log.warning("could not remove cancelled update download %s", dest)
                self._usig.download_cancelled.emit()
            except Exception as exc:  # surfaced in the UI
                try:  # never leave a broken half-download next to the exe
                    dest.unlink(missing_ok=True)
                except OSError:
                    log.warning("could not remove failed update download %s", dest)
                self._usig.download_failed.emit(str(exc))

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _cancel_update_download(self) -> None:
        if self._update_cancel_event is not None:
            self._update_cancel_event.set()
        # Feedback right away; the worker confirms via download_cancelled.
        self.update_cancel_button.setEnabled(False)
        self.update_status.setText("Cancelling download…")

    def _on_update_progress(self, done: int, total: int) -> None:
        from . import updater

        if total > 0:
            self.update_progress.setRange(0, 100)
            self.update_progress.setValue(int(done * 100 / total))
            text = (
                f"Downloading {self._update_download_label} — "
                f"{updater.format_size(done)} of {updater.format_size(total)}"
            )
        else:
            self.update_progress.setRange(0, 0)  # indeterminate
            # No Content-Length: the bar can only spin, so the amount already
            # downloaded is the only sign the transfer is still moving.
            text = (
                f"Downloading {self._update_download_label} — "
                f"{updater.format_size(done)} so far"
            )
        # progress_cb fires per 256 KB chunk — several hundred times for the
        # portable build. Relabel only when the text actually changed.
        if text != self.update_status.text():
            self.update_status.setText(text)

    def _on_update_downloaded(self, path: str) -> None:
        from pathlib import Path

        from . import updater

        if self._update_cancel_event is not None and self._update_cancel_event.is_set():
            # Cancel arrived between the worker's last check and this handler:
            # never swap the exe after the user said no.
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                log.warning("could not remove cancelled update download %s", path)
            self._on_update_download_cancelled()
            return
        self._update_busy = False
        self.update_cancel_button.setVisible(False)
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(100)

        try:
            updater.apply_update_windows(Path(path))
        except Exception as exc:  # surfaced in the UI
            log.exception("could not apply update")
            self._end_update_download(f"Could not apply update: {exc}")
            return
        self.update_status.setText("Update downloaded — restarting…")
        # Quit so the detached swapper can replace the (now unlocked) exe.
        self.app.post("quit")

    def _end_update_download(self, status: str) -> None:
        """Put the page back into its idle state after a download ended badly.

        Every non-restarting outcome routes through here — a failed download, a
        cancelled one, and a download that arrived but could not be swapped in.
        The three used to reset the page on their own and had already drifted:
        the failed-swap path left the progress bar sitting at 100 %, so "Could
        not apply update" was reported underneath a full bar that reads as
        success.
        """
        self._update_busy = False
        self.update_cancel_button.setVisible(False)
        self.update_progress.setVisible(False)
        self.update_check_button.setEnabled(True)
        self.update_button.setEnabled(True)
        self.update_status.setText(status)

    def _on_update_download_failed(self, message: str) -> None:
        self._end_update_download(f"Download failed: {message}")

    def _on_update_download_cancelled(self) -> None:
        self._end_update_download("Download cancelled — nothing was installed.")

    # ---------------------------------------------------------- history UI

    def _clear_history_rows(self) -> None:
        # Remove every row widget but keep the trailing stretch. Detach + hide
        # before deleteLater: the deletion only happens once the event loop
        # runs, and a still-parented row keeps painting until then — visible as
        # ghost rows behind the freshly inserted ones when the list is rebuilt
        # twice in one pass (page change + a finished dictation). Same fix as
        # HomePage._clear_layout.
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _on_history_filter_changed(self, *_args) -> None:
        """Re-render debounced: rebuilding up to 300 transcript rows on every
        keystroke stutters, so wait until the typing pauses briefly.
        (*_args: textChanged passes the new text, which is read from the field.)"""
        self._history_filter_timer.start()

    def _refresh_history(self) -> None:
        from .history import filter_entries

        self._history_rendered = True
        self._history_filter_timer.stop()  # a pending re-render is this one
        self._clear_history_rows()
        stored = self.app.history.entries()
        # Deleting nothing is not a destructive action worth offering.
        self.history_clear_button.setEnabled(bool(stored))
        self.history_clear_button.setToolTip(
            "Permanently delete every stored transcript."
            if stored
            else "Nothing to delete — no transcripts are stored."
        )
        query = self.history_filter_edit.text().strip()
        if not stored:
            self.history_count_label.setText("")
            # "No transcripts yet" promises the list will fill up — which is a
            # lie once history is switched off. Say which of the two empty
            # states this is, and where to change it.
            self._history_layout.insertWidget(0, self._hint(
                "No transcripts yet — the text of your next dictation shows up here."
                if self.cfg["history_enabled"]
                else "History is off — new transcripts are not stored. Turn on "
                "“Keep a history of transcribed text” above to collect them."
            ))
            return
        entries = filter_entries(stored, query)
        self.history_count_label.setText(
            f"{len(entries)} of {len(stored)} match"
            if query
            else f"{len(stored)} transcript{'s' if len(stored) != 1 else ''}"
        )
        if not entries:
            # A filtered-to-empty list must not look like an empty history —
            # name the search term and how to get back to the full list.
            self._history_layout.insertWidget(0, self._hint(
                f"No transcript contains “{query}”. Clear the search field above "
                "to see all of them again."
            ))
            return
        shown = entries[:_HISTORY_RENDER_LIMIT]
        insert_at = 0
        if len(entries) > len(shown):
            note = self._hint(
                f"Showing the {len(shown)} most recent of {len(entries)} matching transcripts."
                if query
                else f"Showing the {len(shown)} most recent of {len(entries)} transcripts."
            )
            self._history_layout.insertWidget(insert_at, note)
            insert_at += 1
        for entry in shown:
            self._history_layout.insertWidget(insert_at, self._history_row(entry))
            insert_at += 1

    def _history_row(self, entry: dict) -> QWidget:
        # str(): the store normalizes this, but the value is untrusted input and
        # a non-string would raise inside QLabel — mirrors HomePage._recent_row.
        text = str(entry.get("text", ""))
        row = QGroupBox()
        rv = QVBoxLayout(row)
        rv.setContentsMargins(10, 6, 10, 8)
        rv.setSpacing(2)

        header = QHBoxLayout()
        stamp = ""
        when = entry.get("time")
        if when:
            # TypeError/OverflowError included: a corrupt history timestamp
            # must only lose the stamp, never the page (see home_page.py).
            try:
                stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(when)))
            except (TypeError, ValueError, OverflowError, OSError):
                stamp = ""
        stamp_label = QLabel(stamp)
        stamp_label.setProperty("role", "hint")
        header.addWidget(stamp_label)
        header.addStretch(1)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda _checked=False, t=text, b=copy_btn: self._copy_history(t, b))
        header.addWidget(copy_btn)
        rv.addLayout(header)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rv.addWidget(body)
        return row

    def _copy_history(self, text: str, button: QPushButton) -> None:
        # Reports a failed clipboard write on the button — see copy_with_feedback.
        copy_with_feedback(text, button)

    def _clear_history(self) -> None:
        if not self.app.history.entries():
            return
        confirm = QMessageBox.question(
            self, APP_NAME, "Delete the entire transcript history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.app.history.clear()
            self._refresh_history()

    # --------------------------------------------------- selection readers

    def _selected_language(self) -> str:
        return language_from_label(self.language_combo.currentText())

    def _selected_backend(self) -> str:
        return backend_from_label(self.backend_combo.currentText())

    def _selected_clipboard_mode(self) -> str:
        return clipboard_copy_from_label(self.clipboard_combo.currentText())

    def _on_clipboard_mode_changed(self) -> None:
        """“Always” owns the clipboard, so the restore option cannot also apply.

        Putting the previous content back would wipe the transcript that mode
        just promised to keep. The injector ignores the restore in that case —
        a checkbox that stays tickable while nothing acts on it would be the
        silent no-op this project keeps running into, so grey it out and say
        why. The stored value is untouched and returns with another mode.
        """
        always = self._selected_clipboard_mode() == "always"
        self.chk_restore.setEnabled(not always)
        self._clipboard_hint.setText(
            "“Always” keeps the transcript on the clipboard — the previous content "
            "is not restored while that mode is selected."
            if always
            else ""
        )
        # Hidden rather than empty: an always-present blank line would leave a
        # gap in the group for the mode nearly everyone runs.
        self._clipboard_hint.setVisible(always)

    def _on_backend_changed(self) -> None:
        """Show only the Engine rows that apply to the selected backend."""
        backend = self._selected_backend()
        fw = backend == "faster-whisper"
        openvino = backend == "openvino"
        parakeet = backend == "parakeet"
        form = self._engine_form
        # Parakeet shares the CUDA/CPU device choice with faster-whisper; the
        # remaining Whisper decode options apply to faster-whisper only.
        form.setRowVisible(self.device_combo, fw or parakeet)
        form.setRowVisible(self.compute_combo, fw)
        form.setRowVisible(self.beam_spin, fw)
        form.setRowVisible(self.chk_vad, fw)  # VAD is faster-whisper only
        form.setRowVisible(self.ov_device_combo, openvino)
        form.setRowVisible(self.ov_precision_combo, openvino)
        form.setRowVisible(self.pk_quant_combo, parakeet)
        # Parakeet is a single fixed model that always auto-detects the language
        # and takes no prompt — none of these are sent to it. Grey them out
        # instead of leaving fields that silently do nothing (the Home page
        # already reports "Auto-detect" for this backend). Values are kept.
        self.model_combo.setEnabled(not parakeet)
        self.language_combo.setEnabled(not parakeet)
        self.initial_prompt_edit.setEnabled(not parakeet)
        self._speech_hint.setText(
            "The Parakeet backend ignores both: it runs one fixed model and "
            "always detects the spoken language itself. Choose a different "
            "backend on the Whisper page to use them again — your selections "
            "are kept."
            if parakeet
            else "Downloaded automatically on first use (folder on the Whisper page). "
            "Pick a preset, or choose “Custom model id…” to use any CTranslate2 "
            "model from Hugging Face."
        )
        # Live typing (General page) needs faster-whisper's segment timestamps,
        # so the option is greyed out for the other backends — its tooltip
        # explains the requirement. The stored value is kept either way.
        self.chk_live_typing.setEnabled(fw)

    def _selected_model(self) -> str:
        label = self.model_combo.currentText()
        if label == CUSTOM_MODEL_LABEL:
            # The sentinel never survives _on_model_activated; if it is ever
            # current anyway (programmatic selection), fall back to the saved
            # model instead of storing the sentinel text as a model id.
            return self.cfg["model"]
        return model_from_label(label)

    def _on_model_activated(self, index: int) -> None:
        """Resolve the "Custom model id…" sentinel via an input dialog.

        The combo itself is read-only — free text used to become the model id
        verbatim — so arbitrary CTranslate2 ids are entered here deliberately.
        Cancel restores the previous selection; the sentinel is never left
        selected."""
        if self.model_combo.itemText(index) != CUSTOM_MODEL_LABEL:
            self._model_index = index
            return
        previous = model_from_label(self.model_combo.itemText(self._model_index))
        is_preset = any(previous == model for model, _ in MODEL_CHOICES)
        text, ok = QInputDialog.getText(
            self,
            "Custom Whisper model",
            "CTranslate2 model id on Hugging Face,\n"
            f"e.g. {GERMAN_TURBO_CT2}:",
            text="" if is_preset else previous,
        )
        model = text.strip() if ok else ""
        if not model or model == CUSTOM_MODEL_LABEL:
            self.model_combo.setCurrentIndex(self._model_index)
            return
        row = self.model_combo.findText(model_label(model))
        if row < 0:
            # Keep a single custom entry, directly above the sentinel.
            sentinel = self.model_combo.count() - 1
            if sentinel == len(MODEL_CHOICES):
                self.model_combo.insertItem(sentinel, model)
                row = sentinel
            else:
                row = sentinel - 1
                self.model_combo.setItemText(row, model)
        self.model_combo.setCurrentIndex(row)
        self._model_index = row

    def _selected_input_device(self):
        return input_device_from_label(self.input_combo.currentText())

    # -------------------------------------------------------- save / apply

    def _collect(self) -> dict:
        """Every value the dialog edits, as one plain dict.

        Single source for Save/Apply (what gets written to the config) and for
        the unsaved-changes guard (compared against the snapshot taken at
        construction / after the last apply)."""
        return {
            "hotkey": self.hotkey_edit.text().strip(),
            "hotkey_mode": "hold" if self.rb_hold.isChecked() else "toggle",
            "language": self._selected_language(),
            "model": self._selected_model(),
            "model_dir": self.model_dir_edit.text().strip() or None,
            "injection_mode": "type" if self.rb_type.isChecked() else "paste",
            "live_typing": self.chk_live_typing.isChecked(),
            "clipboard_copy": self._selected_clipboard_mode(),
            "restore_clipboard": self.chk_restore.isChecked(),
            "notifications": self.chk_notifications.isChecked(),
            "beep": self.chk_beep.isChecked(),
            "autostart": self.chk_autostart.isChecked(),
            "start_in_tray": self.chk_start_in_tray.isChecked(),
            "backend": self._selected_backend(),
            "device": self.device_combo.currentText(),
            "compute_type": self.compute_combo.currentText(),
            "beam_size": int(self.beam_spin.value()),
            "openvino_device": self.ov_device_combo.currentText(),
            "openvino_precision": self.ov_precision_combo.currentText(),
            "parakeet_quantization": self.pk_quant_combo.currentText(),
            "vad_filter": self.chk_vad.isChecked(),
            "history_enabled": self.chk_history_enabled.isChecked(),
            "history_max": int(self.history_max_spin.value()),
            "update_check_on_start": self.chk_update_on_start.isChecked(),
            "include_prereleases": self.chk_prereleases.isChecked(),
            "insecure_ssl": self.chk_insecure_ssl.isChecked(),
            "initial_prompt": self.initial_prompt_edit.toPlainText().strip(),
            "input_device": self._selected_input_device(),
            "max_seconds": int(self.max_seconds_spin.value()),
            "overlay": {
                "enabled": self.chk_o_enabled.isChecked(),
                "show_preview": self.chk_o_preview.isChecked(),
                "live_preview": self.chk_o_live.isChecked(),
                "preview_seconds": int(self.preview_seconds_spin.value()),
            },
            "assistant": {
                "enabled": self.chk_a_enabled.isChecked(),
                "base_url": self.a_url_edit.text().strip(),
                "model": self.a_model_edit.text().strip(),
                "api_key": self.a_key_edit.text().strip(),
                "temperature": float(self.a_temp_spin.value()),
                "system_prompt": (
                    self.a_prompt_edit.toPlainText().strip() or DEFAULT_ASSISTANT_PROMPT
                ),
            },
            "integrations": {
                "mute_while_recording": self.chk_mute_enabled.isChecked(),
                "targets": [row.values() for row in self._target_rows],
            },
        }

    def _validate(self, values: dict) -> bool:
        """Check the collected values; on a problem, jump to the offending page
        and field so the error message points at what is on screen."""
        hotkey = values["hotkey"]
        if not Hotkeys.validate(hotkey):
            self._show_page("General")
            QMessageBox.critical(
                self,
                APP_NAME,
                f"Invalid hotkey: {hotkey}\n\nUse the pynput format, e.g. <ctrl>+<alt>+<space> — "
                "or click “Change…” and press the keys.",
            )
            self.hotkey_edit.setFocus()
            return False

        # An enabled assistant with no usable endpoint is the one setting that
        # cannot report itself: it runs after a dictation, on a worker thread,
        # and the user meets the problem as a raw requests error attached to a
        # transcript they already spoke. Catch it here, where the fields are.
        # A disabled assistant may stay half-configured, like a disabled mute row.
        if values["assistant"]["enabled"]:
            problem = assistant_config_problem(values["assistant"])
            if problem is not None:
                field, reason = problem
                self._show_page("Assistant")
                QMessageBox.critical(
                    self,
                    APP_NAME,
                    f"Assistant post-processing is switched on, but {reason}.\n\n"
                    "Fill the field in, or turn the assistant off — otherwise "
                    "every dictation would fail on it after the fact.",
                )
                widget = self.a_url_edit if field == "base_url" else self.a_model_edit
                widget.setFocus()
                return False

        # Only enabled mute targets need a valid keybind; a disabled row may be
        # left half-configured without blocking Save.
        for target in values["integrations"]["targets"]:
            if not target["enabled"]:
                continue
            if not Hotkeys.validate(target["hotkey"]):
                self._show_page("Integrations")
                QMessageBox.critical(
                    self,
                    APP_NAME,
                    f"“{target['name']}” is enabled but its mute keybind "
                    f"“{target['hotkey']}” is not a valid combination.\n\n"
                    "Click “Change…” to set it, or turn that app off.",
                )
                return False
            if Hotkeys.equal(target["hotkey"], hotkey):
                self._show_page("Integrations")
                QMessageBox.critical(
                    self,
                    APP_NAME,
                    f"“{target['name']}” uses the same keybind as the recording "
                    f"hotkey ({hotkey}).\n\nGive the app a different combination — "
                    "otherwise muting it would also start/stop your recording.",
                )
                return False
        return True

    def _apply_values(self) -> bool:
        """Validate, write the dialog values to the config and apply them.
        Returns False (dialog stays open, nothing saved) on invalid input."""
        values = self._collect()
        if not self._validate(values):
            return False
        # Finish a running hotkey test first: apply_settings() re-registers the
        # real global listener, and with the test listener still alive a test
        # press would also start a real recording behind the window. (Save had
        # the same overlap only for microseconds before closing; Apply keeps
        # the window open, so end the test explicitly.)
        if self._hotkey_test is not None:
            self._finish_hotkey_test("")
        cfg = self.cfg.data
        for key, value in values.items():
            if key in ("overlay", "assistant", "integrations"):
                continue
            cfg[key] = value
        cfg["overlay"].update(values["overlay"])
        cfg["assistant"].update(values["assistant"])
        cfg.setdefault("integrations", {}).update(values["integrations"])
        if not self.cfg.save():
            # Disk full / read-only config dir: the values still apply to this
            # session (they are in cfg.data), but silence here would let the
            # user believe they survive a restart.
            QMessageBox.warning(
                self,
                APP_NAME,
                "The settings could not be written to disk — they apply to "
                "this session but will be lost on quit. See the log file for "
                "the reason.",
            )
        self.app.apply_settings()
        self._saved_snapshot = self._collect()
        self._refresh_autostart_status()  # apply_settings just (re)wrote the entry
        self.home.refresh()  # hotkey chips / stat cards may show old values
        if self._history_rendered:
            # The empty-list note names the applied on/off state, so it goes
            # stale the moment the history switch is applied. Re-render it now
            # when it's on screen; otherwise let the next visit rebuild it.
            if self.stack.currentIndex() == self._history_index:
                self._refresh_history()
            else:
                self._history_rendered = False
        return True

    def _save(self) -> None:
        if self._apply_values():
            self.accept()

    def _apply(self) -> None:
        if self._apply_values():
            self.footer_status.setText("Settings applied ✓")
            self._footer_status_timer.start()

    def force_close(self) -> None:
        """Close without the unsaved-changes prompt. Used when the app itself
        closes the window (shutdown via tray Exit, updater restart) — a modal
        question there would stall the quit, and in the update flow the exe
        swap waiting for the process to exit, until someone answers it."""
        self._force_close = True
        self.close()

    def reject(self) -> None:
        """Cancel / Esc / the window's close button: confirm before silently
        discarding edits — Save validates and closes, Discard drops them."""
        if not self._force_close and self._collect() != self._saved_snapshot:
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("You have unsaved changes.")
            box.setInformativeText("Save them before closing, or discard them?")
            box.setStandardButtons(
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Save)
            choice = box.exec()
            if choice == QMessageBox.StandardButton.Save:
                self._save()  # on invalid input this warns and keeps the dialog open
                return
            if choice != QMessageBox.StandardButton.Discard:
                return  # Cancel / Esc on the prompt: keep editing
        super().reject()
