"""How a failed take kept for a retry is put into words (#363).

`failed_takes` stores the audio; this module words it — the notifications
the worker (`failed_takes_flow`) and `App._retry_take` send (`KEPT_NOTE`,
`with_note`, the `RETRY_*` sentences), the hint line under a failed row on the History page
(`describe`), the question its Delete… asks (`delete_prompt`) — and merges the
failed takes into the transcript list that page renders (`merge_newest_first`).

Qt-free and stdlib-only, so every sentence is checked headless (selftest
"failed takes are kept for a retry").
"""

from __future__ import annotations

import math
import time

from .choices import source_label

RETENTION_DAYS = 7  # how long `failed_takes.FailedTakes` keeps a take by default

# Every note names the page the take is on — which is where
# `app.notification_target` sends a click on the notification.
KEPT_NOTE = f"The recording is kept for {RETENTION_DAYS} days — retry it in Settings → History."
NOT_KEPT_NOTE = "The recording could not be kept — see the log file."
STAYS_NOTE = "The recording stays in Settings → History."
RETRY_DONE = "Retry worked — the transcript is in Settings → History."
RETRY_BUSY = "Finish the current recording first, then retry it."
RETRY_GONE = "That recording is no longer kept — it expired or was deleted."
RETRY_UNREADABLE = "Could not read the recordings kept for a retry — see the log file."
RETRY_NO_SPEECH_ERROR = "No speech was recognized when it was retried."
RETRY_NO_SPEECH = "The retry recognized no speech in the recording."
# Delete… or "Clear history…" removed the take while it was being retried.
RETRY_DELETED = (
    "The recording was deleted while it was being retried, so nothing of it was stored."
)
# A retry that failed after its take's retention ran out: the pin kept it for
# the retry only, and the next listing purges it.
EXPIRED_NOTE = f"Its {RETENTION_DAYS} days are over, so the recording is deleted now."
# "Don't insert this transcript" during a retry, which never inserts anything.
RETRY_WITHHOLD = "Nothing to hold back — a retried recording is never inserted at the cursor."


def with_note(message: str, note: str) -> str:
    """`message` and `note` as two sentences — an exception text rarely ends
    in a full stop, and one that does must not get a second."""
    message = str(message or "").rstrip()
    if message and message[-1] not in ".!?…":
        message += "."
    return f"{message} {note}" if message else note


def format_length(seconds) -> str:
    """``m:ss`` (``h:mm:ss`` past the hour). `tray.format_duration` says the
    same, but importing it would pull Qt into a module the self-test reads
    headless."""
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError, OverflowError):
        total = 0
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _local(when, fmt: str) -> str:
    """`when` (epoch) as local time, or "" — a value from a hand-editable
    file must cost the stamp, never the row."""
    try:
        return time.strftime(fmt, time.localtime(float(when)))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _what(entry: dict) -> str:
    source = source_label(entry.get("source")).capitalize()
    return f"{source} · {format_length(entry.get('seconds'))}"


def describe(entry: dict) -> str:
    """The hint line under a failed row: "Microphone · 0:42 · kept until 2026-11-03".

    The date is the one thing on the row that is a deadline — after it the
    recording is purged and there is nothing left to retry."""
    until = _local(entry.get("expires"), "%Y-%m-%d")
    return f"{_what(entry)} · kept until {until}" if until else _what(entry)


def delete_prompt(entry: dict) -> str:
    """The question Delete… on a failed row asks. It names what is lost: the
    audio is the only copy of what was said, and no transcript of it exists."""
    what = _what(entry)
    stamp = _local(entry.get("time"), "%Y-%m-%d %H:%M")
    if stamp:
        what += f", recorded {stamp}"
    return (
        f"Delete this failed recording?\n\n{what}\n\n"
        "Its audio is deleted, so it can no longer be retried. This cannot be undone."
    )


def _when(entry: dict) -> float:
    try:
        value = float(entry.get("time"))
    except (TypeError, ValueError, OverflowError):
        return -math.inf
    return value if math.isfinite(value) else -math.inf


def merge_newest_first(transcripts: list[dict], failed: list[dict]) -> list[dict]:
    """The History page's one list: the `failed` takes merged into
    `transcripts` (newest first, as `TranscriptHistory.entries()` returns it).

    A merge rather than one sort over both: the transcripts keep exactly the
    order the store hands them over in, so a hand-edited or out-of-range
    timestamp — which a sort would move — changes nothing about the rows the
    page has always shown. A failed take goes in front of the first
    transcript that is older than it.
    """
    pending = sorted(failed, key=_when, reverse=True)
    merged: list[dict] = []
    index = 0
    for entry in transcripts:
        stamp = _when(entry)
        while index < len(pending) and _when(pending[index]) >= stamp:
            merged.append(pending[index])
            index += 1
        merged.append(entry)
    merged.extend(pending[index:])
    return merged
