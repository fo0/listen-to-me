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

from . import APP_NAME, REPO_URL, __version__
from . import assistant, autostart, netutil, singleinstance
from .audio import SAMPLE_RATE, Recorder
from .choices import resolve_input_device
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

# How long before the maximum recording length the heads-up goes out.
_LENGTH_WARNING_SECONDS = 30


def length_warning_message(
    elapsed: float, max_seconds, warn_seconds: float = _LENGTH_WARNING_SECONDS
) -> str | None:
    """The heads-up for a take that has been running `elapsed` seconds, or
    None when none is due.

    The maximum recording length used to be invisible until it hit: the take
    was cut off mid-sentence with "Maximum recording length reached." and
    everything said past that point was never captured at all. One warning in
    the closing seconds is enough to wrap the sentence up (or to stop and
    continue in a second take).

    Silent for a cap that is not comfortably longer than the warning window
    itself — warning at 30 of 45 seconds is noise about a limit that short
    because the user asked for it. NaN/None/garbage from a hand-edited config
    falls through the `not (... > ...)` guards to None rather than raising
    inside the 100 ms poll.
    """
    try:
        cap = float(max_seconds)
    except (TypeError, ValueError):
        return None
    if not cap > warn_seconds * 2:
        return None
    remaining = cap - float(elapsed)
    if not 0 < remaining <= warn_seconds:
        return None
    return (
        f"{int(round(remaining))} seconds left of the {int(cap)} s maximum "
        "recording length — the recording stops by itself then."
    )


# Hard cap on the rule list. A hand-edited config is untrusted input, and the
# rules are compiled and applied after every single dictation.
_MAX_REPLACEMENT_RULES = 500


