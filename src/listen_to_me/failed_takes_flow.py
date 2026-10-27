"""What the processing worker does with a failed take and with its retry (#363).

`App._process` hands over here at the points a take can fail or a retry ends:
a failure before the model returned text keeps the audio in `FailedTakes` and
says where to retry it (`report_failure`); a retry's transcript goes into the
history at the take's own time, never to the cursor (`finish_retry`); a retry
that finds no speech, produces a recognition error or raises again keeps its
row with the new error (`no_speech`, `implausible_retry`, `retry_failed`).

Functions taking the app rather than App methods, for the reason
`app._take_source` is one: `App._process` and `App._retry_take` are borrowed
unbound by the headless self-test onto stubs that define a handful of
attributes — and no stub written before this feature has a `failed_takes` at
all. Qt-free; everything that reaches the user goes through `app.notify`.
"""

from __future__ import annotations

import logging

from .failed_takes_text import (
    KEPT_NOTE,
    NOT_KEPT_NOTE,
    RETRY_DONE,
    RETRY_NO_SPEECH,
    RETRY_NO_SPEECH_ERROR,
    STAYS_NOTE,
    with_note,
)
from .transcriber import is_cuda_library_error

log = logging.getLogger(__name__)

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


def history_stamp(retry: dict | None) -> dict:
    """The keywords a history add() of this take passes: a retried take's own
    time, so it lands where it was recorded. Nothing for a fresh take, whose
    add() call stays exactly what it always was — the self-test's stub
    histories take no timestamp."""
    return {} if retry is None else {"timestamp": retry["time"]}


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


def finish_retry(app, retry: dict, text: str) -> None:
    """Deliver a retried take's transcript — never to the cursor: the user is
    in the Settings window, which is where the click came from.

    Into the history at the take's own time while the history is on. Off,
    the history keeps its promise to store nothing, and the transcript the
    user explicitly asked for goes on the clipboard instead, whatever
    "clipboard_copy" says (that setting is about insertions, and this is
    none). The kept audio is deleted only once the text is somewhere: if
    neither the history nor the clipboard could take it, the row stays.
    """
    take_id = retry["id"]
    if app.cfg["history_enabled"]:
        try:
            app.history.add(text, **history_stamp(retry))
        except Exception:
            log.exception("could not add the retried transcript to the history")
            where = "it could not be saved to the history"
        else:
            _drop_take(app, take_id)
            app.notify(RETRY_DONE, force=True)
            return
    else:
        where = "the history is off"
    if app.injector.copy_to_clipboard(text):
        _drop_take(app, take_id)
        preview = text if len(text) <= 60 else text[:60].rstrip() + "…"
        app.notify(
            f"Retry worked — {where}, so the transcript is on the clipboard: {preview}",
            force=True,
        )
        return
    app.failed_takes.update_error(
        take_id, f"Transcribed, but {where} and the clipboard could not be written."
    )
    app.notify(
        with_note(f"Retry worked, but {where} and the clipboard could not be written", STAYS_NOTE),
        force=True,
    )


def no_speech(app, audio, source: str, verdict: str | None, retry: dict | None) -> None:
    """Report a take that produced no text. A fresh take gets
    `_notify_no_speech`'s device diagnosis; a retried one keeps its row with
    that as its error — the audio is still the only copy, and a model or
    language switched afterwards may hear what this one did not."""
    if retry is None:
        app._notify_no_speech(audio, source, verdict)
        return
    app.failed_takes.update_error(retry["id"], RETRY_NO_SPEECH_ERROR)
    app.notify(RETRY_NO_SPEECH, force=True)


def implausible_retry(app, retry: dict, reason: str, kept: bool) -> None:
    """A retried transcript `implausible_reason` rejects. In the history like
    every such transcript (never inserted), so the take has served its
    purpose; when nothing could be stored, it stays for another try."""
    if kept:
        _drop_take(app, retry["id"])
        app.notify(
            "Retry done, but the transcript looks like a recognition error "
            f"({reason}). It is in Settings → History.",
            force=True,
        )
        return
    note = f"The retry produced what looks like a recognition error ({reason})"
    app.failed_takes.update_error(retry["id"], note + ".")
    app.notify(with_note(note, STAYS_NOTE), force=True)


def retry_failed(app, retry: dict, exc: BaseException) -> None:
    """A retry that raised again: the take stays, with the new error."""
    app.failed_takes.update_error(retry["id"], _error_of(exc))
    reason = _CUDA_MESSAGE if is_cuda_library_error(exc) else f"Retry failed: {_error_of(exc)}"
    app.notify(with_note(reason, STAYS_NOTE), force=True)


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
