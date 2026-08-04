"""Application core: state machine, event loop, wiring of all components.

Threading model:
- main thread: Qt event loop (QApplication) + a QTimer that drains the event
  queue, so every state transition and all GUI work happens here.
- hotkey thread: pynput global hotkey listener
- worker thread: transcription + assistant + text injection
All background threads talk to the main thread via App.post(); helpers that
would touch the tray/GUI from a worker (notify) post instead of calling in.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import queue
import sys
import threading
import time

from . import APP_NAME, __version__
from . import assistant, autostart, netutil, singleinstance
from .audio import SAMPLE_RATE, Recorder
from .config import Config, config_dir
from .history import TranscriptHistory
from .hotkeys import Hotkeys
from .injector import Injector, sanitize_typed_text
from .integrations import MuteIntegrations
from .livetype import LiveTyper
from .transcriber import _PREVIEW_WINDOW_SECONDS, create_transcriber, is_cuda_library_error

log = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_RECORDING = "recording"
STATE_PROCESSING = "processing"

_instance_lock = None  # keeps the single-instance claim alive for the process lifetime

_LIVE_PREVIEW_INTERVAL = 2.5  # seconds between partial transcriptions


class App:
    def __init__(self):
        self.cfg = Config()
        # Before any component that talks to the network is created, so even
        # the first model download honours the corporate-proxy SSL opt-out.
        netutil.apply_insecure_ssl(bool(self.cfg["insecure_ssl"]))
        self.state = STATE_IDLE
        self.events: queue.Queue = queue.Queue()
        self.recorder = Recorder()
        self.transcriber = create_transcriber(self.cfg)
        self.injector = Injector(self.cfg)
        self.integrations = MuteIntegrations(self.cfg)
        self.history = TranscriptHistory(
            self.cfg.path.parent / "history.json", max_entries=self.cfg["history_max"]
        )
        self.hotkeys = Hotkeys(
            lambda: self.post("hotkey_press"), lambda: self.post("hotkey_release")
        )
        # Imported here (not at module top) so `--version`/`--selftest` don't
        # pull in Qt just to import app.py.
        from .tray import Tray

        self.tray = Tray(self)
        self.qapp = None
        self.overlay = None
        self._settings_window = None
        self._poll_timer = None
        self._recording_id = 0  # invalidates live-preview workers of old takes
        self._live_typer = None  # per-take live-typing worker (livetype.py)
        self._quitting = False  # set by _quit; guards UI opened after shutdown

    def post(self, kind: str, payload=None) -> None:
        """Thread-safe: queue an event for the main loop."""
        self.events.put((kind, payload))

    def notify(self, message: str, force: bool = False) -> None:
        """Thread-safe desktop notification: routed through the event queue so
        the tray's showMessage() is always invoked on the Qt main thread."""
        self.post("notify", (message, force))

    def run(self) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        from .overlay import Overlay
        from .theme import apply_theme

        # sys.argv[:1] keeps our own --selftest/--version flags away from Qt.
        self.qapp = QApplication.instance() or QApplication(sys.argv[:1])
        self.qapp.setApplicationName(APP_NAME)
        self.qapp.setApplicationDisplayName(APP_NAME)
        # A tray app must survive with no open windows; otherwise closing the
        # settings window would quit it.
        self.qapp.setQuitOnLastWindowClosed(False)
        apply_theme(self.qapp)

        self.tray.start()
        if _instance_lock is not None:
            # A second launch of the app pings us instead of starting again;
            # surface this instance then (thread-safe via the event queue).
            _instance_lock.start_server(lambda: self.post("activate"))
        self._register_hotkey()
        self._sync_autostart()
        try:
            self.overlay = Overlay(self)
            self.overlay.set_visible(bool(self.cfg["overlay"]["enabled"]))
        except Exception:
            log.exception("could not create the floating overlay icon")
        if self.cfg.first_run:
            # Very first launch (no config file existed): walk the user through
            # the essential choices instead of dropping them into full Settings.
            QTimer.singleShot(300, self._run_onboarding)
        elif not self.cfg["start_in_tray"]:
            # Make the freshly started app visible instead of hiding in the
            # tray right away (configurable in Settings → General).
            QTimer.singleShot(300, self._open_settings)

        if self.cfg["update_check_on_start"]:
            threading.Thread(
                target=self._startup_update_check, name="update-startup", daemon=True
            ).start()

        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(100)
        log.info("%s %s started (hotkey: %s)", APP_NAME, __version__, self.cfg["hotkey"])
        self.qapp.exec()

    # ------------------------------------------------------------- events

    def _poll(self) -> None:
        # Invoked every 100 ms by the QTimer, which re-arms itself.
        try:
            while True:
                kind, payload = self.events.get_nowait()
                try:
                    self._handle(kind, payload)
                except Exception:
                    log.exception("error handling event %r", kind)
        except queue.Empty:
            pass

    def _handle(self, kind: str, payload) -> None:
        if kind == "toggle":
            if self.state == STATE_IDLE:
                self._start_recording()
            elif self.state == STATE_RECORDING:
                self._finish_recording()
            else:
                self.notify("Still transcribing the previous recording…")
        elif kind == "hotkey_press":
            if self.cfg["hotkey_mode"] == "hold":
                # push-to-talk: start on press, stop on release
                if self.state == STATE_IDLE:
                    self._start_recording()
            else:
                self._handle("toggle", None)
        elif kind == "hotkey_release":
            if self.cfg["hotkey_mode"] == "hold" and self.state == STATE_RECORDING:
                self._finish_recording()
        elif kind == "preview_text":
            if self.overlay is not None and self.state == STATE_RECORDING:
                self.overlay.show_live(str(payload))
        elif kind == "flash_text":
            if self.overlay is not None and self.cfg["overlay"]["show_preview"]:
                self.overlay.flash(str(payload))
        elif kind == "toggle_overlay":
            ocfg = self.cfg["overlay"]
            ocfg["enabled"] = not ocfg["enabled"]
            self.cfg.save()
            if self.overlay is not None:
                self.overlay.set_visible(bool(ocfg["enabled"]))
            self.tray.set_state(self.state)  # refresh the "Show floating icon" tick
        elif kind == "cancel":
            self._cancel_recording()
        elif kind == "copy_last":
            self._copy_last_transcript()
        elif kind == "auto_stop":
            if self.state == STATE_RECORDING:
                self.notify("Maximum recording length reached.")
                self._finish_recording()
        elif kind == "done":
            self._set_state(STATE_IDLE)
        elif kind == "notify":
            message, force = payload if isinstance(payload, tuple) else (payload, False)
            self.tray.notify(str(message), force=bool(force))
        elif kind == "activate":
            self._activate_from_second_launch()
        elif kind == "settings":
            self._open_settings()
        elif kind == "updates":
            self._open_updates()
        elif kind == "help":
            self._open_help()
        elif kind == "open_config":
            self._open_config_folder()
        elif kind == "quit":
            self._quit()

    # ---------------------------------------------------------- recording

    def _start_recording(self) -> None:
        try:
            self.recorder.start(
                device=self.cfg["input_device"],
                max_seconds=self.cfg["max_seconds"],
                on_limit=lambda: self.post("auto_stop"),
            )
        except Exception as exc:
            log.exception("could not start recording")
            self.notify(f"Could not start recording: {exc}", force=True)
            return
        self._set_state(STATE_RECORDING)
        self._beep(880)
        # Bump on every take so a lingering live-preview worker from a previous
        # recording sees a changed id and exits, even if this take has no worker.
        self._recording_id += 1
        ocfg = self.cfg["overlay"]
        want_preview = bool(ocfg["enabled"] and ocfg["live_preview"])
        self._live_typer = None
        if self.cfg["live_typing"]:
            reason = self._live_typing_gate()
            if reason is None:
                # The live typer runs the decode loop, so it also feeds the
                # overlay preview — never both loops competing for the model.
                self._live_typer = LiveTyper(self, self._recording_id, post_preview=want_preview)
                self._live_typer.start()
            else:
                log.info("live typing stays off for this take: %s", reason)
        if self._live_typer is None and want_preview:
            threading.Thread(
                target=self._live_preview_loop,
                args=(self._recording_id,),
                name="live-preview",
                daemon=True,
            ).start()

    def _live_typing_gate(self) -> str | None:
        """Why live typing must stay off for this take (None = it can run).

        Hold mode is only safe with a hotkey that (a) contains no modifier —
        off Windows the modifier state can't be polled while the chord is held,
        and on Windows a held modifier would defer every chunk to the very end
        anyway — and (b) contains no key our own typing could synthesize (a
        character key or Space), which the hold listener would misread as the
        hotkey being released, stopping the recording mid-sentence.
        """
        if not hasattr(self.transcriber, "preview_segments"):
            return "backend provides no live segments"
        if self.cfg["hotkey_mode"] == "hold":
            try:
                has_modifier, has_typable = Hotkeys.combo_flags(self.cfg["hotkey"])
            except Exception:
                log.exception("could not analyze the hotkey combo")
                return "hotkey combo could not be analyzed"
            if has_modifier:
                return "hold-mode hotkey contains a modifier key"
            if has_typable:
                return "hold-mode hotkey contains a typable key"
        return None

    def _take_active(self, recording_id: int) -> bool:
        """Whether the given take is still recording and hasn't been superseded
        by a newer one. Polled by per-take workers (live typing)."""
        return self.state == STATE_RECORDING and recording_id == self._recording_id

    def _finish_recording(self) -> None:
        audio = self.recorder.stop()
        live, self._live_typer = self._live_typer, None
        self._beep(520)
        if len(audio) / SAMPLE_RATE < 0.3:
            self._set_state(STATE_IDLE)
            self.notify("Recording too short — nothing inserted.")
            return
        self._set_state(STATE_PROCESSING)
        threading.Thread(
            target=self._process, args=(audio, live), name="process", daemon=True
        ).start()

    def _cancel_recording(self) -> None:
        if self.state != STATE_RECORDING:
            return
        self.recorder.stop()
        # Live-typed text stays where it is — append-only typing has no way to
        # take it back; the worker exits on the state change below.
        self._live_typer = None
        self._set_state(STATE_IDLE)
        self.notify("Recording cancelled.")

    def _process(self, audio, live=None) -> None:
        """Worker thread: transcribe, optionally refine, insert at the cursor.

        With live typing (`live` is this take's LiveTyper), part of the
        transcript was already typed while recording: only the audio after its
        committed offset is transcribed here, and only the still-missing text
        is typed (never pasted). The assistant is skipped in that case — it
        rewrites the whole text, but the typed part can't be taken back
        (append-only by design)."""
        try:
            prefix = ""
            pending, typed_any = "", False
            if live is not None:
                # Wait for a decode that was mid-tick to finish; the loop
                # itself exits promptly once the state left RECORDING.
                live.join(timeout=60)
                if live.is_alive():
                    log.warning("live typing worker still busy — using its last committed state")
                # Take the untyped remainder over even when the worker outlived
                # the join: a hung decode/injection that resumes later must not
                # type its `pending` a second time (duplicate words).
                pending, typed_any = live.hand_over()
                prefix = live.committed_text
                audio = audio[live.committed_frames :]
            text = ""
            if len(audio) / SAMPLE_RATE >= 0.3:
                self.transcriber.ensure_loaded(notify=self.notify)
                text = self.transcriber.transcribe(audio, notify=self.notify)
            full_text = f"{prefix} {text}" if prefix and text else (prefix or text)
            if not full_text:
                self.notify("No speech detected.")
                return
            acfg = self.cfg["assistant"]
            if acfg["enabled"]:
                if live is not None:
                    log.info("assistant post-processing skipped — text was live-typed")
                else:
                    try:
                        text = assistant.refine(text, acfg)
                        full_text = text
                    except Exception as exc:
                        log.exception("assistant post-processing failed")
                        self.notify(f"Assistant failed ({exc}) — inserting the raw transcript.", force=True)
            # Record before inserting so the transcript is kept even if the
            # insertion into the target window fails.
            if self.cfg["history_enabled"]:
                try:
                    self.history.add(full_text)
                except Exception:
                    log.exception("could not add transcript to history")
            if live is not None:
                # Flush what live typing still owes: text committed but not yet
                # typed (a modifier was held), plus the transcript of the rest.
                rest = sanitize_typed_text(text)
                if pending:
                    rest = f"{pending} {rest}" if rest else pending
                leftover = ""
                if rest:
                    leftover = self.injector.type_plain_blocking(
                        (" " if typed_any else "") + rest
                    )
                if leftover:
                    # Only the untyped remainder goes to the clipboard: pasting
                    # the whole transcript would duplicate what was typed.
                    if self._copy_for_recovery(leftover):
                        self.notify(
                            "A modifier key was held down — the rest of the transcript "
                            "is on the clipboard, press Ctrl+V.",
                            force=True,
                        )
                    else:
                        self.notify(
                            "A modifier key was held down — part of the transcript "
                            "was not typed. Copy it from Settings → History.",
                            force=True,
                        )
                elif self.injector.clipboard_mode() == "always":
                    # Live typing never touches the clipboard by itself.
                    if self.injector.copy_to_clipboard(full_text):
                        self._notify_copied(full_text)
            else:
                self._insert_transcript(full_text)
            self.post("flash_text", full_text)
        except Exception as exc:
            log.exception("processing failed")
            if is_cuda_library_error(exc):
                # A GPU/CUDA library failure that the CPU fallback couldn't
                # recover from: give an actionable message, not the raw DLL name.
                self.notify(
                    "GPU transcription needs the NVIDIA CUDA 12 libraries. "
                    "Set Device = CPU in Settings → Whisper, or see the tray "
                    "menu → Help / Troubleshooting.",
                    force=True,
                )
            else:
                self.notify(f"Transcription failed: {exc}", force=True)
        finally:
            self.post("done")

    def _insert_transcript(self, text: str) -> None:
        """Insert `text` at the cursor and say where it ended up.

        A successful insertion is silent — the text is visibly there. But a
        transcript that stayed on the clipboard has to be announced: the app
        cannot see whether the focused window took the paste, so with no text
        field under the cursor the insertion "succeeds" into nothing and only
        this message tells the user that Ctrl+V still produces the text.
        At most one notification per recording: a failed insertion has its own
        (forced) message and returns instead of also confirming the copy.
        """
        try:
            on_clipboard = self.injector.insert(text)
        except Exception as exc:
            # The transcript itself worked — say so instead of letting this
            # surface as "Transcription failed", and point at the place the
            # text can be recovered from.
            log.exception("could not insert the transcript")
            if self._copy_for_recovery(text):
                self.notify(
                    f"Could not insert the text ({exc}) — it is on the "
                    "clipboard, press Ctrl+V.",
                    force=True,
                )
            else:
                self.notify(
                    f"Could not insert the text ({exc}) — copy it from "
                    "Settings → History.",
                    force=True,
                )
            return
        if on_clipboard:
            self._notify_copied(text)

    def _notify_copied(self, text: str) -> None:
        """Confirm a transcript that is now on the clipboard.

        Same wording and preview as the tray's "Copy last transcript", because
        it is the same promise — and the preview is what makes the message
        useful: it says *which* text a Ctrl+V would produce. Not forced; this
        is a success message, so the notifications setting decides.
        """
        preview = text if len(text) <= 60 else text[:60].rstrip() + "…"
        self.notify(f"Copied to the clipboard: {preview}")

    def _copy_for_recovery(self, text: str) -> bool:
        """Put a transcript the app could not insert on the clipboard, so it is
        one Ctrl+V away instead of four clicks into Settings → History.

        Returns whether it really got there — the caller words its notification
        after it, because promising a clipboard that stayed empty is worse than
        naming the history. Disabled by `clipboard_copy = "off"`; runs on the
        processing thread, so it goes through the injector (pyperclip, no Qt).
        """
        if self.injector.clipboard_mode() == "off":
            return False
        return self.injector.copy_to_clipboard(text)

    def _copy_last_transcript(self) -> None:
        """Put the most recent transcript back on the clipboard.

        Recovery in one click for the case the app already tells users about:
        an insertion that failed, a paste that landed in the wrong window, a
        transcript overwritten by the next copy. The alternative — open
        Settings, walk the sidebar to History, find the entry, press its Copy
        button — is four steps for the text the user just dictated.

        Main thread only (posted as an event): the clipboard fallback is Qt's.
        """
        try:
            text = self.history.latest()
        except Exception:
            log.exception("could not read the transcript history")
            self.notify("Could not read the transcript history.", force=True)
            return
        if not text:
            # Also the state right after "Keep a local history" was switched
            # off — say what is missing instead of a silent no-op.
            self.notify("No transcript in the history yet.", force=True)
            return
        from .qtutil import copy_to_clipboard

        if copy_to_clipboard(text):
            self._notify_copied(text)
        else:
            self.notify(
                "Could not copy to the clipboard — open Settings → History to copy it there.",
                force=True,
            )

    def _live_preview_loop(self, recording_id: int) -> None:
        """Worker thread: periodically transcribe the audio captured so far
        and push a rolling preview to the overlay bubble. Skips a round when
        the transcriber is busy.

        Loading the model here (with a notification, so a first-use download
        isn't silent) both warms it up for the final pass and lets the preview
        work on the very first take instead of showing nothing until loaded.
        """
        try:
            self.transcriber.ensure_loaded(notify=self.notify)
        except Exception:
            log.exception("live preview model load failed — disabling for this take")
            return
        while self.state == STATE_RECORDING and recording_id == self._recording_id:
            time.sleep(_LIVE_PREVIEW_INTERVAL)
            if self.state != STATE_RECORDING or recording_id != self._recording_id:
                return
            # Only grab the tail the preview actually uses — snapshotting the
            # whole growing buffer every tick would be O(n²) on long takes.
            audio = self.recorder.snapshot(max_frames=_PREVIEW_WINDOW_SECONDS * SAMPLE_RATE)
            if len(audio) < SAMPLE_RATE:  # wait for at least ~1 s of audio
                continue
            try:
                text = self.transcriber.preview(audio)
            except Exception:
                log.exception("live preview transcription failed — disabling for this take")
                return
            if text and self.state == STATE_RECORDING and recording_id == self._recording_id:
                self.post("preview_text", text)

    # ------------------------------------------------------------ helpers

    def _set_state(self, state: str) -> None:
        previous = self.state
        self.state = state
        # Mute configured apps (Discord, …) for exactly the duration of the
        # recording. Deactivation on any exit from RECORDING (finish, cancel,
        # too-short, auto-stop) happens here — always before _process pastes,
        # since that runs only after the PROCESSING transition below.
        try:
            if state == STATE_RECORDING and previous != STATE_RECORDING:
                self.integrations.on_recording_start()
            elif previous == STATE_RECORDING and state != STATE_RECORDING:
                self.integrations.on_recording_stop()
        except Exception:
            log.exception("mute integration failed during state change")
        self.tray.set_state(state)
        if self.overlay is not None:
            try:
                self.overlay.set_state(state)
            except Exception:
                log.debug("overlay state update failed", exc_info=True)
        if self._settings_window is not None:
            # Keep the Home hero in sync. A closed-but-still-referenced window
            # is fine (its widgets outlive the close), and one already deleted
            # by _open_settings raises RuntimeError on attribute access — which
            # must never abort a state transition.
            try:
                self._settings_window.set_app_state(state)
            except RuntimeError:
                self._settings_window = None

    def _beep(self, frequency: int) -> None:
        if not self.cfg["beep"] or sys.platform != "win32":
            return

        def play():
            try:
                import winsound

                winsound.Beep(frequency, 120)
            except Exception:
                log.debug("could not play the %d Hz beep", frequency, exc_info=True)

        threading.Thread(target=play, daemon=True).start()

    def _sync_autostart(self, repair_block: bool = False) -> None:
        """Match the OS autostart entry to the setting — and say so when that
        failed. A registration that silently doesn't take is indistinguishable
        from a working one until the machine is rebooted and the app isn't
        there, so this never fails quietly."""
        problem = autostart.sync(bool(self.cfg["autostart"]), repair_block=repair_block)
        if problem:
            self.notify(f"“Start with the system” is not active: {problem}.", force=True)

    def _register_hotkey(self) -> None:
        combo = self.cfg["hotkey"]
        try:
            self.hotkeys.register(combo, mode=self.cfg["hotkey_mode"])
        except Exception:
            log.exception("failed to register hotkey %r", combo)
            self.notify(f"Could not register hotkey {combo!r} — change it in Settings.", force=True)

    def apply_settings(self) -> None:
        """Called by the settings window after the config was saved.

        The Whisper model is not reloaded here: Transcriber.ensure_loaded()
        compares its cached model against the config on every use. A session CPU
        fallback likewise clears itself once the device/compute type changes, so
        an explicit device change (e.g. back to CUDA) is retried automatically.
        """
        netutil.apply_insecure_ssl(bool(self.cfg["insecure_ssl"]))
        self._register_hotkey()
        if self.transcriber.backend != self.cfg["backend"]:
            # A backend switch needs a fresh instance; a worker thread that
            # still holds the old transcriber finishes on it harmlessly.
            self.transcriber = create_transcriber(self.cfg)
        # repair_block: saving the settings is the explicit user action that
        # may switch a Windows-disabled entry back on (see autostart.sync).
        self._sync_autostart(repair_block=True)
        self.history.max_entries = max(1, int(self.cfg["history_max"]))
        self.tray.set_state(self.state)
        if self.overlay is not None:
            self.overlay.set_visible(bool(self.cfg["overlay"]["enabled"]))

    def _run_onboarding(self) -> None:
        """First launch: modal setup wizard for the essential settings. A
        completed wizard saves and applies its choices; a skipped (or crashed)
        one falls back to opening Settings so the app is visibly running."""
        from .onboarding import OnboardingWizard

        try:
            # app=self: the wizard's key picker pauses our live global hotkey,
            # or pressing the (already registered) combination while picking
            # would start a real recording behind the modal wizard.
            wizard = OnboardingWizard(self.cfg, app=self)
            accepted = bool(wizard.exec())
        except Exception:
            log.exception("onboarding wizard failed — opening Settings instead")
            self._open_settings()
            return
        if self._quitting:
            # Quit was chosen while the wizard was open: its nested event loop
            # was broken out of — don't resurrect any UI mid-shutdown.
            return
        if accepted:
            self.cfg.save()
            self.apply_settings()
        else:
            self._open_settings()

    def _activate_from_second_launch(self) -> None:
        """A second launch of the app pinged this instance: give the user
        visible feedback instead of the silent nothing a swallowed duplicate
        start would produce — re-assert the overlay (the OS may have dropped
        it, which is usually *why* the user started the app again) and bring
        the settings window up."""
        if self._quitting:
            return
        log.info("second launch detected — showing this instance")
        self.notify(f"{APP_NAME} is already running.", force=True)
        if self.overlay is not None and self.cfg["overlay"]["enabled"]:
            self.overlay.set_visible(True)
        self._open_settings()

    def _open_settings(self) -> None:
        from .settings_ui import SettingsWindow

        window, self._settings_window = self._settings_window, None
        if window is not None:
            try:
                if window.isVisible():
                    self._settings_window = window
                    window.raise_()
                    window.activateWindow()
                    return
            except RuntimeError:
                window = None  # C++ side already gone — build a fresh window
            if window is not None:
                # A closed window must be destroyed, not just dropped: PySide's
                # signal-connection bookkeeping keeps the wrapper (and every
                # pixmap it built) alive, so each open/close cycle would retain
                # a whole window. _set_state tolerates the deleted wrapper.
                try:
                    window.deleteLater()
                except RuntimeError:
                    pass
        self._settings_window = SettingsWindow(self)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _open_updates(self) -> None:
        self._open_settings()
        if self._settings_window is not None:
            try:
                self._settings_window.show_updates_page()
            except Exception:
                log.debug("could not open the updates page", exc_info=True)

    def _open_help(self) -> None:
        self._open_settings()
        if self._settings_window is not None:
            try:
                self._settings_window.show_help_page()
            except Exception:
                log.debug("could not open the help page", exc_info=True)

    def _startup_update_check(self) -> None:
        """Background: notify (once) if a newer release exists. Best-effort — a
        network/API failure is silent."""
        try:
            from . import updater

            releases = updater.fetch_releases(
                include_prerelease=bool(self.cfg["include_prereleases"])
            )
            newer = updater.newer_releases(releases)
        except Exception:
            log.debug("startup update check failed", exc_info=True)
            return
        if newer:
            self.notify(
                f"Update available: {newer[0].tag}. Open the tray menu → Check for updates."
            )

    def _open_config_folder(self) -> None:
        folder = self.cfg.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        from .config import open_path

        open_path(folder)

    def _quit(self) -> None:
        log.info("shutting down")
        self._quitting = True
        if self._poll_timer is not None:
            self._poll_timer.stop()
        try:
            if self.recorder.active:
                self.recorder.stop()
        except Exception:
            log.debug("error stopping the recorder during shutdown", exc_info=True)
        try:
            self.integrations.reset()  # never leave a target app stuck muted
        except Exception:
            log.debug("error resetting mute integrations", exc_info=True)
        # Close the settings window BEFORE stopping the hotkeys: a running
        # hotkey test re-registers the global listener on close, which would
        # otherwise resurrect it after the stop below. force_close skips the
        # unsaved-changes prompt — a modal question would stall the shutdown
        # (and an updater restart) until answered.
        if self._settings_window is not None:
            try:
                self._settings_window.force_close()
            except Exception:
                log.debug("error closing the settings window during shutdown", exc_info=True)
        self.hotkeys.stop()
        self.tray.stop()
        if self.overlay is not None:
            try:
                self.overlay.destroy()
            except Exception:
                log.debug("error destroying overlay", exc_info=True)
        if self.qapp is not None:
            self.qapp.quit()


