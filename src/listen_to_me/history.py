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

    def clear(self) -> None:
        with self._lock:
            self._save([])

    # -------------------------------------------- internal (lock held by caller)

    def _load(self) -> list[dict]:
        try:
            if self.path.exists():
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    return [e for e in data if isinstance(e, dict) and e.get("text")]
        except Exception:
            log.exception("could not read transcript history %s", self.path)
        return []

    def _save(self, entries: list[dict]) -> None:
        try:
            atomic_write_json(self.path, entries)
        except Exception:
            log.exception("could not write transcript history %s", self.path)
