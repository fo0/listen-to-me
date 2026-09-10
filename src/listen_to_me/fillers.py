"""Dropping the phrase Whisper invents for a take that contains no speech.

Press the hotkey, say nothing, press it again, and the text that lands at the
cursor is a sentence nobody spoke — "Vielen Dank." in German, "Thank you." in
English, or a subtitle credit ("Untertitelung des ZDF, 2020"). None of those
strings exist anywhere in this app; they come out of the model. Whisper was
trained on subtitled video, where a stretch without speech is often subtitled
with the clip's closing phrase, so near-silence decodes to the most likely
"silence continuation" the model ever saw (issue #190).

Neither guard in front of it catches this. `vad_filter` (Silero VAD) keeps a
chunk as soon as there is room noise or a keyboard click, and faster-whisper's
`no_speech_threshold` only drops a segment when `no_speech_prob` is high *and*
`avg_logprob` is low — while these hallucinations are decoded with high
confidence, so they pass every quality gate the decoder has. The one place
left to catch them is the finished transcript, which is what this module does.

The rule is deliberately narrow: a phrase only counts when it is the *whole*
transcript. "Vielen Dank" is a sentence people really dictate, and a filter
that removed it from inside a text would corrupt real dictations to fix an
empty one.

Qt-free, numpy-free, pure stdlib — `app.py` calls `is_filler` on the worker
thread, the Settings window calls `describe_filler_phrases` while the list is
being edited, and the headless self-test exercises both.
"""

from __future__ import annotations

import logging
import unicodedata

log = logging.getLogger(__name__)

# What is_filler returns for a transcript that holds nothing but punctuation or
# whitespace. Deliberately not a phrase from the list: a stable string for the
# log, and something a caller can tell the two cases apart by.
EMPTY_TRANSCRIPT = "(empty transcript)"

# The Unicode categories trimmed off the ends of a phrase — everything a model
# puts *around* a sentence. Ps/Pe (brackets) are deliberately not in here; see
# _is_trimmable and normalize for why they are content.
_TRIMMED_CATEGORIES = frozenset({"Po", "Pd", "Pc", "Pi", "Pf", "Sm", "Sc", "Sk", "So"})

# Hard cap on the phrase list, mirroring _MAX_REPLACEMENT_RULES in app.py: a
# hand-edited config is untrusted input, and the list is walked after every
# single dictation.
_MAX_FILLER_PHRASES = 500

# How many bad lines describe_filler_phrases names before it counts the rest —
# the status is one line under a text field, and a list pasted in from
# somewhere else can have dozens of them. Same reasoning as app.py's.
_MAX_REPORTED_ISSUES = 3

# The phrase list the log has already complained about; see _warn_once.
_warned_spec: str | None = None


def _warn_once(spec: str, message: str, *args: object, exc_info: bool = False) -> None:
    """Log `message` at warning level, but only once per distinct phrase list.

    Both entry points run hot: `is_filler` after every single recording, and
    `describe_filler_phrases` on every keystroke while the list is being
    edited. Warning per call would repeat one hand-edited typo hundreds of
    times and bury everything else in the log, so the module remembers the text
    it last complained about and stays quiet until that text changes — the list
    only changes when the user edits it, so once per version of it is exactly
    the information a log reader wants. The *visible* report is
    `describe_filler_phrases`, which is built from the `issues` list and is
    therefore never suppressed.
    """
    global _warned_spec
    if _warned_spec == spec:
        return
    _warned_spec = spec
    log.warning(message, *args, exc_info=exc_info)


def _is_trimmable(ch: str) -> bool:
    """True for a character that carries no meaning at the edge of a phrase:
    whitespace, the punctuation a model sprinkles around a sentence (`Po` `Pd`
    `Pc` `Pi` `Pf`) or a symbol (`Sm` `Sc` `Sk` `So` — the `♪` it emits for
    music, `+`, currency signs).

    Brackets (`Ps`, `Pe`) are content, not decoration — see `normalize`. The
    one exception is the quotation marks Unicode files under them: `„` and `‚`
    are `Ps`, so a category test alone would leave `„Vielen Dank!"` starting
    with a quote while the closing `"` (`Pf`) came off. They are recognized by
    Unicode *name* so that every real bracket — `(`, `[`, `{`, `「` — keeps
    being kept, whatever the next model writes.
    """
    if ch.isspace():
        return True
    category = unicodedata.category(ch)
    if category in _TRIMMED_CATEGORIES:
        return True
    if category in ("Ps", "Pe"):
        return "QUOTATION MARK" in unicodedata.name(ch, "")
    return False


