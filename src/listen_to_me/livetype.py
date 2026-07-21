"""Live typing: type stable parts of the transcript at the cursor WHILE recording.

Instead of waiting for the end of the recording, a background worker
periodically transcribes the not-yet-committed audio and types the parts that
have become stable. Three rules make this safe:

- **Agreement policy** (LocalAgreement-2): a leading run of Whisper segments is
  committed only when two consecutive passes over the same audio produce the
  identical text AND the segment ends well before the end of the captured audio
  (the still-being-spoken tail is always unstable). Once a segment is
  committed, the audio offset advances past it, so it is never decoded again
  and the final pass only ever sees the remaining audio.
- **Append-only**: committed text is typed and never corrected — no Backspace,
  no cursor movement, so a wrong early hypothesis can never destroy anything
  the user already had in the target field.
- **Plain text only**: everything goes through injector.sanitize_typed_text()
  (printable characters only, whitespace collapsed to single spaces) and
  injector.type_plain(), which pauses while a physical modifier key is held —
  no Enter/Tab, no accidental Ctrl/Alt/Win chords.

The worker mirrors the threading rules of app._live_preview_loop: it never
touches Qt, talks to the main thread via App.post() only, and dies quietly when
the recording ends or a newer take starts.
"""

from __future__ import annotations

import logging
import threading
import time

from .audio import SAMPLE_RATE
from .injector import sanitize_typed_text

log = logging.getLogger(__name__)

# Seconds between passes. Lower = snappier typing but more CPU; a segment needs
# two agreeing passes, so the first words appear after roughly two ticks.
_TICK_SECONDS = 2.0

# A segment is only committed when it ends at least this far before the end of
# the snapshot — the audio still being spoken re-transcribes differently on
# every pass and must never be typed.
_TAIL_GUARD_SECONDS = 1.0

# Don't bother decoding less than this much uncommitted audio.
_MIN_AUDIO_SECONDS = 1.0

# Safety valve: if no segment stabilizes for this long (constant re-decoding of
# a growing window would get expensive), stop live commits for this take — the
# final pass in app._process still transcribes and types everything remaining.
_MAX_WINDOW_SECONDS = 60.0


def stable_prefix(
    prev: list[tuple[float, str]],
    cur: list[tuple[float, str]],
    max_end: float,
) -> tuple[list[str], float]:
    """The leading run of segments that is identical in two consecutive passes.

    `prev` and `cur` are (end_seconds, text) lists over the same audio; only
    the texts are compared — end timestamps jitter a little between passes.
    Segments ending after `max_end` (the tail guard) never qualify. Returns the
    stable texts and the end time (from `cur`) of the last one, i.e. how far
    the committed-audio offset may advance.
    """
    texts: list[str] = []
    end_time = 0.0
    for (_p_end, p_text), (c_end, c_text) in zip(prev, cur):
        if not c_text or p_text != c_text or c_end > max_end:
            break
        texts.append(c_text)
        end_time = c_end
    return texts, end_time


def _join(a: str, b: str) -> str:
    return f"{a} {b}" if a and b else (a or b)


class LiveTyper:
    """Background worker for a single take. Created (and started) by
    app._start_recording when live typing is enabled; app._process joins it
    after the recording stops and continues from `committed_frames` /
    `committed_text` / `pending` / `typed_any`.
    """

    def __init__(self, app, recording_id: int, post_preview: bool):
        self.app = app
        self.recording_id = recording_id
        # Also feed the overlay's live-preview bubble (when enabled), so the
        # two features don't run two competing decode loops.
        self.post_preview = post_preview
        self.committed_frames = 0  # absolute frame offset of the committed audio
        self.committed_text = ""  # sanitized transcript of the committed audio
        self.pending = ""  # committed but not yet typed (modifier was held)
        self.typed_any = False  # whether the next chunk needs a separating space
        self._prev: list[tuple[float, str]] | None = None
        self._thread = threading.Thread(target=self._run, name="live-type", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    # ------------------------------------------------------------- worker

    def _active(self) -> bool:
        return self.app._take_active(self.recording_id)

    def _run(self) -> None:
        app = self.app
        try:
            app.transcriber.ensure_loaded(notify=app.notify)
        except Exception:
            log.exception("live typing: model load failed — disabled for this take")
            return
        while self._active():
            time.sleep(_TICK_SECONDS)
            if not self._active():
                return
            self._flush_pending()
            # Re-fetched every tick: apply_settings may swap the transcriber
            # (backend change) mid-take; a backend without segment timestamps
            # simply ends the live commits.
            preview_segments = getattr(app.transcriber, "preview_segments", None)
            if preview_segments is None:
                log.info("live typing: backend provides no segments — stopping for this take")
                return
            audio = app.recorder.snapshot(start_frame=self.committed_frames)
            duration = len(audio) / SAMPLE_RATE
            if duration < _MIN_AUDIO_SECONDS:
                continue
            if duration > _MAX_WINDOW_SECONDS:
                log.warning(
                    "live typing: no stable segment within %.0fs — stopping live "
                    "commits for this take",
                    _MAX_WINDOW_SECONDS,
                )
                return
            try:
                segments = preview_segments(audio)
            except Exception:
                log.exception("live typing: transcription failed — disabled for this take")
                return
            if segments is None:  # model not loaded / another decode running
                continue
            if not self._active():
                return
            if self.post_preview:
                rolling = _join(self.committed_text, " ".join(t for _e, t in segments))
                if rolling:
                    app.post("preview_text", rolling)
            prev, self._prev = self._prev, segments
            if prev is None:
                continue
            texts, end = stable_prefix(prev, segments, duration - _TAIL_GUARD_SECONDS)
            chunk = sanitize_typed_text(" ".join(texts))
            if not chunk:
                continue
            # Book the commit BEFORE typing: app._process slices the final
            # audio at committed_frames, so the offset must already cover every
            # chunk that is about to be handed to the keyboard.
            self.committed_frames += int(end * SAMPLE_RATE)
            self.committed_text = _join(self.committed_text, chunk)
            self._prev = None  # the offset moved — the next pass isn't comparable
            self.pending = _join(self.pending, chunk)
            self._flush_pending()

    def _flush_pending(self) -> None:
        """Type whatever is committed but not yet typed. Leaves the rest in
        `pending` when a held modifier interrupts — retried next tick, and
        app._process picks up any final leftover."""
        if not self.pending:
            return
        text = (" " if self.typed_any else "") + self.pending
        try:
            rest = self.app.injector.type_plain(text)
        except Exception:
            log.exception("live typing: keyboard injection failed — keeping text pending")
            return
        if rest != text:
            self.typed_any = True
        self.pending = rest.lstrip(" ")
