"""First-run onboarding wizard: the essential choices on the very first launch.

Shown once when no config file exists yet (Config.first_run). It collects only
the settings a new user must get right and writes them into the config on
Finish; everything else keeps its default and stays editable in the settings
window later. The pages, in order:

1. Recording hotkey.
2. Spoken language.
3. Transcription engine — "Recommended for this PC" (preselected: the setup
   `autoconfig` picks for this machine's hardware probe and the language from
   page 2) or "Choose manually" (backend, device, Intel device, Whisper model,
   Parakeet model). Its own module: `onboarding_engine`.
4. Microphone — the input device, with the same three-second level test as
   Settings → Audio (`mic_test_widget`).
5. Startup behaviour.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from . import APP_NAME
from .choices import (
    LANGUAGES,
    input_device_choices,
    input_device_from_label,
    language_from_label,
    language_label,
)
from .hotkeys import Hotkeys
from .mic_test_widget import APP_BUSY_TEXT, MicTestWidget, app_busy
from .onboarding_engine import EnginePage, hint_label
from .qtutil import busy_cursor, elastic_combo, flash_button, guard_wheel
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


class OnboardingWizard(QWizard):
    """Modal first-run setup. On accept the chosen values are written into
    ``cfg.data`` — saving and applying is the caller's job (App), so the wizard
    stays constructible with a bare Config in the headless self-test.

    ``app`` is optional and used only to pause the live global hotkey while the
    key picker is open or the microphone test records (see
    _pause_app_hotkeys), and to refuse that test while a take runs; without
    it the wizard works exactly as before, just unable to pause anything.

    ``probe`` stands in for `diagnostics.hardware_status` on the engine page
    (onboarding_engine) — the self-test passes one, so it never probes real
    hardware on a thread it cannot join."""

    def __init__(self, cfg, parent=None, app=None, probe=None):
        super().__init__(parent)
        self.cfg = cfg
        self._app = app
        self._hotkeys_paused_for_mic = False
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.resize(620, 520)

        self.addPage(self._build_hotkey_page())
        self.addPage(self._build_speech_page())
        # Built after the language combo it reads; its probe starts here, so
        # it has usually answered by the time the user arrives on the page.
        self.engine_page = EnginePage(cfg, self._selected_language, probe=probe)
        self.addPage(self.engine_page)
        self._audio_page = self._build_audio_page()
        self.addPage(self._audio_page)
        self.addPage(self._build_startup_page())
        # Leaving the Microphone page (or closing the wizard, see done) stops
        # a running level test — it holds the microphone.
        self.currentIdChanged.connect(self._on_page_changed)

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
        self._hotkey_error = hint_label("")
        # Styled as an error, not as one more grey hint — it sits directly
        # above the explanatory hint below and is the reason Next refused.
        self._hotkey_error.setProperty("role", "error")
        layout.addWidget(self._hotkey_error)
        layout.addWidget(hint_label(
            "Pick a combination that no other application uses. The default "
            "toggle mode records between two presses; hold (push-to-talk) can "
            "be enabled later in Settings → General."
        ))
        layout.addStretch(1)
        return page

    def _build_speech_page(self) -> QWizardPage:
        page = _Page(
            "Spoken language",
            "The language you dictate in — speech is recognized locally, no cloud.",
        )
        form = QFormLayout(page)
        self.language_combo = QComboBox()
        self.language_combo.addItems([language_label(code) for code, _ in LANGUAGES])
        self.language_combo.setCurrentText(language_label(self.cfg["language"]))
        self.language_combo.setToolTip(
            "The language you dictate in. Fixing it improves accuracy and speed over auto-detect."
        )
        form.addRow("Spoken language:", self.language_combo)
        form.addRow(hint_label(
            "The next page picks the speech engine and model for this language."
        ))
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
        # In the field column, as the instruction for the button below it.
        form.addRow("", hint_label("Speak for three seconds — the bar should move."))
        # The same test as Settings → Audio, on the device selected above.
        self.mic_test = MicTestWidget(
            lambda: input_device_from_label(self.input_combo.currentText()),
            can_start=self._mic_test_refusal,
        )
        self.mic_test.started.connect(self._on_mic_test_started)
        self.mic_test.finished.connect(self._on_mic_test_finished)
        form.addRow("", self.mic_test)
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
        layout.addWidget(hint_label(
            f"{APP_NAME} lives in the system tray — click the tray icon to open "
            "this window again, right-click it for Settings, Help and Quit. "
            "Every choice made here (and much more) can be changed there at "
            "any time."
        ))
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ handlers

    def _selected_language(self) -> str:
        return language_from_label(self.language_combo.currentText())

    def _pause_app_hotkeys(self) -> bool:
        """Stop the app's live global hotkeys; False without an app.

        App registers the hotkey before it shows this wizard, so pressing the
        currently active combination while the key picker is open would start
        a real recording behind the modal wizard — on the user's very first
        launch — and pressing it during the microphone test would open a
        second input stream on the device under test. Nothing is applied until
        Finish, so the way back is simply `App._register_hotkey`, which
        registers both listeners again (same pattern as settings_ui).

        Both listeners (#191): a first launch inherits a config with no
        system-audio hotkey, but this wizard is also the path back after a
        deleted config file, and that combination would then be just as live
        as the microphone's. The lines mirror `SettingsWindow._stop_app_hotkeys`
        on purpose — an import from the settings window would not carry its
        weight for them.
        """
        app = self._app
        if app is None:  # bare-Config construction (headless self-test)
            return False
        try:
            app.hotkeys.stop()
            listener = getattr(app, "system_hotkeys", None)
            if listener is not None:
                listener.stop()
        except Exception:
            log.debug("could not pause the global hotkeys", exc_info=True)
        return True

    def _capture_hotkey(self) -> str | None:
        """Open the key picker with the app's live global hotkeys paused (see
        _pause_app_hotkeys)."""
        if not self._pause_app_hotkeys():
            return HotkeyCaptureDialog.ask(self)
        try:
            return HotkeyCaptureDialog.ask(self)
        finally:
            self._app._register_hotkey()

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

    def _mic_test_refusal(self) -> str | None:
        """The microphone test's can_start: not while a take runs (the
        hotkey still records behind the wizard)."""
        return APP_BUSY_TEXT if app_busy(self._app) else None

    def _on_mic_test_started(self) -> None:
        self._hotkeys_paused_for_mic = self._pause_app_hotkeys()

    def _on_mic_test_finished(self, _outcome: str) -> None:
        if self._hotkeys_paused_for_mic:
            self._hotkeys_paused_for_mic = False
            try:
                self._app._register_hotkey()
            except Exception:
                log.debug("could not restore the global hotkeys", exc_info=True)

    def _on_page_changed(self, _page_id: int) -> None:
        if self.currentPage() is not self._audio_page:
            self.mic_test.cancel()

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
        # PortAudio enumerates on the Qt main thread and can stall for hundreds
        # of ms — the same wait cursor as the settings window's Refresh.
        with busy_cursor():
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
        # The recommendation's keys or the manual fields; the language after
        # them, because it is the speech page's alone, whatever they hold.
        cfg.update(self.engine_page.values())
        cfg["language"] = self._selected_language()
        cfg["input_device"] = input_device_from_label(self.input_combo.currentText())
        cfg["autostart"] = self.chk_autostart.isChecked()
        cfg["start_in_tray"] = self.chk_start_in_tray.isChecked()
        log.info(
            "onboarding completed (%s engine: backend %s, model %s, parakeet model %s)",
            "recommended" if self.engine_page.is_recommended() else "manual",
            cfg["backend"],
            cfg["model"],
            cfg["parakeet_model"],
        )

    def accept(self) -> None:
        self._apply()
        super().accept()

    def done(self, result: int) -> None:
        # Every way the wizard closes — Finish, Cancel, Esc, the close button:
        # a level test still recording must let go of the microphone and
        # hand the hotkey back.
        self.mic_test.cancel()
        super().done(result)
