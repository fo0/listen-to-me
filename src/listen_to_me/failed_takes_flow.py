"""What the processing worker does with a failed take and with its retry (#363).

`App._process` hands over here at the points a take can fail or a retry ends:
a failure before the model returned text keeps the audio in `FailedTakes` and
says where to retry it (`report_failure`); a retry's transcript goes into the
history at the take's own time, never to the cursor (`finish_retry`); a retry
that finds no speech, produces a recognition error or raises again keeps its
row with the new error (`no_speech`, `implausible_retry`, `retry_failed`) —
unless Delete… or "Clear history…" removed it meanwhile, which discards the
retry's transcript and says so. `purge_when_due` keeps the retention promise
while the app runs.

Functions taking the app rather than App methods, for the reason
`app._take_source` is one: `App._process` and `App._retry_take` are borrowed
unbound by the headless self-test onto stubs that define a handful of
attributes — and no stub written before this feature has a `failed_takes` at
all. Qt-free; everything that reaches the user goes through `app.notify`.
"""

from __future__ import annotations

import logging
import time

from .failed_takes import start_purge
from .failed_takes_text import (
    KEPT_NOTE,
    NOT_KEPT_NOTE,
    RETRY_DELETED,
    RETRY_DONE,
    RETRY_NO_SPEECH,
    RETRY_NO_SPEECH_ERROR,
    STAYS_NOTE,
    with_note,
)
from .transcriber import is_cuda_library_error

log = logging.getLogger(__name__)

PURGE_INTERVAL_S = 3600.0  # how often a running app purges expired takes

# A GPU/CUDA library failure the CPU fallback could not recover from: an
# actionable message, not the raw DLL name. Shared by a take and its retry;
# moved here from `App._process` word for word.
_CUDA_MESSAGE = (
    "GPU transcription needs the NVIDIA CUDA 12 libraries. "
    "Set Device = CPU in Settings → Engine, or see the tray "
    "menu → Help / Troubleshooting."
)


def _error_of(exc: BaseException) -> str:
    """An exception as the line a failed row shows — never empty."""
    return str(exc) or type(exc).__name__


def report_failure(app, exc: BaseException, audio, source: str, transcribed: bool) -> None:
    """Notify about a take whose processing raised, keeping its audio for a
    retry when the failure cost the words (#363).

    Only before the model returned text: a failure after that (inserting,
    live typing) left the text in the history already, and keeping the audio
    too would offer to transcribe it a second time. Only with the history on:
    off promises that nothing is stored, and audio least of all.
    """
    message = _CUDA_MESSAGE if is_cuda_library_error(exc) else f"Transcription failed: {exc}"
    store = getattr(app, "failed_takes", None)
    if not transcribed and audio is not None and store is not None and app.cfg["history_enabled"]:
        try:
            kept = store.keep(audio, source, _error_of(exc)) is not None
        except Exception:  # keep() logs and answers None; this is the last net
            log.exception("could not keep the recording of a failed transcription")
            kept = False
        message = with_note(message, KEPT_NOTE if kept else NOT_KEPT_NOTE)
    app.notify(message, force=True)


def _drop_take(app, take_id: str) -> None:
    """Delete a take whose retry delivered its transcript. A delete that fails
    is logged — the row then stays, and the transcript is safe either way."""
    try:
        app.failed_takes.remove(take_id)
    except Exception:
        log.exception("could not delete the kept recording %s after its retry", take_id)


def _keep_row(app, retry: dict, error: str, message: str) -> None:
    """A retry that did not deliver: the take stays, with `error` on its row —
    and the notification says it stays only when that is true. Delete… or
    "Clear history…" may have removed it while it was being transcribed (an
    update_error that fails for another reason leaves it there, hence the
    second question)."""
    store = app.failed_takes
    if store.update_error(retry["id"], error) or store.exists(retry["id"]):
        app.notify(with_note(message, STAYS_NOTE), force=True)
    else:
        app.notify(RETRY_DELETED, force=True)


def _store(app, retry: dict, text: str) -> str:
    """Put a retried take's transcript into the history at the take's own
    time. "stored" — and only then is the kept audio deleted; "failed" —
    nothing was written (logged), the audio stays the one durable copy;
    "deleted" — the take was deleted while it was being retried, and its
    transcript is not stored (or taken back out).

    The write is strict: the lenient default only logs a failed write, which
    here would delete the only copy of the words after a write that never
    happened. The take is asked for twice, around the write, so a Delete… or
    "Clear history…" (which removes the take first) can never land between
    the two and leave the transcript of a deleted recording in the history.
    """
    store, take_id = app.failed_takes, retry["id"]
    if not store.exists(take_id):
        return "deleted"
    try:
        added = app.history.add(text, timestamp=retry["time"], strict=True)
    except Exception:
        log.exception("could not add the retried transcript to the history")
        return "failed"
    if not store.exists(take_id):
        if added:
            try:
                app.history.remove(text.strip(), retry["time"])
            except Exception:
                log.exception("could not take back the transcript of a deleted recording")
        return "deleted"
    _drop_take(app, take_id)
    return "stored"


