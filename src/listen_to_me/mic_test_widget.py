"""The three-second microphone level test, as one widget for two hosts.

Settings → Audio and the first-run wizard's Microphone page both show it: a
"Test microphone (3 s)" button with its Cancel, a level bar that moves while
the clip records, and a status line that ends on a verdict — works, too quiet
or no signal at all (the `diagnostics.clip_stats` verdicts).

The widget owns everything one test run needs: the worker thread, the signal
bridge that brings its results back onto the Qt main thread, a generation
counter (bumped on every start and every cancel, so whatever a detached worker
still emits is recognized as stale and dropped) and the cancel event the
recording loop polls. What differs between the hosts is injected:

- ``device()`` — the input device to test, read when the test starts;
- ``run(device, on_level, is_cancelled) -> dict`` — the recording itself,
  called on the worker thread (default: `DiagnosticsEngine().mic_test`);
- ``can_start() -> str | None`` — None lets a test start, a string refuses it
  and is shown on the status line ("" refuses without a word, for a host whose
  disabled button already says why).

`started` and `finished(outcome)` let the host fold the test into its own
rules — Settings runs one diagnostic at a time and pauses the global hotkey
while one records; the wizard pauses the hotkey too.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .qtutil import elastic_label

log = logging.getLogger(__name__)

TEST_SECONDS = 3.0
# How long the start button stays disabled after a Cancel: the cancelled
# worker is detached, not stopped, and its recording loop needs up to a poll
# tick to release the input stream — restarting at once would briefly open a
# second stream on the same device.
COOLDOWN_MS = 400

RECORDING_TEXT = "Recording 3 s — speak now…"
CANCELLED_TEXT = "Microphone test cancelled."
# What a host's can_start returns while the app records or transcribes.
APP_BUSY_TEXT = "Finish the current recording first, then run the test."

# finished(outcome) values.
DONE, FAILED, CANCELLED = "done", "failed", "cancelled"


def app_busy(app) -> bool:
    """Whether `app` is recording or transcribing right now — the guard every
    test that borrows the microphone or the hotkey listener runs. False
    without an app (the wizard built from a bare Config in the self-test).

    A hotkey press posted by the listener thread can sit in App's event queue
    for up to one poll tick (100 ms), so App.state alone is stale: hold the
    combo and start a test within that window and the guard would pass, the
    test takes over, and the queued press then starts a recording whose
    release is never delivered. Draining the queue first applies the press
    before the state is read.
    """
    if app is None:
        return False
    poll = getattr(app, "_poll", None)
    if callable(poll):
        try:
            poll()
        except Exception:
            log.debug("could not drain the app event queue", exc_info=True)
    return getattr(app, "state", "idle") != "idle"


def verdict_text(result) -> str:
    """The status line for a finished test's `clip_stats` dict."""
    try:
        peak = int(float(result.get("peak", 0.0)) * 100)
        verdict = result.get("verdict")
    except Exception:  # not a dict — a broken run() stand-in
        log.warning("microphone test returned %r", result)
        return "Microphone test failed: no level was measured."
    if verdict == "silent":
        return (
            "No signal — check that the right device is selected and the "
            "OS allows microphone access."
        )
    if verdict == "quiet":
        return (
            f"Signal is very quiet (peak {peak} %) — move closer to the "
            "microphone or raise its input volume."
        )
    return f"Microphone works ✓ — peak level {peak} %."


def _default_run(device, on_level, is_cancelled) -> dict:
    from .diagnostics import DiagnosticsEngine

    return DiagnosticsEngine().mic_test(
        device, seconds=TEST_SECONDS, on_level=on_level, is_cancelled=is_cancelled
    )


class _MicSignals(QObject):
    """Worker → main thread. The leading int is the generation the worker was
    started with; the widget ignores a payload that no longer matches it."""

    level = Signal(int, float)  # recent peak 0.0-1.0 while the clip records
    done = Signal(int, object)  # diagnostics.clip_stats() dict
    failed = Signal(int, str)