def normalize(text: str) -> str:
    """The comparison form of `text`: casefolded, whitespace collapsed, outer
    punctuation removed.

    Applied to both sides of the comparison — every phrase in the list and the
    transcript — so `Vielen Dank.`, `vielen dank!`, `„Vielen Dank!"` and
    `  Vielen  Dank  ` all reduce to the same `vielen dank`. The model
    punctuates its own hallucination inconsistently — sometimes a full stop,
    sometimes an exclamation mark, sometimes typographic quotes around the
    whole thing — and none of that is a difference the user could have
    anticipated when writing the list.

    Four choices worth naming:

    * `str.casefold()`, not `.lower()` — casefold folds `ß` to `ss`, so a
      phrase written `Straße` also matches a transcript spelled `STRASSE`,
      which `.lower()` would leave apart. Umlauts are letters and are never
      touched by any step here.
    * Punctuation is recognized by Unicode *category* (`Po` `Pd` `Pc` `Pi` `Pf`
      and the four `S*`), not by an explicit ASCII set. The model emits
      typographic marks — `„ " ' – — … » «` and `♪` — and an explicit set would
      silently miss the next one. Letters and digits survive, so
      `Untertitelung des ZDF, 2020` keeps its year.
    * **Brackets are the exception and stay** (`Ps`/`Pe`, minus the quotation
      marks Unicode files under them). They are not decoration, they are the
      signal that the text is a non-speech annotation rather than a word: the
      shipped entry `[Musik]` normalizes to `[musik]` and matches a transcript
      `[Musik]`, while somebody dictating the single word `Musik` normalizes to
      `musik`, matches nothing and gets their word. Stripping the brackets made
      those two indistinguishable, which is a wrong answer, not a stricter
      filter.
    * Only the *outer* punctuation goes. Inner marks stay, because they are
      what separates a transcript that is nothing but the phrase from a real
      dictation that contains it: `ich bedanke mich. vielen dank` keeps its
      full stop and is therefore not equal to `vielen dank`.

    This is a comparison key, never text to insert. What reaches the cursor is
    always the transcript as the model wrote it — this module either drops it
    whole or leaves it completely alone.
    """
    folded = " ".join(str(text or "").split()).casefold()
    start, end = 0, len(folded)
    while start < end and _is_trimmable(folded[start]):
        start += 1
    while end > start and _is_trimmable(folded[end - 1]):
        end -= 1
    return folded[start:end]


def _has_content(probe: str) -> bool:
    """True when a normalized string holds anything that could be typed — one
    letter or digit is enough.

    Not the same as `probe != ""` since brackets survive `normalize`: an empty
    annotation (`[...]`, `[]`, `(…)`, which a model produces for a silent take
    just like a bare ellipsis) keeps its brackets and is therefore not the
    empty string, while still being nothing anybody could want at the cursor.
    """
    return any(ch.isalnum() for ch in probe)