def finish_retry(app, retry: dict, text: str) -> None:
    """Deliver a retried take's transcript — never to the cursor: the user is
    in the Settings window, which is where the click came from.

    Into the history at the take's own time while the history is on; a
    history that cannot be written keeps the take (the audio is the durable
    copy) and puts the text on the clipboard on top. With the history off it
    keeps its promise to store nothing, and the transcript the user explicitly
    asked for goes on the clipboard instead, whatever "clipboard_copy" says
    (that setting is about insertions, and this is none) — the take is then
    deleted, unless the clipboard could not take it either.
    """
    if app.cfg["history_enabled"]:
        outcome = _store(app, retry, text)
        if outcome == "stored":
            app.notify(RETRY_DONE, force=True)
        elif outcome == "deleted":
            app.notify(RETRY_DELETED, force=True)
        else:
            on_clipboard = app.injector.copy_to_clipboard(text)
            _keep_row(
                app,
                retry,
                "Transcribed, but the history could not be written — see the log file.",
                "Retry worked, but the transcript could not be saved to the history"
                + (" — it is on the clipboard" if on_clipboard else " or put on the clipboard"),
            )
        return
    if not app.failed_takes.exists(retry["id"]):
        app.notify(RETRY_DELETED, force=True)
        return
    if app.injector.copy_to_clipboard(text):
        _drop_take(app, retry["id"])
        preview = text if len(text) <= 60 else text[:60].rstrip() + "…"
        app.notify(
            "Retry worked — the history is off, so the transcript is on the clipboard: "
            f"{preview}",
            force=True,
        )
        return
    _keep_row(
        app,
        retry,
        "Transcribed, but the history is off and the clipboard could not be written.",
        "Retry worked, but the history is off and the clipboard could not be written",
    )


def no_speech(app, audio, source: str, verdict: str | None, retry: dict | None) -> None:
    """Report a take that produced no text. A fresh take gets
    `_notify_no_speech`'s device diagnosis; a retried one keeps its row with
    that as its error — the audio is still the only copy, and a model or
    language switched afterwards may hear what this one did not."""
    if retry is None:
        app._notify_no_speech(audio, source, verdict)
        return
    _keep_row(app, retry, RETRY_NO_SPEECH_ERROR, RETRY_NO_SPEECH)


def implausible_retry(app, retry: dict, reason: str, text: str) -> None:
    """A retried transcript `implausible_reason` rejects. Stored in the history
    like every such transcript (never inserted), so the take has served its
    purpose; when it could not be stored, the take stays for another try."""
    if app.cfg["history_enabled"]:
        outcome = _store(app, retry, text)
        if outcome == "stored":
            app.notify(
                "Retry done, but the transcript looks like a recognition error "
                f"({reason}). It is in Settings → History.",
                force=True,
            )
            return
        if outcome == "deleted":
            app.notify(RETRY_DELETED, force=True)
            return
    note = f"The retry produced what looks like a recognition error ({reason})"
    _keep_row(app, retry, note + ".", note)


def retry_failed(app, retry: dict, exc: BaseException) -> None:
    """A retry that raised again — the take stays, with the new error. One
    whose audio was deleted under it (Delete…, "Clear history…") raises too,
    and is told apart by `_keep_row`."""
    reason = _CUDA_MESSAGE if is_cuda_library_error(exc) else f"Retry failed: {_error_of(exc)}"
    _keep_row(app, retry, _error_of(exc), reason)


def purge_when_due(app, now: float | None = None) -> None:
    """Start the hourly purge of expired takes once it is due — ridden by
    `App._poll` on the main thread every 100 ms, so all it costs there is a
    clock read; the purge runs on its own thread (`start_purge`).

    The purge at startup alone did not keep "kept for 7 days": a tray app runs
    for weeks, and the listing that purges as well only runs while someone
    looks at the History page. getattr: `App._poll` is borrowed by stubs too.
    """
    store = getattr(app, "failed_takes", None)
    if store is None:
        return
    now = time.monotonic() if now is None else now
    if now < getattr(app, "_next_purge", 0.0):
        return
    app._next_purge = now + PURGE_INTERVAL_S
    start_purge(store)


def end_retry(app) -> None:
    """The worker's "done": no take is being retried any more. Clears
    `retrying_take` (before the state change, whose History re-render reads
    it) and unpins the take, so the purge may take it once it has expired
    (`FailedTakes.pin`). getattr: `App._handle` is borrowed by stubs too."""
    app.retrying_take = None
    store = getattr(app, "failed_takes", None)
    if store is not None:
        store.unpin()


def refresh_history_page(app) -> None:
    """Have an open settings window re-render its History page (or mark it
    stale) — for a retry refused before any state change, whose button
    already reads "Retrying…"."""
    window = getattr(app, "_settings_window", None)
    if window is None:
        return
    try:
        window.history_changed()
    except RuntimeError:
        app._settings_window = None  # deleted by _open_settings, see _set_state
    except Exception:
        log.debug("could not refresh the History page", exc_info=True)
