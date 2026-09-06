"""First-run onboarding wizard: the essential choices on the very first launch.

Shown once when no config file exists yet (Config.first_run). It collects only
the settings a new user must get right — recording hotkey, spoken language,
speech model, transcription backend + device, microphone, and startup
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
    OPENVINO_DEVICES,
    backend_from_label,
    backend_label,
    input_device_choices,
    input_device_from_label,
    language_from_label,
    language_label,
    model_from_label,
    model_label,
    models_for_backend,
    openvino_alternative,
    openvino_supports_model,
)
from .hotkeys import Hotkeys
from .qtutil import elastic_combo, flash_button, guard_wheel
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
    stays constructible with a bare Config in the headless self-test.

    ``app`` is optional and used only to pause the live global hotkey while the
    key picker is open (see _capture_hotkey); without it the wizard works
    exactly as before, just unable to pause anything."""

    def __init__(self, cfg, parent=None, app=None):
        super().__init__(parent)
        self.cfg = cfg
        self._app = app
        # The preset the OpenVINO model filter swapped out, so going back to
        # another backend restores it (see _on_backend_changed).
        self._model_swapped_from: str | None = None
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
        # The field sits in a plain row with no label of its own, so name it
        # explicitly — a screen reader would announce a bare "edit" otherwise.
        self.hotkey_edit.setAccessibleName("Recording hotkey")
        rh.addWidget(self.hotkey_edit, 1)
        pick = QPushButton("Change…")
        pick.setToolTip("Records the next key combination you press — no typing needed.")
        pick.clicked.connect(self._pick_hotkey)
        rh.addWidget(pick)
        layout.addWidget(row)
        self._hotkey_error = _hint("")
        # Styled as an error, not as one more grey hint — it sits directly
        # above the explanatory hint below and is the reason Next refused.
        self._hotkey_error.setProperty("role", "error")
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
            "What you speak and which speech model transcribes it — locally, no cloud.",
        )
        form = QFormLayout(page)
        self.language_combo = QComboBox()
        self.language_combo.addItems([language_label(code) for code, _ in LANGUAGES])
        self.language_combo.setCurrentText(language_label(self.cfg["language"]))
        self.language_combo.setToolTip(
            "The language you dictate in. Fixing it improves accuracy and speed over auto-detect."
        )
        form.addRow("Spoken language:", self.language_combo)

        # Read-only presets only — free text typed here was once saved verbatim
        # as the model id. Custom CTranslate2 ids live behind the explicit
        # "Custom model id…" dialog in Settings, not in the first-run wizard.
        self.model_combo = QComboBox()
        # Listed for the backend chosen on the *next* page — which starts out
        # as the saved/default one and re-lists this combo whenever it changes
        # (see _on_backend_changed): not every preset has an OpenVINO version.
        self._fill_model_combo(self.cfg["backend"], self.cfg["model"])
        self.model_combo.setToolTip(
            "Bigger = more accurate but slower and larger. small is a good start; "
            "custom Hugging Face model ids can be set later in Settings."
        )
        # Long preset labels must not force the fixed-size wizard wider (see qtutil).
        elastic_combo(self.model_combo)
        form.addRow("Model:", self.model_combo)
        form.addRow(_hint(
            "The model is downloaded automatically on first use — nothing to install now."
        ))
        return page

    def _build_engine_page(self) -> QWizardPage:
        page = _Page(
            "Transcription engine",
            "Which backend and hardware run the speech model.",
        )
        form = QFormLayout(page)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems([label for _, label in BACKENDS])
        self.backend_combo.setCurrentText(backend_label(self.cfg["backend"]))
        self.backend_combo.setToolTip(
            "faster-whisper accelerates on NVIDIA GPUs (CUDA); OpenVINO on Intel "
            "GPUs and NPUs; Parakeet is a separate engine (NVIDIA Parakeet TDT) that "
            "transcribes many times faster — the model chosen on the previous page "
            "doesn't apply to it. Unsure? Keep faster-whisper — it also runs on any CPU."
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
            "the selected hardware is unavailable. Precision and other engine "
            "details live in Settings → Engine."
        ))
        # Filled by _on_backend_changed for Parakeet: it ignores the model and
        # language just picked on the previous page, and a wizard that accepts
        # those choices and then drops them silently is simply misleading. The
        # settings window greys the same fields out for this reason.
        self._engine_note = _hint("")
        form.addRow(self._engine_note)
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
        # The form row's label buddies the containing widget, not this combo.
        self.input_combo.setAccessibleName("Input device")
        # Device names come from the OS and can be arbitrarily long.
        elastic_combo(self.input_combo)
        rh.addWidget(self.input_combo, 1)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-scan the audio devices, e.g. after plugging in a headset.")
        # Not _load_devices directly: the usual outcome of a rescan is the very
        # same list, so the button looked dead in exactly the normal case —
        # the same trap the settings window's Refresh already avoids.
        self._devices_refresh_button = refresh
        refresh.clicked.connect(self._rescan_devices)
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
            f"{APP_NAME} lives in the system tray — click the tray icon to open "
            "this window again, right-click it for Settings, Help and Quit. "
            "Every choice made here (and much more) can be changed there at "
            "any time."
        ))
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ handlers

    def _capture_hotkey(self) -> str | None:
        """Open the key picker with the app's live global hotkey paused.

        App registers the hotkey before it shows this wizard, so pressing the
        currently active combination while picking would start a real recording
        behind the modal wizard — on the user's very first launch. Nothing is
        applied until Finish, so the old hotkey is simply restored afterwards
        (same pattern as settings_ui._capture_hotkey)."""
        app = self._app
        if app is None:  # bare-Config construction (headless self-test)
            return HotkeyCaptureDialog.ask(self)
        try:
            app.hotkeys.stop()
        except Exception:
            log.debug("could not pause the global hotkey for the key picker", exc_info=True)
        try:
            return HotkeyCaptureDialog.ask(self)
        finally:
            app._register_hotkey()

    def _pick_hotkey(self) -> None:
        combo = self._capture_hotkey()
        if combo:
            self.hotkey_edit.setText(combo)
            self._hotkey_error.setText("")
            # Cleared together with the label: a stale reason on the field
            # would still be read out after the picker replaced the value.
            self.hotkey_edit.setAccessibleDescription("")

    def _validate_hotkey(self) -> bool:
        """Refuse Next on an unusable combination, and point at the field.

        Refusing while leaving everything where it is makes the error label the
        only sign that anything happened — a label a screen reader never reads,
        because focus is still on the Next button the user just pressed. So the
        reason is carried on the offending field as well and the caret is put
        there, exactly as the settings window's _validate does for the very
        same value.
        """
        hotkey = self.hotkey_edit.text().strip()
        if Hotkeys.validate(hotkey):
            self._hotkey_error.setText("")
            self.hotkey_edit.setAccessibleDescription("")
            return True
        reason = f"“{hotkey}” is not a valid combination — click “Change…” and press the keys."
        self._hotkey_error.setText(reason)
        self.hotkey_edit.setAccessibleDescription(reason)
        self.hotkey_edit.setFocus()
        return False

    def _fill_model_combo(self, backend: str, model: str) -> None:
        """(Re)list the model dropdown for `backend` and select `model`.

        Only presets the backend can actually run are offered — the OpenVINO
        backend has no conversion for a few of them, and a combination that the
        wizard accepts and the first transcription then refuses is worse than
        no choice at all (#112)."""
        presets = [preset for preset, _ in models_for_backend(backend)]
        labels = [model_label(preset) for preset in presets]
        if model not in presets:
            labels.append(model)  # unlisted id from the config, verbatim
        blocked = self.model_combo.blockSignals(True)
        try:
            self.model_combo.clear()
            self.model_combo.addItems(labels)
        finally:
            self.model_combo.blockSignals(blocked)
        row = self.model_combo.findText(model_label(model) if model in presets else model)
        self.model_combo.setCurrentIndex(max(0, row))

    def _on_backend_changed(self) -> None:
        """Show only the device row that applies to the selected backend,
        re-list the model page's dropdown for it, and say when the previous
        page's choices no longer apply."""
        backend = backend_from_label(self.backend_combo.currentText())
        openvino = backend == "openvino"
        self._engine_form.setRowVisible(self.device_combo, not openvino)
        self._engine_form.setRowVisible(self.ov_device_combo, openvino)

        model = model_from_label(self.model_combo.currentText())
        swapped_out = None
        if openvino and not openvino_supports_model(model):
            swapped_out = model
            self._model_swapped_from = model
            model = openvino_alternative(model)
        elif not openvino and self._model_swapped_from is not None:
            # Restore only while the replacement is still selected — a model
            # the user went back and picked themselves wins.
            if model == openvino_alternative(self._model_swapped_from):
                model = self._model_swapped_from
            self._model_swapped_from = None
        self._fill_model_combo(backend, model)

        if backend == "parakeet":
            note = (
                "Note: Parakeet ignores the model and the spoken language "
                "from the previous page — it runs one fixed model and detects the "
                "language itself (25 supported). Go Back and choose another backend "
                "to use them; your selections are kept either way."
            )
        elif swapped_out is not None:
            note = (
                f"Note: “{swapped_out}” has no OpenVINO version — the model on the "
                f"previous page was switched to “{openvino_alternative(swapped_out)}”. "
                "Choosing another backend brings your original pick back."
            )
        elif openvino:
            note = (
                "Note: the previous page now lists only models with a pre-converted "
                "OpenVINO version; the rest need the faster-whisper backend."
            )
        else:
            note = ""
        self._engine_note.setText(note)

    def _load_devices(self) -> None:
        values, current = input_device_choices(self.cfg["input_device"])
        self.input_combo.clear()
        self.input_combo.addItems(values)
        self.input_combo.setCurrentText(current)

    def _rescan_devices(self) -> None:
        """Re-scan on the Refresh button and confirm on it that it happened.

        Plugging a headset in is the reason to press this on the very first
        launch, and the list usually comes back identical — with no
        confirmation the button reads as doing nothing at all. Counted by the
        "<index>: <name>" shape rather than by row count: the list also carries
        "System default" and, when enumeration failed, an inline error entry,
        and neither is a microphone that was found.
        """
        self._load_devices()
        found = sum(
            1
            for row in range(self.input_combo.count())
            if input_device_from_label(self.input_combo.itemText(row)) is not None
        )
        flash_button(
            self._devices_refresh_button,
            f"{found} found ✓" if found else "None found",
            "Refresh",
        )

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