# ----------------------------------------------------------------- startup


def _ensure_std_streams() -> None:
    """Give the process usable std streams when it has none.

    A PyInstaller ``--windowed`` build runs without a console: ``sys.stdout``
    and ``sys.stderr`` are None. Libraries assume they exist — huggingface_hub's
    tqdm progress bar writes to ``sys.stderr`` during a model download, which
    crashed the whole transcription with "'NoneType' object has no attribute
    'write'". Devnull streams make any such write a harmless no-op. Called
    after ``_setup_logging`` so the real log handlers are already decided."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _setup_logging() -> None:
    handlers: list[logging.Handler] = []
    file_error: Exception | None = None
    try:
        log_dir = config_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_dir / "listen-to-me.log", maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
            )
        )
    except Exception as exc:
        # Remembered rather than logged: there is no logging yet. Reported below
        # so a windowed build that lost its only log file says so somewhere
        # instead of just going quiet.
        file_error = exc
    if sys.stderr is not None:  # absent in --windowed PyInstaller builds
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
    )
    if file_error is not None:
        log.warning("could not open the log file — logging to stderr only (%s)", file_error)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--version" in args:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--selftest" in args:
        from .selftest import run as run_selftest

        return run_selftest()

    _setup_logging()
    _ensure_std_streams()

    # OS-level single-instance guard (named mutex / flock — see
    # singleinstance.py for why a TCP port bind was not reliable on Windows).
    # A refused start pings the running instance so it shows itself.
    global _instance_lock
    _instance_lock = singleinstance.acquire()
    if _instance_lock is None:
        log.info("another instance is already running — pinged it to show itself")
        print(f"{APP_NAME} is already running.", file=sys.stderr or sys.stdout)
        return 0

    try:
        from . import updater

        updater.cleanup_stale_update()
    except Exception:
        logging.getLogger(__name__).exception("stale update cleanup failed")
    try:
        App().run()
    except Exception:
        logging.getLogger(__name__).exception("fatal error")
        return 1
    return 0
