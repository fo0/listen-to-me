"""Persistent history of transcribed text.

Keeps the most recent transcripts in a small JSON file next to the config so a
transcript can be recovered from Settings → History if a paste is lost. Only the
text is stored — never the audio. Thread-safe: the recording worker appends
while the settings window reads/clears on the main thread.

A file that exists but cannot be read is its own answer (`HistoryUnavailable`),
never an empty list: see that class for what the difference costs.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from .config import atomic_write_json

log = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 200


class HistoryUnavailable(RuntimeError):
    """The history file is there but could not be read.

    Raised instead of reporting an empty history, because the two are the
    opposite news: "no transcripts yet" promises the list will fill up, while
    this one means transcripts exist that nobody can see. Every surface that
    lists transcripts already tells the two apart (the tray and floating-icon
    menus, the Home page's recent rows, the History page) — until this
    existed, a file that could not be read reached all four as an empty list
    and they all said the dictations were gone.

    It also stops `add` from writing: a read that failed leaves the stored
    entries unknown, and appending one transcript on top of that assumption
    turns a file that could still be rescued by hand into a file with exactly
    one dictation in it. Same contract as `Config.save()`, which refuses to
    overwrite a config file it could not read. "Clear history…" is the way
    back — it writes without reading, so it repairs a broken file on purpose.
    """


# The characters a search term may consist of to be matched against an entry's
# timestamp as well: digits plus the two separators the stamp renders.
_STAMP_TERM_CHARS = frozenset("0123456789-:")


def _is_stamp_term(term: str) -> bool:
    """Whether `term` reads like a fragment of a ``YYYY-MM-DD HH:MM`` stamp.

    True for "2026-09", "09-05" or "14:" — a term of at least two characters
    that contains a digit and uses nothing but digits, "-" and ":". Everything
    else keeps matching the transcript text only.

    The length and digit guards are the point: a bare "9" is far more likely a
    word from a dictation than a search for September, and matching every term
    against the stamp would quietly return every transcript of that month for
    it. A term that looks like a date can still match the text too — the stamp
    is an additional place to look, never a replacement.
    """
    return (
        len(term) >= 2
        and any(char.isdigit() for char in term)
        and all(char in _STAMP_TERM_CHARS for char in term)
    )


# One search term: a quoted phrase or a whitespace-free word, either of them
# with an optional leading "-". An unclosed quote runs to the end of the query,
# because the History page filters while the user types — a phrase whose
# closing quote is not typed yet must already narrow the list, not empty it.
_QUERY_TOKEN = re.compile(r'(-?)"([^"]*)(?:"|$)|(\S+)')


def _query_terms(query: str) -> list[tuple[str, bool]]:
    """`query` as (term, excluded) pairs, casefolded, in the order written.

    A word stays one term, as it always has. Two additions, both spelled the
    way every search engine spells them:

    - ``"exact phrase"`` is one term, matched as those words in that order.
      AND over single words cannot tell "the release notes" from a dictation
      that merely mentions a release and some notes, and a remembered phrase
      is often exactly what someone looking for an old dictation has.
    - ``-word`` (or ``-"a phrase"``) leaves out every transcript containing
      it — the way to keep fifteen-minute meeting recordings, which mention
      everything, out of a search for a short note.

    A leading "-" only excludes when a letter or digit follows it, so a
    search for "->" or a lone "-" still finds that text; a quoted ``"-5"``
    is the way to search for a word that itself starts with a dash. Empty
    phrases are dropped rather than matched: ``""`` is contained in every
    transcript and would say nothing.
    """
    terms: list[tuple[str, bool]] = []
    for dash, phrase, word in _QUERY_TOKEN.findall(str(query or "")):
        if word:
            excluded = word.startswith("-") and any(char.isalnum() for char in word[1:])
            term = word[1:] if excluded else word
        else:
            excluded = bool(dash)
            # Collapsed like the text it is matched against (see
            # filter_entries), so two spaces typed inside the quotes still
            # find the phrase.
            term = " ".join(phrase.split())
        if term:
            terms.append((term.casefold(), excluded))
    return terms


def filter_entries(entries: list[dict], query: str) -> list[dict]:
    """The entries matching every term of `query`, case-insensitively; an
    empty query returns `entries` unchanged. A term is a word, a quoted
    phrase, or either one with a leading "-" to exclude it (see
    `_query_terms`).

    A term matches when the transcript text contains it — or, for a term that
    reads like a date or clock fragment (see `_is_stamp_term`), when the
    entry's rendered ``YYYY-MM-DD HH:MM`` stamp does. Every row on the History
    page shows that stamp, so "what did I dictate on 2026-09-05" was the one
    obvious question the search field could not answer; the transcript itself
    never repeats its own date. An excluded term is looked for in the same
    places, so ``-2025`` leaves out last year's dictations as well as the
    ones that mention the year. Additive for every query without a quote or a
    leading "-": such a query matches exactly what it matched before.

    Kept here (Qt-free) rather than in the History page so the matching rule is
    testable headlessly. AND over terms, order-independent: a user looking for
    a past dictation remembers a few words from it, not the phrase verbatim.
    casefold(), not lower(), so a German "ß"/"SS" or "Ä"/"ä" still matches."""
    terms = _query_terms(query)
    if not terms:
        return list(entries)
    # Only a phrase can span a line break or a double space in the text, so the
    # whitespace is collapsed only for a query that has one: for single words
    # the result is identical, and a long history is not copied a second time
    # on every keystroke for nothing.
    collapse = any(" " in term for term, _excluded in terms)
    matched = []
    for entry in entries:
        text = str(entry.get("text", ""))
        if collapse:
            text = " ".join(text.split())
        text = text.casefold()
        # Rendered on demand: only a date-like term ever needs the stamp, and
        # entry_timestamp() formats one per call.
        stamp: str | None = None
        hit = True
        for term, excluded in terms:
            found = term in text
            if not found and _is_stamp_term(term):
                if stamp is None:
                    stamp = entry_timestamp(entry)
                found = term in stamp
            if found == excluded:
                hit = False
                break
        if hit:
            matched.append(entry)
    return matched


# How much of a transcript a collapsed History row shows before it is cut.
# Both limits bite, whichever comes first: a recorded meeting is one very long
# paragraph (no line breaks to stop at) and a dictated note is a dozen short
# lines (few characters, a lot of height).
PREVIEW_CHARS = 320
PREVIEW_LINES = 5


def preview_text(
    text: str, max_chars: int = PREVIEW_CHARS, max_lines: int = PREVIEW_LINES
) -> tuple[str, bool]:
    """The opening of `text` for a collapsed History row, and whether it was cut.

    The History page renders every stored transcript in full, which was fine
    while a transcript was a dictated sentence. The second recording source
    (#191) stores what the computer played for up to fifteen minutes, and one
    such entry fills the page many screens deep — scrolling past a single
    meeting to reach yesterday's dictation is the whole list becoming unusable
    because of one row.

    Line breaks are kept, unlike the tray's one-line labels: the History row
    shows the real text, and folding a transcript's paragraphs into one blob
    would misrepresent what Copy hands back. The cut is on whole lines where a
    line limit ends it, so a collapsed row never breaks mid-word for that
    reason; a character cut trims the trailing partial word instead of
    stopping mid-syllable.

    Returns ``(shown, truncated)``. `truncated` is what the caller hangs a
    "Show more" button on, and it is compared on the stripped texts on
    purpose: `TranscriptHistory.add` strips what it stores, but history.json
    is hand-editable, and a transcript whose only excess is trailing blank
    lines would otherwise get a button that reveals nothing but whitespace.

    str(): history.json is untrusted input and the store's own normalization
    is not this function's to assume.
    """
    text = str(text or "")
    lines = text.split("\n")
    cut = "\n".join(lines[:max_lines]) if len(lines) > max_lines else text
    if len(cut) > max_chars:
        cut = cut[:max_chars].rstrip()
        # Drop the word the cut landed inside — but only when there is another
        # word left, or a single 400-character token would collapse to "…".
        head, space, _tail = cut.rpartition(" ")
        if space and head:
            cut = head
    if cut.rstrip() == text.rstrip():
        return text, False
    # "…" with no space, the spelling the tray labels and every other preview
    # in this app already use.
    return cut.rstrip() + "…", True


def entry_timestamp(entry: dict) -> str:
    """The entry's local ``YYYY-MM-DD HH:MM`` stamp, or "" when it has none
    that can be rendered.

    The stored value is untrusted input: ``float()`` raises TypeError on a
    non-numeric one and ``localtime()`` OverflowError/OSError on an
    out-of-range one, and an export must lose at most the stamp of a single
    line — never the whole file."""
    when = entry.get("time")
    if not when:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(when)))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def format_entries(entries: list[dict]) -> str:
    """The given transcripts as a plain-text document, in the order given.

    One block per transcript — its local timestamp on its own line, then the
    text verbatim with its line breaks intact — separated by a blank line, so
    the result reads as notes and can be pasted into any editor. Qt-free and
    deterministic (the caller supplies the entries and their order), which is
    what makes the export rule testable headlessly.

    Entries without a usable timestamp keep their text and simply lose the
    stamp line: an export exists to get the words out, and dropping a
    transcript because its metadata is odd would defeat that."""
    blocks = []
    for entry in entries:
        text = str(entry.get("text", ""))
        if not text:
            continue
        stamp = entry_timestamp(entry)
        blocks.append(f"{stamp}\n{text}" if stamp else text)
    return "\n\n".join(blocks) + "\n" if blocks else ""


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
        (e.g. the same take retried) are ignored.

        Raises `HistoryUnavailable` — and writes nothing — when the stored
        file could not be read: see there. The caller in `app._process`
        already logs it, and the transcript itself is unaffected, so a broken
        history file costs the record of the dictation, never the dictation.
        """
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
        """All stored transcripts, newest first.

        Raises `HistoryUnavailable` when the file cannot be read, so a list
        that could not be produced is never rendered as an empty one. Every
        caller that lists transcripts is a view and already handles it.
        """
        with self._lock:
            return list(reversed(self._load()))

    def latest(self) -> str:
        """The text of the most recent transcript, or "" when there is none.

        Read from the file rather than a cached value: the recording worker
        appends here while the main thread (tray → "Copy last transcript")
        reads, and the file is the single source both already agree on.

        The one reader that swallows `HistoryUnavailable` instead of passing
        it on: this answers a menu click that puts text on the clipboard, not
        a view, so there is nothing here to render the difference into — and
        an exception out of a menu handler is the failure mode this has always
        promised not to have. The menu click still tells the two apart: only
        when this returns "" does `app.nothing_to_copy_message` read the store
        a second time to say why.
        """
        with self._lock:
            try:
                entries = self._load()
            except HistoryUnavailable:
                return ""
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

        Raises `HistoryUnavailable` — and deletes nothing — when the file
        cannot be read: a delete that cannot see the other entries would write
        them away with the one it was asked to remove. The History page says
        so instead of reporting the transcript as already gone. A file that
        cannot be *written* re-raises the write error (logged by `_save`):
        the transcript is still on disk, and True would say otherwise.
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
                self._save(entries, strict=True)
                return True
        return False

    def clear(self) -> None:
        """Drop every stored transcript.

        Writes without reading, deliberately: this is also the way back from a
        file that `_load` refuses (see `HistoryUnavailable`), and a clear that
        first had to read the entries it is about to delete would be the one
        action that cannot repair the file it exists to replace.

        Re-raises a failed write (see `remove`): the user asked for the
        transcripts to be gone, and they are not.
        """
        with self._lock:
            self._save([], strict=True)

    # -------------------------------------------- internal (lock held by caller)

    def _load(self) -> list[dict]:
        """Stored entries, normalized. The file is untrusted input (hand-edited,
        truncated, written by an older build), and its values are handed
        straight to QLabel by the History/Home renderers — a non-string "text"
        (e.g. a number) would raise there. Keeping only entries with a
        non-empty string keeps every consumer, including add()'s duplicate
        check, on a known type.

        No file at all is an empty history and returns ``[]``. A file that is
        there but cannot be turned into a list of entries raises
        `HistoryUnavailable` instead — see there for why the two must not
        arrive as the same answer. Unusable *entries inside* a readable list
        are still dropped rather than raised over: that is one transcript
        nobody can render, not a file nobody can read.
        """
        try:
            if not self.path.exists():
                return []
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            log.exception("could not read transcript history %s", self.path)
            raise HistoryUnavailable(f"{self.path}: {exc}") from exc
        if not isinstance(data, list):
            log.error(
                "transcript history %s holds %s, not a list of entries",
                self.path,
                type(data).__name__,
            )
            raise HistoryUnavailable(f"{self.path}: the file holds no list of transcripts")
        return [
            e for e in data if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"]
        ]

    def _save(self, entries: list[dict], *, strict: bool = False) -> None:
        """Write `entries`; a failure is logged, and re-raised with `strict`.

        `add` runs on the recording worker and must never cost the dictation,
        so it stays lenient. The two deletes are user actions whose whole
        point is the write, so they report it."""
        try:
            atomic_write_json(self.path, entries)
        except Exception:
            log.exception("could not write transcript history %s", self.path)
            if strict:
                raise