def parse_replacements(spec: str) -> list[tuple[str, str]]:
    """The `find => replace` rules in `spec`, in the order they are written.

    One rule per line. Blank lines and lines starting with `#` are comments; a
    line without the `=>` separator is skipped with a warning rather than
    failing the list, because this is hand-edited text and one typo must not
    cost the other rules. An empty right-hand side is allowed on purpose — it
    deletes the word (a stock filler this speaker never wants written out).

    Qt-free and side-effect free so the rule syntax is testable headlessly.
    """
    rules: list[tuple[str, str]] = []
    for number, line in enumerate(str(spec or "").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" not in line:
            log.warning("replacement rule on line %d has no “=>” separator, ignored: %.60r", number, line)
            continue
        find, replace = line.split("=>", 1)
        find = find.strip()
        if not find:
            log.warning("replacement rule on line %d has an empty search term, ignored", number)
            continue
        rules.append((find, replace.strip()))
        if len(rules) >= _MAX_REPLACEMENT_RULES:
            log.warning("more than %d replacement rules — the rest is ignored", _MAX_REPLACEMENT_RULES)
            break
    return rules


def assistant_failure_message(exc: BaseException) -> str:
    """What to show when the assistant could not clean up a finished dictation.

    The Assistant page's "Test connection" has translated transport failures
    into one actionable sentence since it existed, but this — the path that
    fires after a *real* dictation — still put the raw exception in the
    notification: `requests` renders an endpoint that is simply not running as
    its whole transport chain ("HTTPSConnectionPool(host='localhost',
    port=11434): Max retries exceeded with url: … NewConnectionError(…)"), a
    stack-trace fragment where a next step belongs, in the one place the user
    is not sitting in the settings window looking for it.

    The app's own wording (`AssistantError`, e.g. a base_url the config check
    rejected) and an HTTP status from raise_for_status pass through untouched —
    describe_error only rewrites the transport failures.

    Always closes on where the text went: the transcript is never lost to an
    assistant failure, it is inserted unrefined.
    """
    reason = str(netutil.describe_error(exc)).strip()
    # The translated sentences end in a full stop; a passed-through exception
    # message (or a bare class name) does not, and would run straight into the
    # next sentence.
    if reason and reason[-1] not in ".!?":
        reason += "."
    return f"Assistant failed: {reason} Inserting the raw transcript."


def apply_replacements(text: str, spec: str) -> str:
    """`text` with the user's `find => replace` rules applied, in order.

    Whisper mis-hears the same domain words the same way every time — a product
    name, a colleague's surname, an acronym — and the initial prompt only
    *biases* recognition, it cannot guarantee a spelling. These rules are the
    deterministic second half of that: what the recognizer got wrong anyway is
    corrected before the text reaches the cursor.

    Matching is case-insensitive and on whole words, and the replacement is
    inserted exactly as written — one rule therefore catches the word at the
    start of a sentence as well as inside it, and always produces the spelling
    the user typed. The word-boundary guards are only added on a side that
    starts/ends with a word character, so a rule for “z.B.” or “:-)” still
    matches.

    Never raises: this runs on the worker thread between a finished dictation
    and its insertion, so a bad rule (a search term that is somehow not
    compilable even escaped) must cost the correction, never the transcript.
    """
    if not text:
        return text
    rules = parse_replacements(spec)
    if not rules:
        return text
    import re

    for find, replace in rules:
        try:
            pattern = re.escape(find)
            if find[0].isalnum() or find[0] == "_":
                pattern = r"\b" + pattern
            if find[-1].isalnum() or find[-1] == "_":
                pattern = pattern + r"\b"
            # A backslash or \1 in the replacement is literal text here, not a
            # group reference — the user wrote a word, not a regex.
            text = re.sub(pattern, replace.replace("\\", r"\\"), text, flags=re.IGNORECASE)
        except Exception:
            log.exception("replacement rule %r could not be applied", find)
    return text


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
        self._recording_started = 0.0  # monotonic start of the running take
        self._length_warned = False  # one max-length heads-up per take
        # The configured microphone index the "recording with the system
        # default instead" notice was last shown for, so a mic that stays
        # unplugged does not repeat it before every single take.
        self._device_fallback_notified = object()
        self._clock_seconds = -1  # whole second the tray clock currently shows
        # Global hotkey suspended by the user (tray menu → Pause hotkey).
        # Deliberately not a config key — see _toggle_hotkey_pause.
        self.hotkey_paused = False
        self._live_typer = None  # per-take live-typing worker (livetype.py)
        self._quitting = False  # set by _quit; guards UI opened after shutdown
        # True while a factory reset is running its (modal, nested) wizard —
        # see _factory_reset.
        self._resetting = False
        # True while a download is showing on the icon/tray (see _set_progress).
        self._progress_active = False

    def post(self, kind: str, payload=None) -> None:
        """Thread-safe: queue an event for the main loop."""
        self.events.put((kind, payload))

    def notify(self, message: str, force: bool = False) -> None:
        """Thread-safe desktop notification: routed through the event queue so
        the tray's showMessage() is always invoked on the Qt main thread."""
        self.post("notify", (message, force))

    def progress(
        self, label: str | None, fraction: float | None, done: int = 0, total: int = 0
    ) -> None:
        """Thread-safe progress report for a running download (#110).

        The transcribers' download watchers and the updater call this from
        worker threads, so like notify() it only queues — the floating icon
        and the tray are updated by the main-thread drain. `label=None` means
        the download ended and the display goes back to the plain state icon —
        which is why `label` is annotated optional: that sentinel is the whole
        end-of-download protocol, not an accident.
        """
        self.post("progress", None if label is None else (str(label), fraction, done, total))

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
        if self.cfg.load_failed:
            # The settings exist but could not be read (locked/corrupt file):
            # the app is running on defaults right now, which looks like every
            # setting was reset — say so instead of letting the user discover
            # it hotkey by hotkey. Save() preserves the file as config.json.bad.
            self.notify(
                "The settings file could not be read — running on defaults. "
                "Saving any setting preserves the old file as config.json.bad.",
                force=True,
            )
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
        self._check_length_warning()
        self._tick_recording_clock()

    def _check_length_warning(self) -> None:
        """Warn once, shortly before the maximum length ends the running take.

        Rides the 100 ms timer that already drains the event queue instead of
        owning a timer that would have to be started and stopped with every
        take: the check is two comparisons on the main thread, and it can
        never outlive a recording it no longer belongs to.
        """
        if self._length_warned or self.state != STATE_RECORDING:
            return
        message = length_warning_message(
            time.monotonic() - self._recording_started, self.cfg["max_seconds"]
        )
        if message is None:
            return
        # Latched before notifying, so a failure downstream cannot turn this
        # into one notification per poll tick for the rest of the take.
        self._length_warned = True
        self.notify(message)

    def _tick_recording_clock(self) -> None:
        """Count the running take up in the tray status and on the floating
        icon, once per second.

        Rides the 100 ms timer that already drains the event queue (same
        reasoning as the length warning) and only touches the two surfaces when
        the whole second changed — the labels are rebuilt once a second, not
        sixty times. `_set_state` writes the clock-free label on every
        transition, so leaving RECORDING clears the counter by itself.

        Every surface is fed, and each in its own try: the floating icon is
        the control that never leaves the screen while the user speaks, the
        Home hero is the one in front of whoever dictates from the window, so
        a take clock only the tray carries is missing exactly where it is being
        looked for — and a failure on one of them must not cost the others
        their update.
        """
        if self.state != STATE_RECORDING:
            self._clock_seconds = -1
            return
        seconds = int(time.monotonic() - self._recording_started)
        if seconds == self._clock_seconds:
            return
        self._clock_seconds = seconds
        try:
            self.tray.set_elapsed(seconds)
        except Exception:
            log.debug("could not update the tray recording clock", exc_info=True)
        if self.overlay is not None:
            try:
                self.overlay.set_elapsed(seconds)
            except Exception:
                log.debug("could not update the overlay recording clock", exc_info=True)
        if self._settings_window is not None:
            # Same handling as in _set_state: a window already deleted by
            # _open_settings raises RuntimeError on attribute access, and a
            # clock tick must never be what takes the app down.
            try:
                self._settings_window.set_app_elapsed(seconds)
            except RuntimeError:
                self._settings_window = None
            except Exception:
                log.debug("could not update the Home recording clock", exc_info=True)

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
                elif self.state == STATE_PROCESSING:
                    # Same feedback as the toggle branch: the user is already
                    # speaking into a dead mic — silence here loses dictation.
                    self.notify("Still transcribing the previous recording…")
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
        elif kind == "toggle_hotkey_pause":
            self._toggle_hotkey_pause()
        elif kind == "toggle_overlay":
            ocfg = self.cfg["overlay"]
            ocfg["enabled"] = not ocfg["enabled"]
            if not self.cfg.save():
                self.notify("Could not save the settings — see the log file.", force=True)
            if self.overlay is not None:
                self.overlay.set_visible(bool(ocfg["enabled"]))
            self.tray.set_state(self.state)  # refresh the "Show floating icon" tick
        elif kind == "reset_overlay_position":
            self._reset_overlay_position()
        elif kind == "cancel":
            self._cancel_recording()
        elif kind == "copy_last":
            self._copy_last_transcript()
        elif kind == "copy_text":
            self._copy_transcript(str(payload))
        elif kind == "auto_stop":
            if self._owns_take(payload):
                self.notify("Maximum recording length reached.")
                self._finish_recording()
        elif kind == "stream_died":
            # The input stream ended on its own (device unplugged, PortAudio
            # abort): finish with what was captured instead of showing a
            # recording that silently stopped listening.
            if self._owns_take(payload):
                self.notify("The microphone stream ended unexpectedly.", force=True)
                self._finish_recording()
        elif kind == "done":
            self._set_state(STATE_IDLE)
        elif kind == "notify":
            message, force = payload if isinstance(payload, tuple) else (payload, False)
            self.tray.notify(str(message), force=bool(force))
        elif kind == "progress":
            self._set_progress(payload)
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
        elif kind == "factory_reset":
            self._factory_reset()
        elif kind == "quit":
            self._quit()

    # ---------------------------------------------------------- recording

    def _owns_take(self, recording_id) -> bool:
        """Whether a recorder-originated event still belongs to the running take.
        `auto_stop`/`stream_died` are posted from PortAudio's callback thread and
        can sit up to 100 ms in the queue, so one from take A drained after a
        stop-A/start-B pair would otherwise stop take B with A's message."""
        if self.state != STATE_RECORDING:
            return False
        return recording_id is None or recording_id == self._recording_id

    def _start_recording(self) -> None:
        # Reserved before start(): the callbacks are handed to the recorder
        # here, and a stream that dies during start() already fires them.
        take = self._recording_id + 1
        # PortAudio indices are positional: unplugging the configured
        # microphone (or plugging anything else in) makes the stored index
        # point at nothing or at another device. Resolve before opening the
        # stream so the take survives on the system default instead of dying
        # with a raw PortAudio error naming no fix.
        configured = self.cfg["input_device"]
        device, device_note = resolve_input_device(configured)
        try:
            self.recorder.start(
                device=device,
                max_seconds=self.cfg["max_seconds"],
                on_limit=lambda: self.post("auto_stop", take),
                on_ended=lambda: self.post("stream_died", take),
            )
        except Exception as exc:
            log.exception("could not start recording")
            self.notify(f"Could not start recording: {exc}", force=True)
            return
        if device_note is not None:
            log.warning("input device %r is gone — recording with the system default", configured)
            # Forced (this is a device problem the user has to fix in the
            # settings), but only once per configured device: the alternative
            # is an interruption before every dictation until the microphone
            # comes back.
            if self._device_fallback_notified != configured:
                self._device_fallback_notified = configured
                self.notify(device_note, force=True)
        else:
            # Plugged back in — re-arm, so a second disappearance is reported
            # again instead of being swallowed by the first one's marker.
            self._device_fallback_notified = object()
        # Bump on every take so a lingering worker from a previous recording
        # sees a changed id and exits, even if this take has no worker. Before
        # the state change: _set_state re-enters RECORDING first, and a stale
        # worker that wakes in between must not mistake it for its own take.
        self._recording_id = take
        self._recording_started = time.monotonic()
        self._length_warned = False
        self._clock_seconds = -1  # the next poll renders this take's 0:00
        self._set_state(STATE_RECORDING)
        self._beep(880)
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
        if self._live_typer is None:
            if want_preview:
                threading.Thread(
                    target=self._live_preview_loop,
                    args=(self._recording_id,),
                    name="live-preview",
                    daemon=True,
                ).start()
            else:
                # Neither the live typer nor the preview loop will load the
                # model for this take, so nothing else would — and the load
                # would land after the last word instead of during the take.
                self._warm_up_model()

    def _live_typing_gate(self) -> str | None:
        """Why live typing must stay off for this take (None = it can run).

        Hold mode is only safe with a hotkey that (a) contains no modifier —
        off Windows the modifier state can't be polled while the chord is held,
        and on Windows a held modifier would defer every chunk to the very end
        anyway — and (b) contains no key our own typing could synthesize (a
        character key or Space), which the hold listener would misread as the
        hotkey being released, stopping the recording mid-sentence.

        Toggle mode tolerates modifier chords (our plain typing never completes
        them), but a bare typable key as the toggle hotkey would be pressed by
        our own injected keystrokes and toggle-stop the take mid-sentence.
        """
        if not hasattr(self.transcriber, "preview_segments"):
            return "backend provides no live segments"
        try:
            has_modifier, has_typable = Hotkeys.combo_flags(self.cfg["hotkey"])
        except Exception:
            log.exception("could not analyze the hotkey combo")
            return "hotkey combo could not be analyzed"
        if self.cfg["hotkey_mode"] == "hold":
            if has_modifier:
                return "hold-mode hotkey contains a modifier key"
            if has_typable:
                return "hold-mode hotkey contains a typable key"
        elif has_typable and not has_modifier:
            return "hotkey is a bare typable key our own typing would press"
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
            if live is not None:
                live.hand_over()  # discarded: the worker must not type into idle
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
        # take it back. hand_over() (result discarded) disarms the worker for
        # good: relying on the state change alone leaves a window where a
        # worker mid-tick still types the cancelled take's pending text.
        live, self._live_typer = self._live_typer, None
        if live is not None:
            live.hand_over()
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
            # The whole take, kept before live typing slices the already
            # committed part off `audio` below: a recording that produced no
            # text is diagnosed from everything the microphone delivered, not
            # from whatever tail was left over.
            captured = audio
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
                self.transcriber.ensure_loaded(notify=self.notify, progress=self.progress)
                text = self.transcriber.transcribe(
                    audio, notify=self.notify, progress=self.progress
                )
            full_text = f"{prefix} {text}" if prefix and text else (prefix or text)
            if not full_text:
                self._notify_no_speech(captured)
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
                        self.notify(assistant_failure_message(exc), force=True)
            if live is None:
                # Last, so the user's own rules are the final word — the
                # assistant rewrites the whole text and would otherwise be free
                # to undo them. Skipped for live typing for the same reason the
                # assistant is: part of the text is already at the cursor and
                # append-only typing cannot take it back, so a correction here
                # would only reach the tail and leave history disagreeing with
                # what was actually typed.
                full_text = apply_replacements(full_text, self.cfg["replacements"])
                text = full_text
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

    def _notify_no_speech(self, audio) -> None:
        """Report a take that produced no text — naming a microphone that
        delivered nothing instead of leaving the recognition to take the blame.

        Runs on the processing thread (notify() posts, so this stays off Qt)
        and is deliberately best-effort: the statistics only decide the
        wording, so failing to compute them costs the diagnosis, never the
        message. Forced only for the two verdicts that name a fixable device
        problem — "no speech" itself stays an ordinary notification.
        """
        from .diagnostics import clip_stats, no_speech_message

        verdict = "unknown"
        try:
            verdict = str(clip_stats(audio)["verdict"])
        except Exception:
            log.debug("could not classify the recorded audio", exc_info=True)
        self.notify(no_speech_message(verdict), force=verdict in ("silent", "quiet"))

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

        Reading the history is what belongs here; the clipboard itself is
        `_copy_transcript`, shared with the tray's recent-transcripts menu.
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
        self._copy_transcript(text)

    def _copy_transcript(self, text: str) -> None:
        """Put one transcript on the clipboard and say how that went.

        Shared by the tray's "Copy last transcript" and by every entry of its
        "Recent transcripts" submenu, so the two can never drift into different
        wording or a different clipboard path. Main thread only (posted as an
        event): the fallback inside copy_to_clipboard is Qt's.
        """
        if not text:
            # An entry the store would not have accepted (a hand-edited
            # history.json) — never a silently empty clipboard action.
            self.notify("That transcript is empty — nothing to copy.", force=True)
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
            self.transcriber.ensure_loaded(notify=self.notify, progress=self.progress)
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

    def _warm_up_model(self) -> None:
        """Start loading the transcription model while the take is still running.

        The model is loaded on first use, and that used to be *after* the user
        stopped speaking: the first dictation of a session paid the whole load
        — on the very first run the download too — as dead time between the
        last word and the inserted text, even though the app knew a
        transcription was coming the moment the recording started. Speaking is
        exactly the window that load fits into: the audio is buffered by
        PortAudio's callback thread either way.

        `ensure_loaded` is the same idempotent, locked call `_process` makes,
        so the transcription afterwards either finds the model ready or waits
        for this thread to finish it — never a second load, and never a load of
        something else (the transcriber is captured here, so a backend switched
        mid-take leaves this thread warming the instance it was started for).

        Only started when no other loop already loads the model for this take,
        and silent on failure: this is a head start, not the transcription. The
        real attempt in `_process` runs the same call and reports what goes
        wrong there — reporting it twice would blame the wrong moment for it.
        """
        transcriber = self.transcriber
        try:
            if transcriber.loaded:
                return
        except Exception:
            log.debug("could not check whether the model is loaded", exc_info=True)
            return

        def load():
            try:
                # notify/progress are passed on: a first-run download is
                # minutes long, and hiding it until the take ends is what the
                # download progress display exists to prevent.
                transcriber.ensure_loaded(notify=self.notify, progress=self.progress)
            except Exception:
                log.debug("model warm-up failed — the transcription reports it", exc_info=True)

        threading.Thread(target=load, name="model-warmup", daemon=True).start()

    # ------------------------------------------------------------ helpers

    def _set_progress(self, payload) -> None:
        """Show (or clear) a running download on the floating icon and in the
        tray tooltip. Main thread only — App.progress() is what workers call.

        `payload` is (label, fraction, done, total) while a download runs and
        None once it is over; `fraction` stays None whenever the total size is
        unknown, and the icon then shows an indeterminate ring instead of a
        made-up percentage.
        """
        from .progress import progress_text

        # "or None": a report that renders to nothing is no report — a blank
        # tooltip next to a spinning ring says less than the state line does.
        text = None if payload is None else (progress_text(*payload) or None)
        fraction = payload[1] if (payload is not None and text is not None) else None
        self._progress_active = text is not None
        try:
            self.tray.set_progress(text)
        except Exception:
            log.debug("tray progress update failed", exc_info=True)
        if self.overlay is not None:
            try:
                self.overlay.set_progress(fraction, text)
            except Exception:
                log.debug("overlay progress update failed", exc_info=True)

    def _clear_progress(self) -> None:
        """Drop a progress display that is no longer current. The backstop for
        a watcher whose final "download over" report never arrived (a killed
        worker, a report lost to a shutdown): every state change ends any
        download that was running for it."""
        if self._progress_active:
            self._set_progress(None)

    def _set_state(self, state: str) -> None:
        previous = self.state
        self.state = state
        self._clear_progress()
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
        if self.hotkey_paused:
            # Every path that hands the listener back (settings saved, hotkey
            # test finished, key picker closed) comes through here, so the
            # pause survives all of them instead of being undone by the next
            # unrelated action.
            self.hotkeys.stop()
            log.info("hotkey stays paused — not registering")
            return
        combo = self.cfg["hotkey"]
        try:
            self.hotkeys.register(combo, mode=self.cfg["hotkey_mode"])
        except Exception:
            log.exception("failed to register hotkey %r", combo)
            self.notify(f"Could not register hotkey {combo!r} — change it in Settings.", force=True)

    def _toggle_hotkey_pause(self) -> None:
        """Suspend or resume the global hotkey without touching the settings.

        The hotkey is global by definition: while a game, a remote session or
        another app wants the same combination, the only way out so far was to
        open Settings and change (or clear) it — and to remember what it was
        afterwards. Pausing costs one click and leaves the combination alone.

        Never persisted. A pause that survived a restart would be
        indistinguishable from an app that stopped working, with nothing on
        screen at logon to explain it; the tray status line and a forced
        notification say it out loud for the same reason.

        Refused while a take is running: in hold mode the release event would
        never arrive, so the recording would sit there until the maximum length
        cut it off — and stopping it for the user would insert text into
        whatever window the tray click just focused.
        """
        if self.state != STATE_IDLE:
            self.notify("Finish the current recording before pausing the hotkey.", force=True)
            self.tray.set_state(self.state)  # put the menu tick back
            return
        self.hotkey_paused = not self.hotkey_paused
        if self.hotkey_paused:
            self.hotkeys.stop()
            self.notify(
                "Hotkey paused — switch it back on in the tray or floating-icon "
                "menu when you need it.",
                force=True,
            )
        else:
            self._register_hotkey()
            self.notify("Hotkey active again.", force=True)
        log.info("global hotkey %s by the user", "paused" if self.hotkey_paused else "resumed")
        self.tray.set_state(self.state)

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
            # Order matters: the always-on-top flag rebuilds the native window
            # and hides it, so visibility is (re-)applied afterwards.
            self.overlay.apply_always_on_top()
            self.overlay.set_visible(bool(self.cfg["overlay"]["enabled"]))

    def _factory_reset(self) -> None:
        """Settings → General → "Reset to factory settings": every setting back
        to DEFAULTS, then the first-run wizard again.

        The defaults are applied *before* the wizard opens, not after it
        finishes: the wizard can be cancelled, and what has to be running then
        is the reset app — a configuration the user just discarded must not
        keep driving the hotkey and the autostart entry behind a cancelled
        dialog. apply_settings() re-registers the hotkey, syncs autostart off,
        rebuilds the transcriber for the default backend and re-applies the
        overlay visibility; the icon's saved position is gone with the config,
        so it is moved back explicitly.
        """
        if self._quitting or self._resetting:
            # The wizard below runs a nested event loop, during which the queue
            # keeps draining — a second click before the settings window closed
            # would otherwise stack a second wizard on top of the first.
            return
        self._resetting = True
        try:
            saved = self.cfg.reset()
            self.apply_settings()
            if self.overlay is not None:
                try:
                    self.overlay.reapply_position()
                except Exception:
                    log.exception("could not move the floating icon back after the reset")
            if not saved:
                self.notify(
                    "The settings were reset, but could not be written to disk — "
                    "your previous settings will be back after a restart. "
                    "See the log file.",
                    force=True,
                )
            log.info("factory reset applied — starting the setup wizard")
            self._run_onboarding()
        finally:
            self._resetting = False

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
            if not self.cfg.save():
                self.notify("Could not save the settings — see the log file.", force=True)
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

    def _reset_overlay_position(self) -> None:
        """Move the floating icon back to its default corner.

        Reported either way. The icon may be switched off (nothing to move) or
        the move may fail, and a menu entry that silently does nothing is the
        one outcome this must not have — the user is reaching for it precisely
        because the icon is not where they can see it.
        """
        if self.overlay is None or not self.cfg["overlay"]["enabled"]:
            self.notify(
                "The floating icon is switched off — turn it on first "
                "(tray menu → Show floating icon).",
                force=True,
            )
            return
        try:
            self.overlay.reset_position()
        except Exception:
            log.exception("could not reset the overlay position")
            self.notify("Could not move the floating icon — see the log file.", force=True)
            return
        self.notify("Floating icon moved back to the bottom right.")

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
        # The state stays RECORDING through teardown — disarm a live-typing
        # worker explicitly or it may keep typing while the app shuts down.
        live, self._live_typer = self._live_typer, None
        if live is not None:
            try:
                live.hand_over()
            except Exception:
                log.debug("error disarming the live typer during shutdown", exc_info=True)
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


def _usage() -> str:
    """The `--help` text, naming the config directory this machine really uses.

    Built here rather than baked into a module constant: the directory depends
    on APPDATA/XDG_CONFIG_HOME, which belongs to the environment of the run
    asking for help, and resolving it at import time would put that lookup in
    front of `--version` too.

    Naming the resolved path is the whole point of the line. `--help` is what
    someone reaches for when the GUI does not come up, and that is exactly when
    the tray menu's "Open config folder" — the only other place the location is
    named — cannot be clicked. Sending them to look for "the platform config
    dir" left them guessing between three different conventions.

    A directory that cannot be resolved falls back to the wording this text
    always had: help that prints is worth more than help that is exact.
    """
    try:
        location = f"the config dir — on this machine:\n  {config_dir()}\n"
    except Exception:
        # No logging is configured yet (main() sets it up further down), and a
        # help text is not the place to start it — the fallback says the same
        # thing in general terms and nothing is lost but the exact path.
        location = "the platform config dir.\n"
    return f"""\
{APP_NAME} — push-to-talk voice typing. Started without a flag it runs as a
tray app; everything else is configured in its settings window, not here.

Usage: listen-to-me [--version | --selftest | --help]

  --version     Print the version and exit. Imports no Qt, so it works before
                the GUI dependencies are installed.
  --selftest    Run the packaging self-test and exit with its result (0 = pass).
                Needs every runtime dependency.
  -h, --help    Show this help and exit.

Settings live in config.json in {location}\
The tray menu's "Open config folder" points at it. Full docs: {REPO_URL}"""

_FLAGS = ("--version", "--selftest", "--help", "-h")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Own flags only — they are stripped before Qt sees sys.argv (see App.run),
    # so an unrecognized one is nobody's and would otherwise be swallowed: the
    # app would come up as if nothing had been asked of it. A GUI launched from
    # a shortcut or the autostart entry never passes arguments, so refusing the
    # ones we don't know costs nothing and turns a typo into an answer.
    unknown = [arg for arg in args if arg not in _FLAGS]
    if unknown:
        # Checked before the known flags, not after: `--verison --version`
        # answering with the version would hide the typo it was asked about.
        stream = sys.stderr or sys.stdout
        print(f"{APP_NAME}: unknown option: {unknown[0]}", file=stream)
        print("Try --help for the three flags this app has.", file=stream)
        return 2
    if "--help" in args or "-h" in args:
        print(_usage())
        return 0
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