def parse_filler_phrases(spec: str, issues: list[str] | None = None) -> list[str]:
    """The filler phrases in `spec`, normalized, in the order they are written.

    One phrase per line. Blank lines and lines starting with `#` are comments,
    exactly like the `replacements` list — the two fields sit in the same
    window and must not have two different syntaxes. Every phrase is reduced to
    its comparison form by `normalize`, and a phrase already in the list is
    dropped without complaint: `Vielen Dank` and `Vielen Dank!` are one rule,
    and a user who writes both meant one.

    A line with no letter or digit left in it — punctuation only, `...`, `--`,
    an empty `[]` — is skipped rather than kept, because such a phrase could
    only ever match a transcript that is itself empty, a case `is_filler`
    already covers on its own. Pass a list as `issues` to collect those lines
    as short phrases naming each one ("line 4 is only punctuation"); the list
    is appended to and never read here, so the phrases a call returns are
    exactly the same with and without it. Only per-line problems land in it —
    hitting the phrase cap is not one of them, and `describe_filler_phrases`
    reports that from the phrase count instead.

    Qt-free and free of side effects bar one log line, so the syntax is
    testable headlessly.
    """
    spec_text = str(spec or "")
    phrases: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(spec_text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        phrase = normalize(line)
        if not _has_content(phrase):
            _warn_once(spec_text, "filler phrase on line %d is only punctuation, ignored", number)
            if issues is not None:
                issues.append(f"line {number} is only punctuation")
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        phrases.append(phrase)
        if len(phrases) >= _MAX_FILLER_PHRASES:
            _warn_once(
                spec_text, "more than %d filler phrases — the rest is ignored", _MAX_FILLER_PHRASES
            )
            break
    return phrases


def is_filler(text: str, spec: str) -> str | None:
    """The phrase from `spec` that `text` consists of, or None to keep the text.

    Fires only when a filler phrase is the *entire* transcript, compared in the
    form `normalize` produces — so `Vielen Dank.`, `vielen dank` and
    `  Vielen  Dank!  ` all match the entry `Vielen Dank`, while a sentence
    that merely opens with the phrase ("Vielen Dank für das Gespräch, ich melde
    mich morgen.") or a real dictation that ends in it comes back untouched.
    Never a prefix, never a suffix, never mid-sentence: "vielen Dank" is
    something people dictate, and deleting it out of a sentence would be a far
    worse bug than the one this fixes. Brackets are part of the comparison, so
    the entry `[Musik]` catches the annotation `[Musik]` and leaves the spoken
    word `Musik` alone.

    A transcript with no letter or digit in it — `...`, `.`, `—`, `♪♪`, `[]`,
    or nothing at all — counts as filler too and comes back as
    `EMPTY_TRANSCRIPT`. That case is not in the phrase list and does not depend
    on it: a silent take just as regularly decodes to a lone ellipsis as to a
    phrase, and there is nothing there to insert at the cursor either way. The
    marker is a fixed string so the caller can log *what* fired.

    Never raises. This runs on the worker thread between a finished dictation
    and its insertion, so a hand-edited list that somehow cannot be parsed
    costs the filter, never the user's text — a broken list filters nothing.
    The list is re-read on every call (it is short, and the user may have
    edited it since the last recording), while a complaint about it reaches the
    log once instead of once per recording.
    """
    try:
        probe = normalize(text)
        if not _has_content(probe):
            return EMPTY_TRANSCRIPT
        for phrase in parse_filler_phrases(spec):
            if probe == phrase:
                return phrase
    except Exception:
        # Unreachable for str input — this is pure string work — but what it
        # would cost is the user's dictation, so it fails soft instead.
        _warn_once(
            str(spec or ""), "filler filter failed, transcript kept as it is", exc_info=True
        )
    return None


def describe_filler_phrases(spec: str) -> str:
    """The one-line status for the filler phrase field: how many phrases are in
    force, and which lines were thrown away.

    The same job as `describe_replacements` in `app.py`, for the same reason: a
    bad line is skipped with a warning that goes to the log file, which is not
    where anyone editing the list is looking, and the field then looks exactly
    like one whose phrases all work. This is the line shown under it while it
    is being edited, and the Settings page shows it verbatim — so it is a
    finished sentence, not a fragment.

    Empty for an empty field: a list nobody has written in yet needs its
    placeholder, not a count of zero. A duplicate line is deliberately not
    reported as ignored — it is not a mistake, it just does not add a phrase,
    and the count already says so.
    """
    issues: list[str] = []
    phrases = parse_filler_phrases(spec, issues)
    if not phrases and not issues:
        return ""
    status = f"{len(phrases)} phrase{'' if len(phrases) == 1 else 's'} active"
    if issues:
        shown = issues[:_MAX_REPORTED_ISSUES]
        listed = ", ".join(shown)
        hidden = len(issues) - len(shown)
        if hidden:
            listed += f", and {hidden} more"
        status += f" · {len(issues)} line{'' if len(issues) == 1 else 's'} ignored: {listed}"
    status += "."
    if len(phrases) >= _MAX_FILLER_PHRASES:
        # Its own sentence, not one of the ignored lines: the parser stops
        # counting at the cap, so it does not know how many lines came after it.
        status += f" Only the first {_MAX_FILLER_PHRASES} phrases are used."
    return status