class MicTestWidget(QWidget):
    """Test button + Cancel, level bar and status line; see the module
    docstring for the injected callables. The parts are public — `button`,
    `cancel_button`, `level_bar`, `status` — because Settings' one-diagnostic
    rule enables and disables the button alongside its other tests.

    `cooldown_ms` is how long `button` stays disabled after a Cancel; pass 0
    when the host runs a cool-down of its own over all its start buttons."""

    started = Signal()
    finished = Signal(str)  # DONE | FAILED | CANCELLED

    def __init__(
        self,
        device,
        run=None,
        can_start=None,
        *,
        cooldown_ms: int = COOLDOWN_MS,
        parent=None,
    ):
        super().__init__(parent)
        self._device = device
        self._run = run if run is not None else _default_run
        self._can_start = can_start
        self._gen = 0
        self._running = False
        self._cancel_event: threading.Event | None = None
        self._worker: threading.Thread | None = None  # the latest run's thread
        # Unparented on purpose: each worker holds a reference to it, so a
        # host closed mid-test cannot delete the object a worker emits on.
        self._signals = _MicSignals()
        self._signals.level.connect(self._on_level)
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._cooldown_ms = max(0, int(cooldown_ms))
        self._cooldown = QTimer(self)
        self._cooldown.setSingleShot(True)
        self._cooldown.setInterval(self._cooldown_ms or 1)
        self._cooldown.timeout.connect(self._end_cooldown)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Test microphone (3 s)")
        self.button.setAutoDefault(False)
        self.button.setToolTip(
            "Record three seconds from the selected device and check that a "
            "signal arrives. Speak normally — the level bar should move."
        )
        self.button.clicked.connect(self.start)
        buttons.addWidget(self.button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setToolTip("Stop the running microphone test.")
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        level_row = QHBoxLayout()
        level_row.setContentsMargins(0, 0, 0, 0)
        level_label = QLabel("Level:")
        level_row.addWidget(level_label)
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setTextVisible(False)
        self.level_bar.setToolTip("Input level while the microphone test records.")
        self.level_bar.setAccessibleName("Microphone level")
        level_label.setBuddy(self.level_bar)
        level_row.addWidget(self.level_bar, 1)
        layout.addLayout(level_row)

        # Elastic and selectable: a failure carries PortAudio's message, often
        # with a long device name — it must neither widen the page nor be
        # impossible to copy into a search.
        self.status = QLabel("")
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        elastic_label(self.status)
        layout.addWidget(self.status)

    # -------------------------------------------------------------- control

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Start a test unless one runs or `can_start` refuses; True when it
        started. The result arrives on the main thread via the signals."""
        if self._running:
            return False
        refusal = self._can_start() if self._can_start is not None else None
        if refusal is not None:
            if refusal:
                self.status.setText(refusal)
            return False
        try:
            device = self._device()
        except Exception as exc:  # surfaced, never a dead button
            log.exception("could not read the device for the microphone test")
            self.status.setText(f"Microphone test failed: {exc}")
            return False
        self._gen += 1
        gen = self._gen
        cancel = threading.Event()
        self._cancel_event = cancel
        self._running = True
        self._cooldown.stop()
        self.button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.level_bar.setValue(0)
        # Before the status line: a host reacting to `started` (Settings
        # clears its "another test is running" note) must not overwrite it.
        self.started.emit()
        self.status.setText(RECORDING_TEXT)

        signals, run = self._signals, self._run

        def work():
            try:
                result = run(
                    device,
                    lambda level: signals.level.emit(gen, float(level)),
                    cancel.is_set,
                )
                signals.done.emit(gen, result)
            except Exception as exc:  # surfaced in the UI
                log.exception("microphone test failed")
                signals.failed.emit(gen, str(exc))

        self._worker = threading.Thread(target=work, name="diag-mic", daemon=True)
        self._worker.start()
        return True

    def cancel(self) -> bool:
        """Stop the running test (its Cancel button, a page left, a window
        closed); False when none runs. The worker polls the event and stops
        within ~100 ms; anything it still emits is stale by then."""
        if not self._running:
            return False
        self._gen += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._running = False
        self.cancel_button.setEnabled(False)
        self.level_bar.setValue(0)
        self.status.setText(CANCELLED_TEXT)
        if self._cooldown_ms:
            self.button.setEnabled(False)
            self._cooldown.start()
        else:
            self.button.setEnabled(True)
        self.finished.emit(CANCELLED)
        return True

    def _end_cooldown(self) -> None:
        if not self._running:
            self.button.setEnabled(True)

    def _settle(self) -> None:
        self._running = False
        self.button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    # ------------------------------------------------------------- results

    def _on_level(self, gen: int, level: float) -> None:
        if gen != self._gen or not self._running:
            return
        self.level_bar.setValue(max(0, min(100, int(level * 100))))

    def _on_done(self, gen: int, result) -> None:
        if gen != self._gen or not self._running:
            return
        self._settle()
        self.status.setText(verdict_text(result))
        self.finished.emit(DONE)

    def _on_failed(self, gen: int, message: str) -> None:
        if gen != self._gen or not self._running:
            return
        self._settle()
        self.status.setText(f"Microphone test failed: {message}")
        self.finished.emit(FAILED)
