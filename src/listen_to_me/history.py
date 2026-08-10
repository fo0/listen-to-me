"""Persistent history of transcribed text.

Keeps the most recent transcripts in a small JSON file next to the config so a
transcript can be recovered from Settings → History if a paste is lost. Only the
text is stored — never the audio. Thread-safe: the recording worker appends
while the settings window reads/clears on the main thread.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from .config import atomic_write_json

log = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 200


def filter_entries(entries: list[dict], query: str) -> list[dict]:
    """The entries whose text contains every whitespace-separated term of
    `query`, case-insensitively; an empty query returns `entries` unchanged.

    Kept here (Qt-free) rather than in the History page so the matching rule is
    testable headlessly. AND over terms, order-independent: a user looking for
    a past dictation remembers a few words from it, not the phrase verbatim.
    casefold(), not lower(), so a German "ß"/"SS" or "Ä"/"ä" still matches."""
    terms = [term.casefold() for term in str(query or "").split()]
    if not terms:
        return list(entries)
    matched = []
    for entry in entries:
        text = str(entry.get("text", "")).casefold()
        if all(term in text for term in terms):
            matched.append(entry)
    return matched


def _same_time(stored, wanted) -> bool:
    """Whether two history timestamps denote the same entry.

    Compared numerically with a sub-millisecond tolerance instead of `==` on
    the raw values: the stored one came back through a JSON round-trip and an
    older build (or a hand-edit) may have written it as an int or a string, so
    a strict comparison would refuse to match the very row the user clicked."""
    try:
        return abs(float(stored) - float(wanted)) < 1e-6
    except (TypeError, ValueError):
        return False


class TranscriptHistory:
    def __init__(self, path: Path, max_entries: int = DEFAULT_MAX_ENTRIES):
        self.path = Path(path)
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.Lock()

    def add(self, text: str, timestamp: float | None = None) -> None:
        """Append a transcript. Blank text and exact consecutive duplicates
        (e.g. the same take retried) are ignored."""
        text = (text or "").strip()
        if not text:
            return
        entry = {"time": time.time() if timestamp is None else float(timestamp), "text": text}
        with self._lock:
            entries = self._load()
            if entries and entries[-1].get("text") == text:
                return
            entries.append(entry)
            if len(entries) > self.max_entries:
                entries = entries[-self.max_entries :]
            self._save(entries)

    def entries(self) -> list[dict]:
        """All stored transcripts, newest first."""
        with self._lock:
            return list(reversed(self._load()))

    def latest(self) -> str:
        """The text of the most recent transcript, or "" when there is none.

        Read from the file rather than a cached value: the recording worker
        appends here while the main thread (tray → "Copy last transcript")
        reads, and the file is the single source both already agree on."""
        with self._lock:
            entries = self._load()
        return entries[-1]["text"] if entries else ""

    def remove(self, text: str, timestamp: float | None = None) -> bool:
        """Delete a single stored transcript; True when one was removed.

        "Clear history" used to be the only way out of the store, so a single
        dictation that must not stay on disk (a password read aloud, a name,
        a mis-heard sentence) cost every other transcript with it. Matching is
        on the entry's own values rather than an index: the History page hands
        back the row it rendered, while the recording worker may have appended
        or trimmed entries in between — an index would then delete the wrong
        transcript, which is the one mistake this must never make.

        The newest match wins when the same text was dictated twice at the
        same second: it is the row nearest the top of the list the user just
        clicked in.
        """
        text = str(text or "")
        with self._lock:
            entries = self._load()
            for index in range(len(entries) - 1, -1, -1):
                entry = entries[index]
                if entry.get("text") != text:
                    continue
                if timestamp is not None and not _same_time(entry.get("time"), timestamp):
                    continue
                del entries[index]
                self._save(entries)
                return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._save([])

    # -------------------------------------------- internal (lock held by caller)

    def _load(self) -> list[dict]:
        """Stored entries, normalized. The file is untrusted input (hand-edited,
        truncated, written by an older build), and its values are handed
        straight to QLabel by the History/Home renderers — a non-string "text"
        (e.g. a number) would raise there. Keeping only entries with a
        non-empty string keeps every consumer, including add()'s duplicate
        check, on a known type."""
        try:
            if self.path.exists():
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    return [
                        e
                        for e in data
                        if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"]
                    ]
        except Exception:
            log.exception("could not read transcript history %s", self.path)
        return []

    def _save(self, entries: list[dict]) -> None:
        try:
            atomic_write_json(self.path, entries)
        except Exception:
            log.exception("could not write transcript history %s", self.path)
