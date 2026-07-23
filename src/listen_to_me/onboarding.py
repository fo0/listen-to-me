"""First-run onboarding wizard: the essential choices on the very first launch.

Shown once when no config file exists yet (Config.first_run). It collects only
the settings a new user must get right — recording hotkey, spoken language,
Whisper model, transcription backend + device, microphone, and startup
behaviour — and writes them into the config on Finish. Everything else keeps
its default and stays editable in the settings window later.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from . import APP_NAME
from .choices import (
    BACKENDS,
    DEVICES,
    LANGUAGES,
    MODEL_CHOICES,
    OPENVINO_DEVICES,
    backend_from_label,
    backend_label,
    input_device_choices,
    input_device_from_label,
    language_from_label,
    language_label,
    model_from_label,
    model_label,
)
from .hotkeys import Hotkeys
from .qtutil import elastic_combo, guard_wheel
from .widgets import HotkeyCaptureDialog

log = logging.getLogger(__name__)


class _Page(QWizardPage):
    """A wizard page with an optional validate hook run on Next/Finish."""

    def __init__(self, title: str, subtitle: str, validate=None):
        super().__init__()
        self.setTitle(title)
        self.setSubTitle(subtitle)
        self._validate = validate

    def validatePage(self) -> bool:
        return self._validate() if self._validate is not None else True


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


class OnboardingWizard(QWizard):
    """Modal first-run setup. On accept the chosen values are written into
    ``cfg.data`` — saving and applying is the caller's job (App), so the wizard
    stays constructible with a bare Config in the headless self-test."""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.resize(600, 460)

        self.addPage(self._build_hotkey_page())
        self.addPage(self._build_speech_page())
        self.addPage(self._build_engine_page())
        self.addPage(self._build_audio_page())
        self.addPage(self._build_startup_page())

        # A stray wheel tick must not silently change a choice (same guard as
        # the settings window): combos react to the wheel only once focused.
        guard_wheel(*self.findChildren(QComboBox))

    # -------------------------------------------------------------- pages

    def _build_hotkey_page(self) -> QWizardPage:
        page = _Page(
            "Recording hotkey",
            "This key combination starts and stops a recording — from any application.",
            validate=self._validate_hotkey,
        )
        layout = QVBoxLayout(page)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        self.hotkey_edit = QLineEdit(self.cfg["hotkey"])
        self.hotkey_edit.setToolTip(
            "pynput format, e.g. <ctrl>+<alt>+<space>. Easiest: click “Change…” and press the keys."
        )
        rh.addWidget(self.hotkey_edit, 1)
        pick = QPushButton("Change…")
        pick.setToolTip("Records the next key combination you press — no typing needed.")
        pick.clicked.connect(self._pick_hotkey)
        rh.addWidget(pick)
        layout.addWidget(row)
        self._hotkey_error = _hint("")
        layout.addWidget(self._hotkey_error)
        layout.addWidget(_hint(
            "Pick a combination that no other application uses. The default "
            "toggle mode records between two presses; hold (push-to-talk) can "
            "be enabled later in Settings → General."
        ))
        layout.addStretch(1)
        return page

    def _build_speech_page(self) -> QWizardPage:
        page = _Page(
            "Speech recognition",
            "What you speak and which Whisper model transcribes it — locally, no cloud.",
        )
        form = QFormLayout(page)
        self.language_combo = QComboBox()
        self.language_combo.addItems([language_label(code) for code, _ in LANGUAGES])
        self.language_combo.setCurrentText(language_label(self.cfg["language"]))
        self.language_combo.setToolTip(
            "The language you dictate in. Fixing it improves accuracy and speed over auto-detect."
        )
        form.addRow("Spoken language:", self.language_combo)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([model_label(m) for m, _ in MODEL_CHOICES])
        self.model_combo.setCurrentText(model_label(self.cfg["model"]))
        self.model_combo.setToolTip(
            "Bigger = more accurate but slower and larger. small is a good start; "
            "you can also type any CTranslate2 model id from Hugging Face."
        )
        # Long preset labels must not force the fixed-size wizard wider (see qtutil).
        elastic_combo(self.model_combo)
        form.addRow("Whisper model:", self.model_combo)
        form.addRow(_hint(
            "The model is downloaded automatically on first use — nothing to install now."
        ))
        return page

    def _build_engine_page(self) -> QWizardPage:
        page = _Page(
            "Transcription engine",
            "Which backend and hardware run the Whisper model.",
        )
        form = QFormLayout(page)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems([label for _, label in BACKENDS])
        self.backend_combo.setCurrentText(backend_label(self.cfg["backend"]))
        self.backend_combo.setToolTip(
            "faster-whisper accelerates on NVIDIA GPUs (CUDA); OpenVINO on Intel "
            "GPUs and NPUs; Parakeet is a non-Whisper engine that transcribes many "
            "times faster (the Whisper model choice doesn't apply to it). Unsure? "
            "Keep faster-whisper — it also runs on any CPU."
        )
        form.addRow("Backend:", self.backend_combo)

        self.device_combo = QComboBox()
        self.device_combo.addItems(DEVICES)
        self.device_combo.setCurrentText(self.cfg["device"])
        self.device_combo.setToolTip(
            "auto picks an NVIDIA GPU (CUDA) when available, otherwise the CPU."
        )
        form.addRow("Device:", self.device_combo)

        self.ov_device_combo = QComboBox()
        self.ov_device_combo.addItems(OPENVINO_DEVICES)
        self.ov_device_combo.setCurrentText(self.cfg["openvino_device"])
        self.ov_device_combo.setToolTip(
            "Which Intel device runs the model. auto prefers the GPU, then the NPU, then the CPU."
        )
        form.addRow("Intel device:", self.ov_device_combo)

        form.addRow(_hint(
            "auto is the safe choice — the app falls back to the CPU whenever "
            "the selected hardware is unavailable. Compute type and other "
            "engine details live in Settings → Whisper."
        ))
        self._engine_form = form
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self._on_backend_changed()
        return page

    def _build_audio_page(self) -> QWizardPage:
        page = _Page(
            "Microphone",
            "The input device recordings are captured from.",
        )
        form = QFormLayout(page)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        self.input_combo = QComboBox()
        self.input_combo.setToolTip(
            "“System default” follows the OS sound settings — usually the right choice."
        )
        # Device names come from the OS and can be arbitrarily long.
        elastic_combo(self.input_combo)
        rh.addWidget(self.input_combo, 1)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-scan the audio devices, e.g. after plugging in a headset.")
        refresh.clicked.connect(self._load_devices)
        rh.addWidget(refresh)
        form.addRow("Input device:", row)
        form.addRow(_hint(
            "You can verify the microphone later with the 3-second level test "
            "in Settings → Audio."
        ))
        self._load_devices()
        return page

    def _build_startup_page(self) -> QWizardPage:
        page = _Page(
            "Startup",
            "How the app starts. That's it — Finish saves your choices.",
        )
        layout = QVBoxLayout(page)
        self.chk_autostart = QCheckBox("Start with the system (run in background)")
        self.chk_autostart.setChecked(bool(self.cfg["autostart"]))
        self.chk_autostart.setToolTip(
            "Launch the app automatically when you log in, so the hotkey is always available."
        )
        layout.addWidget(self.chk_autostart)
        self.chk_start_in_tray = QCheckBox("Start minimized to the system tray")
        self.chk_start_in_tray.setChecked(bool(self.cfg["start_in_tray"]))
        self.chk_start_in_tray.setToolTip(
            "When enabled the app starts silently into the tray with no window. "
            "When disabled the settings window opens on launch."
        )
        layout.addWidget(self.chk_start_in_tray)
        layout.addWidget(_hint(
            f"{APP_NAME} lives in the system tray — right-click the tray icon "
            "for Settings, Help and Quit. Every choice made here (and much "
            "more) can be changed there at any time."
        ))
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ handlers

    def _pick_hotkey(self) -> None:
        combo = HotkeyCaptureDialog.ask(self)
        if combo:
            self.hotkey_edit.setText(combo)
            self._hotkey_error.setText("")

    def _validate_hotkey(self) -> bool:
        hotkey = self.hotkey_edit.text().strip()
        if Hotkeys.validate(hotkey):
            self._hotkey_error.setText("")
            return True
        self._hotkey_error.setText(
            f"“{hotkey}” is not a valid combination — click “Change…” and press the keys."
        )
        return False

    def _on_backend_changed(self) -> None:
        """Show only the device row that applies to the selected backend."""
        openvino = backend_from_label(self.backend_combo.currentText()) == "openvino"
        self._engine_form.setRowVisible(self.device_combo, not openvino)
        self._engine_form.setRowVisible(self.ov_device_combo, openvino)

    def _load_devices(self) -> None:
        values, current = input_device_choices(self.cfg["input_device"])
        self.input_combo.clear()
        self.input_combo.addItems(values)
        self.input_combo.setCurrentText(current)

    # -------------------------------------------------------------- accept

    def _apply(self) -> None:
        """Write the chosen values into the config dict. Separate from accept()
        so the headless self-test can exercise the mapping without triggering
        page validation (Hotkeys.validate imports pynput — absent on the light
        CI runner)."""
        cfg = self.cfg.data
        cfg["hotkey"] = self.hotkey_edit.text().strip()
        cfg["language"] = language_from_label(self.language_combo.currentText())
        cfg["model"] = model_from_label(self.model_combo.currentText())
        cfg["backend"] = backend_from_label(self.backend_combo.currentText())
        cfg["device"] = self.device_combo.currentText()
        cfg["openvino_device"] = self.ov_device_combo.currentText()
        cfg["input_device"] = input_device_from_label(self.input_combo.currentText())
        cfg["autostart"] = self.chk_autostart.isChecked()
        cfg["start_in_tray"] = self.chk_start_in_tray.isChecked()
        log.info("onboarding completed (backend: %s, model: %s)", cfg["backend"], cfg["model"])

    def accept(self) -> None:
        self._apply()
        super().accept()
