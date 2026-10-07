"""The first-run wizard's engine step: "Recommended for this PC" or
"Choose manually".

Someone setting the app up for the first time should not have to know what
CUDA, OpenVINO or a quantization is. So the page leads with one preselected
choice — the setup `autoconfig.recommend` picks for this machine and the
spoken language chosen on the previous page, with its summary, reason and
first-use download in `autoconfig_text`'s words — and keeps the individual
fields (backend, device, Intel device, Whisper model, Parakeet model) behind
"Choose manually".

The machine is `diagnostics.hardware_status`, which imports CTranslate2,
OpenVINO and ONNX Runtime and therefore runs on a worker thread, started when
the page is built (i.e. with the wizard) so it is usually done long before
the user gets here. Its result is kept; entering the page recomputes the
recommendation from it for the current language, without probing again.
The probe is injectable (`probe`), so the headless self-test never touches
real hardware and can join the thread it started.

Never waits on the probe: a probe that failed switches the page to the manual
fields with a visible note, and Next pressed while it still runs does the
same — the fields then hold the saved config, and keep it: the note says Next
keeps them, so a recommendation that lands later no longer refills them. (A
"Choose manually" picked by the user is prefilled with the recommendation as
long as no field was edited by hand.)
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
    QWizardPage,
)

from .autoconfig import Recommendation, hardware_from_status, recommend
from .autoconfig_text import download_line, model_downloaded
from .choices import (
    BACKENDS,
    DEVICES,
    OPENVINO_DEVICES,
    PARAKEET_MODELS,
    backend_from_label,
    backend_label,
    choice_label,
    choice_labels,
    choice_value,
    model_from_label,
    model_label,
    models_for_backend,
    openvino_alternative,
    openvino_supports_model,
)
from .qtutil import elastic_combo, elastic_label

log = logging.getLogger(__name__)

CHECKING_TEXT = "Checking this PC…"
FAILED_TEXT = "Could not check this PC."
# Next pressed before the probe answered: the page switches to the manual
# fields and says why, instead of moving on with values the user never saw.
PENDING_NOTE = (
    "This PC is still being checked, so the engine below is chosen manually — "
    "it holds your current settings. Press Next to keep them, or wait for the "
    "check and choose “Recommended for this PC”."
)
FAILED_NOTE = (
    "The engine is chosen manually instead — the fields below hold your current "
    "settings, and “auto” is the safe choice."
)
READY_NOTE = "The check has finished — “Recommended for this PC” is ready above."

# The saved values the probe's model-cache check is taken for (the "model"
# entry), recorded with its result as autoconfig_text.model_downloaded wants.
_SNAPSHOT_KEYS = (
    "backend",
    "model",
    "device",
    "compute_type",
    "openvino_device",
    "openvino_precision",
    "parakeet_model",
    "parakeet_quantization",
    "model_dir",
)
# Left margin of what belongs to a radio button, so it reads as its detail.
_INDENT = 24


def hint_label(text: str) -> QLabel:
    """A muted, wrapping note — the wizard's hint style."""
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


class _ProbeSignals(QObject):
    """Probe worker → main thread (one probe per page, so no generation)."""

    done = Signal(object)  # diagnostics.hardware_status() dict + "snapshot"
    failed = Signal(str)


