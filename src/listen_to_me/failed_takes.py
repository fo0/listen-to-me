"""The audio of takes whose transcription failed, kept on disk for a retry (#363).

A take that raised in `App._process` before the model handed back any text — a
model that would not load, a missing CUDA library, a crashed backend — used to
cost the recording. Most of those failures are fixed in Settings within
minutes, but the words were said once, and asking for them again is the one
thing a dictation tool must not do. So the audio is kept here, and Settings →
History lists it with a Retry button (wording: `failed_takes_text`).

Apart from history.json on purpose — and not in the config folder at all, see
`config.failed_takes_dir` for why: every reader of `TranscriptHistory.entries()`
(tray and floating-icon menus, Home's recent rows, `latest()`, Export, Copy
all, add()'s duplicate check) assumes an entry has text, and an older build
drops text-less entries and would then rewrite the file without them.

This is audio of what the user said, so it is bounded on every side: only
while the history is on (the caller checks — history off promises nothing is
stored); `RETENTION_DAYS` days, purged at startup, hourly while the app runs,
on every write and every listing; at most `max_takes` and `max_bytes` of audio
(an hour-long take is 115 MB); a directory only this user can reach, files
0600. A file that cannot be *read* right now is skipped, never deleted — only
corruption drops a take.

One take is ``<id>.wav`` (16 kHz mono 16-bit PCM, `failed_takes_wav`) plus
``<id>.json`` (its metadata), id a uuid4 hex. The json is written last, so it
commits the take. The directory is hand-editable: only names matching `_TAKE_FILE` count, an id
comes from a file name (never a json value) and is re-validated before a path
is built from it, and every json field is normalized before it reaches a
QLabel. Qt-free and numpy-optional, so the self-test runs it on the CI runner,
which has no numpy.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import uuid
from pathlib import Path

from . import failed_takes_wav as wav
from .audio import SAMPLE_RATE
from .choices import SOURCE_MIC, known_source
from .config import atomic_write_json, sweep_stale_tmp
from .failed_takes_text import RETENTION_DAYS

log = logging.getLogger(__name__)

MAX_TAKES = 50
MAX_BYTES = 1 << 30  # a broken model for a week of fifteen-minute meetings

# fullmatch, never `^…$`: `$` also matches before a trailing newline.
_TAKE_FILE = re.compile(r"([0-9a-f]{32})\.(wav|json)")
_TAKE_ID = re.compile(r"[0-9a-f]{32}")
_ERROR_CHARS = 500
_JSON_MAX_BYTES = 64 * 1024  # a take's metadata is ~200 bytes
_ORPHAN_AGE_S = 3600.0  # the gate config.sweep_stale_tmp uses
_CLOCK_SKEW_S = 86400.0


def valid_id(take_id) -> str | None:
    """`take_id` when it is an id this store could have made, else None."""
    return take_id if isinstance(take_id, str) and _TAKE_ID.fullmatch(take_id) else None


def _own_dir(path: Path, *, create: bool) -> bool:
    """Make sure `path` is a directory only this user can reach; False when it
    does not exist and `create` is off.

    Mirrors `theme._own_dir`, which cannot be imported without Qt:
    ``mkdir(exist_ok=True)`` accepts a directory — or a symlink to one —
    another account created first. Checked on every access, not only on
    creation, so a directory swapped for a symlink later is refused as well.
    POSIX only: Windows keeps the restriction in the profile's ACL.
    """
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    elif not path.exists() and not path.is_symlink():
        return False
    if os.name != "posix":
        return True
    if path.is_symlink():  # before stat/chmod, which both follow symlinks
        raise OSError(f"{path} is a symlink — refusing to keep recordings there")
    owner = os.stat(path).st_uid
    if owner != os.getuid():
        raise OSError(f"{path} is owned by uid {owner}, not {os.getuid()}")
    os.chmod(path, 0o700)
    return True


def _clock(value, fallback: float, now: float) -> float:
    """A stored take time as an epoch float. Unusable — or further ahead than
    a clock correction explains — reads as `fallback`: a hand-edited time a
    year ahead would keep the audio a year past its promised week."""
    try:
        when = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if not math.isfinite(when) or when <= 0 or when > now + _CLOCK_SKEW_S:
        return fallback
    return when


def _seconds(value) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return seconds if math.isfinite(seconds) and 0 <= seconds <= wav.MAX_SECONDS else 0.0


def _error_text(value) -> str:
    text = value.strip() if isinstance(value, str) else ("" if value is None else str(value))
    return text if len(text) <= _ERROR_CHARS else text[:_ERROR_CHARS].rstrip() + "…"


class FailedTakes:
    """The store. Thread-safe: the recording worker keeps a take (and a retry
    updates or removes one) while the Settings window lists them."""

    def __init__(
        self,
        directory: Path,
        retention_days: float = RETENTION_DAYS,
        max_takes: int = MAX_TAKES,
        max_bytes: int = MAX_BYTES,
    ):
        self.directory = Path(directory)
        self.retention_s = max(1.0, float(retention_days) * 86400.0)
        self.max_takes = max(1, int(max_takes))
        self.max_bytes = max(1, int(max_bytes))
        self._lock = threading.Lock()
        # The take a retry is transcribing right now (see `pin`), or None.
        self._pinned: str | None = None

    def pin(self, take_id) -> dict | None:
        """Look the take up and keep it from the purge and the caps until
        `unpin` (`App._retry_take`); its entry, or None when it is not kept.
        A take retried at the end of its week would otherwise expire mid-retry
        (every History listing purges, and so does the hourly purge) and its
        finished transcript be discarded as deleted. Delete… and Clear still
        remove it — the user's word, not the purge's. One step under the lock,
        so no purge runs between lookup and pin."""
        if valid_id(take_id) is None:
            return None
        with self._lock:
            takes, _expired = self._current(time.time())
            entry = next((take for take in takes if take["id"] == take_id), None)
            if entry is not None:
                self._pinned = take_id
        return None if entry is None else self._listed(entry)

    def unpin(self) -> None:
        """The retry is over: the purge may take the take once it expired."""
        with self._lock:
            self._pinned = None

    def keep(self, audio, source, error, timestamp: float | None = None) -> dict | None:
        """Store a failed take; its listed entry, or None (logged) when it
        could not be written — the caller's notification then says so."""
        take_id = uuid.uuid4().hex
        now = time.time()
        tmp: Path | None = None
        try:
            pcm = wav.pcm16(audio)
            if not pcm:
                raise ValueError("the recording holds no audio")
            entry = {
                "id": take_id,
                "time": _clock(timestamp, now, now),
                "source": known_source(source) or SOURCE_MIC,
                "seconds": round(len(pcm) / 2 / SAMPLE_RATE, 2),
                "error": _error_text(error),
            }
            _own_dir(self.directory, create=True)
            # Written outside the lock — a long take is tens of megabytes, and
            # the History page lists under that lock on the main thread. The
            # temp name never matches _TAKE_FILE.
            tmp = wav.write_temp(self.directory, f"{take_id}.", pcm)
            with self._lock:
                takes, _expired = self._current(now)
                # Room for this one, the oldest first. The new take itself is
                # always kept, however large: it is the one just lost — and
                # so is a pinned one, which a retry is reading right now.
                sizes = {take["id"]: self._size(take["id"]) for take in takes}
                total, count = len(pcm) + sum(sizes.values()), len(takes)
                for old in sorted(takes, key=lambda take: take["time"]):
                    if count < self.max_takes and total <= self.max_bytes:
                        break
                    if old["id"] == self._pinned:
                        continue
                    total -= sizes[old["id"]]
                    count -= 1
                    self._delete(old["id"])
                os.replace(tmp, self._path(take_id, "wav"))
                tmp = None
                try:
                    atomic_write_json(self._path(take_id, "json"), entry)
                except Exception:
                    self._delete(take_id)  # a wav nothing commits is no take
                    raise
        except Exception:
            log.exception("could not keep the recording of a failed transcription")
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
            return None
        log.info("kept the %.1f s recording of a failed take as %s", entry["seconds"], take_id)
        return self._listed(entry)

    def entries(self) -> list[dict]:
        """Every kept take, newest first, each with its "expires" epoch;
        expired ones are purged on the way. Raises OSError for a directory
        `_own_dir` refuses — the History page logs that and lists none."""
        with self._lock:
            takes, _expired = self._current(time.time())
        return [self._listed(take) for take in sorted(takes, key=lambda t: t["time"], reverse=True)]

    def count(self) -> int:
        return len(self.entries())

    def exists(self, take_id) -> bool:
        """Whether the take is still kept — asked by a retry right before it
        stores the transcript, since Delete… or "Clear history…" may have run
        while the audio was being transcribed. True when that cannot be told
        (a file there but not readable right now): a transcript of a recording
        that does exist must not be thrown away over a lock."""
        take_id = valid_id(take_id)
        if take_id is None:
            return False
        try:
            return self._path(take_id, "json").exists() and self._path(take_id, "wav").exists()
        except OSError:
            return True

    def load_audio(self, take_id):
        """The take's audio as float32 samples at `SAMPLE_RATE`. ValueError
        for an id this store could not have made — it never becomes a path."""
        take_id = valid_id(take_id)
        if take_id is None:
            raise ValueError("not the id of a kept recording")
        path = self._path(take_id, "wav")
        # No lock: the file is only ever replaced or unlinked, never rewritten
        # in place, and an hour of audio is a long read to hold listings up for.
        if not _own_dir(self.directory, create=False):
            raise FileNotFoundError(f"{path} does not exist")
        return wav.read(path)

    def update_error(self, take_id, error) -> bool:
        """Replace a take's error after a retry that failed as well. False —
        logged where it is a failure — when the take is gone or unwritable."""
        take_id = valid_id(take_id)
        if take_id is None:
            return False
        with self._lock:
            try:
                if not _own_dir(self.directory, create=False):
                    return False
                if not self._path(take_id, "wav").exists():
                    return False
                entry = self._read(take_id, time.time())
                if entry is None:
                    return False
                entry["error"] = _error_text(error)
                atomic_write_json(self._path(take_id, "json"), entry)
            except Exception:
                log.exception("could not update the kept recording %s", take_id)
                return False
        return True

    def remove(self, take_id) -> bool:
        """Delete one take; False when it was not there or the id is not one
        this store makes. Raises OSError when a file of it could not be
        deleted — the user asked for the audio to be gone, and it is not."""
        if valid_id(take_id) is None:
            log.warning("refusing to delete a kept recording by the id %.80r", take_id)
            return False
        with self._lock:
            if not _own_dir(self.directory, create=False):
                return False
            return self._delete(take_id, strict=True)

    def clear(self) -> int:
        """Delete every take; how many files went. Raises OSError, after
        trying every file, when one could not be deleted."""
        removed, problem = 0, None
        with self._lock:
            if not _own_dir(self.directory, create=False):
                return 0
            for path in self.directory.iterdir():
                if not _TAKE_FILE.fullmatch(path.name):
                    continue
                try:
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    log.warning("could not delete %s", path, exc_info=True)
                    problem = problem or exc
        if problem is not None:
            raise problem
        return removed

    def purge_expired(self, now: float | None = None) -> int:
        """Drop expired and unreadable takes, orphaned wavs and stale temp
        files; how many takes went."""
        with self._lock:
            _takes, removed = self._current(time.time() if now is None else float(now))
        return removed

    # -------------------------------------------- internal (lock held by caller)

    def _path(self, take_id: str, suffix: str) -> Path:
        return self.directory / f"{take_id}.{suffix}"

    def _size(self, take_id: str) -> int:
        try:
            return self._path(take_id, "wav").stat().st_size
        except OSError:
            return 0

    def _listed(self, entry: dict) -> dict:
        return dict(entry, expires=entry["time"] + self.retention_s)

    def _current(self, now: float) -> tuple[list[dict], int]:
        """The live takes, after removing the expired and broken ones."""
        if not _own_dir(self.directory, create=False):
            return [], 0
        names: dict[str, set[str]] = {"wav": set(), "json": set()}
        for path in self.directory.iterdir():
            match = _TAKE_FILE.fullmatch(path.name)
            # Anything else is not ours, and left alone — a directory under a
            # take's name included: it is no take file, and counting it would
            # keep its wav unpurgeable (skipped as unreadable on every round).
            if match is not None and not path.is_dir():
                names[match.group(2)].add(match.group(1))
        takes, removed = [], 0
        for take_id in names["json"]:
            pinned = take_id == self._pinned
            try:
                entry = self._read(take_id, now) if take_id in names["wav"] else None
            except OSError:
                # Not corruption: a virus scanner, an indexer or a backup
                # holding the file (typically at logon, when the startup
                # purge runs). Skipped this round — deleting it would destroy
                # the only copy over a lock that is gone a second later. But
                # one that is never readable (an ACL that denies it) still
                # ages out, by its files' own time, or it would be kept past
                # its 7 days, unlisted, for good.
                if not pinned and self._aged_out(take_id, now):
                    log.warning("dropping the kept recording %s — unreadable, expired", take_id)
                    removed += int(self._delete(take_id))
                else:
                    log.warning("skipping the kept recording %s for now", take_id, exc_info=True)
                continue
            if entry is not None and (pinned or entry["time"] + self.retention_s > now):
                takes.append(entry)
                continue
            if entry is None:
                log.warning("dropping the kept recording %s — incomplete or unreadable", take_id)
            removed += int(self._delete(take_id))
        for take_id in names["wav"] - names["json"]:
            # Age-gated like a temp file: another instance may be mid-write.
            wav = self._path(take_id, "wav")
            try:
                if wav.stat().st_mtime < now - _ORPHAN_AGE_S:
                    wav.unlink()
            except OSError:
                log.debug("could not remove the orphaned %s", wav, exc_info=True)
        sweep_stale_tmp(self.directory)
        return takes, removed

    def _aged_out(self, take_id: str, now: float) -> bool:
        """Whether a take whose metadata cannot be read is past its retention
        by the time of its wav (written with the take), else of its json.
        False when neither can be told — nothing is deleted on a guess."""
        for suffix in ("wav", "json"):
            try:
                return self._path(take_id, suffix).stat().st_mtime + self.retention_s <= now
            except OSError:
                continue
        return False

    def _read(self, take_id: str, now: float) -> dict | None:
        """One take's metadata, normalized; None when it is corrupt. An
        OSError is passed on: a file that cannot be opened right now is not
        a broken one (see `_current`)."""
        path = self._path(take_id, "json")
        if path.is_symlink() or path.stat().st_size > _JSON_MAX_BYTES:
            return None
        with open(path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            # ValueError covers UnicodeDecodeError and JSONDecodeError; a
            # hand-made "[[[[…" overflows the decoder's recursion instead.
            except (ValueError, RecursionError):
                return None
        mtime = min(path.stat().st_mtime, now)
        if not isinstance(data, dict):
            return None
        return {
            "id": take_id,  # the file name's, never the json's own "id"
            "time": _clock(data.get("time"), mtime, now),
            "source": known_source(data.get("source")) or SOURCE_MIC,
            "seconds": _seconds(data.get("seconds")),
            "error": _error_text(data.get("error")),
        }

    def _delete(self, take_id: str, *, strict: bool = False) -> bool:
        """Remove a take's files, json first — it is what commits the take."""
        removed, problem = False, None
        for suffix in ("json", "wav"):
            path = self._path(take_id, suffix)
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("could not delete %s", path, exc_info=True)
                problem = problem or exc
        if problem is not None and strict:
            raise problem
        return removed


def start_purge(store: FailedTakes) -> None:
    """Purge expired takes once, off the startup path. Never raises: a store
    that cannot be cleaned up must not cost the app its start."""

    def purge() -> None:
        try:
            removed = store.purge_expired()
        except Exception:
            log.exception("could not purge the expired recordings in %s", store.directory)
            return
        if removed:
            log.info("purged %d expired or unreadable failed recording(s)", removed)

    try:
        threading.Thread(target=purge, name="failed-takes-purge", daemon=True).start()
    except Exception:
        log.exception("could not start the purge of expired failed recordings")