class EnginePage(QWizardPage):
    """``language()`` returns the spoken-language code chosen on the speech
    page; ``probe(snapshot) -> dict`` stands in for
    `diagnostics.hardware_status` (the default)."""

    def __init__(self, cfg, language, probe=None):
        super().__init__()
        self.setTitle("Transcription engine")
        self.setSubTitle("Which engine runs the speech model — locally, on this PC.")
        self.cfg = cfg
        self._language = language
        self._probe = probe
        self._status: dict | None = None  # the probe's result, once it is in
        self._hardware = None  # autoconfig.Hardware read from it
        self._probe_error: str | None = None
        self._probe_thread: threading.Thread | None = None
        self._pending_note_shown = False
        # Set by the first pick by hand in the manual fields (or by Next
        # pressed before the probe answered, see validatePage): from then on
        # a recommendation no longer refills them (see _refresh).
        self._manual_edited = False
        # The preset the OpenVINO model filter swapped out, so going back to
        # another backend restores it (see _on_backend_changed).
        self._model_swapped_from: str | None = None

        layout = QVBoxLayout(self)
        self.recommended_radio = QRadioButton("Recommended for this PC")
        self.recommended_radio.setToolTip(
            "The most accurate engine setup that still runs well on this computer, "
            "for the language chosen on the previous page."
        )
        layout.addWidget(self.recommended_radio)
        self.rec_summary = QLabel(CHECKING_TEXT)
        font = self.rec_summary.font()
        font.setBold(True)
        self.rec_summary.setFont(font)
        self.rec_summary.setWordWrap(True)
        self.rec_summary.setContentsMargins(_INDENT, 0, 0, 0)
        layout.addWidget(self.rec_summary)
        # Elastic: a failed probe shows its error here, which can carry a path.
        self.rec_detail = hint_label("")
        elastic_label(self.rec_detail)
        self.rec_detail.setContentsMargins(_INDENT, 0, 0, 0)
        self.rec_detail.setVisible(False)
        layout.addWidget(self.rec_detail)
        # Normal text, not a grey hint: it explains why the page switched to
        # the manual fields — above them, so it is read before them.
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        layout.addWidget(self.note)

        self.manual_radio = QRadioButton("Choose manually")
        self.manual_radio.setToolTip("Pick the backend, device and model yourself.")
        layout.addWidget(self.manual_radio)
        self._manual_box = QWidget()
        self._build_manual_fields(self._manual_box)
        layout.addWidget(self._manual_box)
        layout.addStretch(1)

        self._mode = QButtonGroup(self)
        self._mode.addButton(self.recommended_radio)
        self._mode.addButton(self.manual_radio)
        self.recommended_radio.setChecked(True)
        self._manual_box.setVisible(False)
        self.manual_radio.toggled.connect(self._on_mode_changed)

        self._signals = _ProbeSignals()  # unparented: the worker keeps it alive
        self._signals.done.connect(self._on_probe_done)
        self._signals.failed.connect(self._on_probe_failed)
        self._start_probe()

    def _build_manual_fields(self, box: QWidget) -> None:
        form = QFormLayout(box)
        form.setContentsMargins(_INDENT, 0, 0, 0)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems([label for _, label in BACKENDS])
        self.backend_combo.setCurrentText(backend_label(self.cfg["backend"]))
        self.backend_combo.setToolTip(
            "faster-whisper accelerates on NVIDIA GPUs (CUDA); OpenVINO on Intel "
            "GPUs and NPUs; Parakeet is a separate engine (NVIDIA Parakeet TDT) with "
            "its own models that transcribes many times faster. Unsure? Keep "
            "faster-whisper — it also runs on any CPU."
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

        # Read-only presets only — free text typed here was once saved verbatim
        # as the model id. Custom CTranslate2 ids live behind the explicit
        # "Custom model id…" dialog in Settings, not in the first-run wizard.
        self.model_combo = QComboBox()
        # Listed for the backend above — not every preset has an OpenVINO
        # version, so a backend change re-lists it (see _on_backend_changed).
        self._fill_model_combo(self.cfg["backend"], self.cfg["model"])
        self.model_combo.setToolTip(
            "Bigger = more accurate but slower and larger. small is a good start; "
            "custom Hugging Face model ids can be set later in Settings."
        )
        form.addRow("Model:", self.model_combo)

        self.pk_model_combo = QComboBox()
        self.pk_model_combo.addItems(choice_labels(PARAKEET_MODELS))
        row = self.pk_model_combo.findText(choice_label(PARAKEET_MODELS, self.cfg["parakeet_model"]))
        self.pk_model_combo.setCurrentIndex(max(0, row))
        self.pk_model_combo.setToolTip(
            "parakeet-tdt-0.6b-v3 is NVIDIA's multilingual original (25 languages, "
            "detected automatically); parakeet-primeline-de is a German fine-tune — "
            "more accurate for German, but German only."
        )
        form.addRow("Parakeet model:", self.pk_model_combo)
        # Long preset labels must not force the fixed-size wizard wider (see qtutil).
        elastic_combo(self.model_combo, self.pk_model_combo)

        form.addRow(hint_label(
            "auto is the safe choice — the app falls back to the CPU whenever the "
            "selected hardware is unavailable. The model is downloaded automatically "
            "on first use; precision and other details live in Settings → Engine."
        ))
        # Filled by _on_backend_changed: what the backend does with the other
        # fields, and a model the OpenVINO filter swapped out.
        self._engine_note = hint_label("")
        form.addRow(self._engine_note)
        self._engine_form = form
        for combo in (
            self.backend_combo,
            self.device_combo,
            self.ov_device_combo,
            self.model_combo,
            self.pk_model_combo,
        ):
            # activated, not currentIndexChanged: only a pick by hand counts.
            combo.activated.connect(self._on_manual_edit)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self._on_backend_changed()

    # ------------------------------------------------------------- probe

    def _start_probe(self) -> None:
        probe = self._probe
        if probe is None:
            from .diagnostics import hardware_status as probe
        snapshot = {key: self.cfg[key] for key in _SNAPSHOT_KEYS}
        signals = self._signals

        def work():
            try:
                result = probe(snapshot)
                if not isinstance(result, dict):
                    raise TypeError(f"the hardware probe returned {type(result).__name__}")
                signals.done.emit(dict(result, snapshot=snapshot))
            except Exception as exc:  # shown on the page, never a crash
                log.exception("the setup wizard's hardware check failed")
                signals.failed.emit(str(exc) or type(exc).__name__)

        self._probe_thread = threading.Thread(target=work, name="wizard-hw", daemon=True)
        self._probe_thread.start()

    def _on_probe_done(self, status: dict) -> None:
        self._status = status
        self._hardware = hardware_from_status(status)
        self._refresh()
        if self._pending_note_shown:
            self._pending_note_shown = False
            self._set_note(READY_NOTE)

    def _on_probe_failed(self, message: str) -> None:
        self._probe_error = message
        self.manual_radio.setChecked(True)
        # Onto the choice that now applies, where the note is voiced — not
        # wherever Qt moves focus off the radio button disabled below.
        if self.window().focusWidget() is self.recommended_radio:
            self.manual_radio.setFocus()
        self.recommended_radio.setEnabled(False)
        self._set_note(FAILED_NOTE)
        self._refresh()

    # ------------------------------------------------------------ state

    def recommendation(self) -> Recommendation | None:
        """The setup for this PC and the language chosen now; None until the
        probe answered (or when it failed)."""
        if self._hardware is None:
            return None
        return recommend(self._hardware, self._language())

    def is_recommended(self) -> bool:
        return self.recommended_radio.isChecked()

    def initializePage(self) -> None:  # noqa: N802 (Qt naming)
        # Entered from the speech page: its language may have changed.
        self._refresh()

    def validatePage(self) -> bool:  # noqa: N802 (Qt naming)
        if self.is_recommended() and self.recommendation() is None:
            self.manual_radio.setChecked(True)
            self._pending_note_shown = True
            self._set_note(PENDING_NOTE)
            # Focus stays on Next otherwise, and the note is never read out.
            self.manual_radio.setFocus()
            # The note promises that Next keeps what the fields show: a
            # recommendation landing later — possibly after the user left
            # the page — must not refill them behind it.
            self._manual_edited = True
            return False
        return True

    def _refresh(self) -> None:
        rec = self.recommendation()
        if rec is not None:
            downloaded = model_downloaded(rec, self._status, self.cfg["model_dir"] or None)
            summary, detail = rec.summary, f"{rec.reason} {download_line(rec, downloaded)}"
            if not self._manual_edited:
                self._fill_manual(rec)
        elif self._probe_error is not None:
            summary, detail = FAILED_TEXT, self._probe_error
        else:
            summary, detail = CHECKING_TEXT, ""
        self.rec_summary.setText(summary)
        self.rec_detail.setText(detail)
        self.rec_detail.setVisible(bool(detail))
        # The labels under the radio button are not part of it for a screen
        # reader; the description is.
        self.recommended_radio.setAccessibleDescription(f"{summary} {detail}".strip())

    def _set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))
        # Every note explains the manual choice; a screen reader hears it on
        # that radio button, not from the label above it.
        self.manual_radio.setAccessibleDescription(text)

    def _on_mode_changed(self, *_args) -> None:
        manual = self.manual_radio.isChecked()
        self._manual_box.setVisible(manual)
        if not manual and self.recommendation() is not None:
            self._set_note("")  # the recommendation is in — nothing to explain

    def _on_manual_edit(self, *_args) -> None:
        self._manual_edited = True

    # ------------------------------------------------------------ values

    def values(self) -> dict:
        """The engine keys Finish writes: the recommendation's when
        "Recommended" is chosen and known, the manual fields otherwise.
        Never the language — that is the speech page's."""
        if self.is_recommended():
            rec = self.recommendation()
            if rec is not None:
                values = dict(rec.values)
                values.pop("language", None)
                return values
            log.warning("setup wizard: no recommendation yet — writing the manual engine fields")
        return self.manual_values()

    def manual_values(self) -> dict:
        return {
            "model": model_from_label(self.model_combo.currentText()),
            "backend": backend_from_label(self.backend_combo.currentText()),
            "device": self.device_combo.currentText(),
            "openvino_device": self.ov_device_combo.currentText(),
            "parakeet_model": choice_value(PARAKEET_MODELS, self.pk_model_combo.currentText()),
        }

    def _fill_manual(self, rec: Recommendation) -> None:
        """Prefill the manual fields with `rec`, as far as they hold its
        keys — the precisions are Settings → Engine detail. Selects listed
        entries only, never adds one."""
        values = rec.values
        if "backend" in values:
            _select(self.backend_combo, backend_label(values["backend"]))
        backend = backend_from_label(self.backend_combo.currentText())
        if "model" in values:
            # Chosen, not swapped: nothing for another backend to restore, and
            # the note must not report a swap the line above undid.
            self._model_swapped_from = None
            self._fill_model_combo(backend, values["model"])
            self._engine_note.setText(self._note_text(backend, None))
        for key, combo in (("device", self.device_combo), ("openvino_device", self.ov_device_combo)):
            if key in values:
                _select(combo, str(values[key]))
        if "parakeet_model" in values:
            _select(self.pk_model_combo, choice_label(PARAKEET_MODELS, values["parakeet_model"]))

    # ------------------------------------------------------- manual fields

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
        """Show only the rows that apply to the selected backend, re-list the
        model dropdown for it, and say what changed."""
        backend = backend_from_label(self.backend_combo.currentText())
        openvino = backend == "openvino"
        parakeet = backend == "parakeet"
        form = self._engine_form
        form.setRowVisible(self.device_combo, not openvino)
        form.setRowVisible(self.ov_device_combo, openvino)
        # Parakeet runs its own models; the Whisper presets do not apply.
        form.setRowVisible(self.model_combo, not parakeet)
        form.setRowVisible(self.pk_model_combo, parakeet)

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
        self._engine_note.setText(self._note_text(backend, swapped_out))

    @staticmethod
    def _note_text(backend: str, swapped_out: str | None) -> str:
        if backend == "parakeet":
            # It ignores the language picked on the previous page, and a
            # wizard that accepts a choice and then drops it silently is
            # misleading — the settings window greys the field out for this.
            return (
                "Note: Parakeet runs its own models, chosen above, and is not told "
                "the spoken language from the previous page: parakeet-tdt-0.6b-v3 "
                "detects it itself (25 European languages), parakeet-primeline-de "
                "understands German only."
            )
        if swapped_out is not None:
            return (
                f"Note: “{swapped_out}” has no OpenVINO version — the model above was "
                f"switched to “{openvino_alternative(swapped_out)}”. Choosing another "
                "backend brings your original pick back."
            )
        if backend == "openvino":
            return (
                "Note: the model list now shows only models with a pre-converted "
                "OpenVINO version; the rest need the faster-whisper backend."
            )
        return ""


def _select(combo: QComboBox, text: str) -> bool:
    row = combo.findText(text)
    if row >= 0:
        combo.setCurrentIndex(row)
    return row >= 0
