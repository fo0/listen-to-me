"""Catching the text Whisper invents instead of what was said (#293).

Two failure modes reached the cursor. A German faster-whisper dictation ended
in `結, hof, 那个, Share, 这 果, 这 ,, 压 ,, � , 这 , ,,`: a 30-s window that failed
the quality gates was re-decoded at ever higher sampling temperatures (0.0 …
1.0 by default), where Whisper emits random multilingual tokens, the best
failed attempt was accepted anyway, and `condition_on_previous_text` carried
it into the next window. And OpenVINO GenAI turned takes of 0.5 to 2.7 s into
exactly 1547 characters of "contract-manager, " — its prompt
"mergen, ci-radar, contract-manager," echoed until the token limit.

The decoder settings make both rarer; this module judges what still comes
out, deliberately narrowly, since every false positive deletes words somebody
said. Qt-free and numpy-free."""

from __future__ import annotations

import logging
import re
import unicodedata
import zlib

log = logging.getLogger(__name__)

# Whisper language codes written in Latin script: for these, CJK, Thai or
# Cyrillic letters are never what was dictated; elsewhere they are the language.
LATIN_SCRIPT_LANGUAGES = frozenset(
    "af az br bs ca cs cy da de en es et eu fi fo fr gl ha haw hr ht hu id is it jw la lb "
    "ln lt lv mg mi ms mt nl nn no oc pl pt ro sk sl sn so sq sv sw tk tl tr uz vi yo".split()
)

# A segment at least this share foreign is the high-temperature garbage itself
# (its Latin words — "hof", "Share" — included) and is dropped whole; a single
# stray ideograph in a real sentence stays below it and is only stripped.
_SEGMENT_FOREIGN_SHARE = 0.2

# faster-whisper's own `compression_ratio_threshold`: text that compresses
# better than this is repetitive, and its window is re-decoded one rung up.
# A window that fails every rung keeps an attempt below the ratio when any
# exists, so a sampled segment still above it is a loop that survived the
# whole ladder. A low avg_logprob proves no such thing: faster-whisper then
# reports the last rung's temperature whatever it kept, and the low score is
# as often real, hard-to-hear speech — which must never be dropped. Both
# figures belong to the whole window, so a segment's own text has to compress
# beyond the ratio too before it goes.
_MAX_COMPRESSION_RATIO = 2.4

# Dictation runs at 15 to 20 characters a second; 30 is no human, while the
# 1547-character echo came from 0.5 s. The floor keeps a short take from
# tripping it: a clipped "Ja, mach ruhig." can come from half a second.
_MAX_CHARS_PER_SECOND = 30.0
_MIN_ALLOWED_CHARS = 60

# A loop is one n-gram (up to _MAX_LOOP_NGRAM words) repeated at least
# _MIN_LOOP_REPEATS times in a row AND covering at least _LOOP_SHARE of all
# words. Both halves matter: "äh, äh, äh, äh" in a long dictation is speech, a
# transcript that is mostly one phrase over and over is the decoder stuck.
_MIN_LOOP_REPEATS = 8
_LOOP_SHARE = 0.5
_MAX_LOOP_NGRAM = 4

# A transcript of at least this many words that is a verbatim run of the
# prompt can be the prompt echoed back; fewer prove nothing ("Ja, gut").
_MIN_ECHO_WORDS = 3
# …and is one only when it is most of the prompt, or long. A term list exists
# because those terms get dictated: "Kubernetes, Docker, Helm." is three of
# its entries said in its order, not an echo of a four- or 600-term list.
_ECHO_PROMPT_SHARE = 0.8
_LONG_ECHO_WORDS = 8

# Letters not named "LATIN …" that Latin text uses: µ (MICRO SIGN), ª, º.
_LATIN_EXTRAS = frozenset("\u00b5\u00aa\u00ba")
# What a broken multi-byte token decodes to — never dictated.
_REPLACEMENT = "\ufffd"
# What surrounds a garbage run and goes with it, so no ", ," is left behind.
_RUN_SEPARATORS = frozenset(",.;:\u00b7\u3001\u3002\uff0c")


def script_language(language) -> bool | None:
    """True for a Latin-script language code, False for any other, None when
    unknown (None, "" or "auto"): judge it, leave it, decide by the text."""
    code = str(language or "").strip().lower()
    if not code or code == "auto":
        return None
    return code in LATIN_SCRIPT_LANGUAGES


def _is_foreign(ch: str) -> bool:
    """A letter outside the Latin script, or U+FFFD. Digits, punctuation,
    symbols and combining marks are neutral, and so are the spacing modifier
    letters (U+02B0–U+02FF): the ʻ of Uzbek "Oʻzbekiston" is Latin orthography
    although its name says MODIFIER LETTER. So are the Letterlike Symbols
    (U+2100–U+214F — Ω OHM SIGN, K KELVIN SIGN, Å, ℓ, ℝ): units and math
    signs Unicode happens to file as letters."""
    if ch == _REPLACEMENT:
        return True
    if not unicodedata.category(ch).startswith("L") or ch in _LATIN_EXTRAS:
        return False
    if "\u02b0" <= ch <= "\u02ff" or "\u2100" <= ch <= "\u214f":
        return False
    return not unicodedata.name(ch, "").startswith("LATIN")


def _is_greek(ch: str) -> bool:
    return "\u0370" <= ch <= "\u03ff" or "\u1f00" <= ch <= "\u1fff"


def _foreign_flags(text: str) -> list[bool]:
    """_is_foreign for each character of `text`, except that a Greek letter
    with no Greek letter on either side is neutral: that is the symbol Latin
    text borrows it as — 5 μm, 10 kΩ, 2π, ΔT, β-Version — where stripping it
    would silently change the value; a run of them is a Greek word, foreign
    like any other script."""
    flags = [_is_foreign(ch) for ch in text]
    for i, ch in enumerate(text):
        if flags[i] and _is_greek(ch):
            before = i > 0 and _is_greek(text[i - 1])
            after = i + 1 < len(text) and _is_greek(text[i + 1])
            flags[i] = before or after
    return flags


def foreign_share(text) -> float:
    """The share of foreign characters among the letters of `text`, 0.0 when
    it has none. U+FFFD counts as a foreign letter, so `� , ,` is 1.0."""
    text = str(text or "")
    flags = _foreign_flags(text)
    letters = sum(1 for ch, flag in zip(text, flags) if flag or unicodedata.category(ch)[0] == "L")
    return sum(flags) / letters if letters else 0.0


def strip_foreign_runs(text, language=None):
    """`text` with each run of foreign characters, and the separators directly
    around it, replaced by one space.

    Returned unchanged — the same object — when there is nothing to remove,
    for a non-Latin language (its script *is* the text), and for an unknown
    language when the text is mostly non-Latin: that is a speaker of such a
    language, not ours to judge. A combining mark after a foreign letter goes
    with it (Thai vowel signs are marks), so no stray mark is left alone.
    """
    if not text:
        return text
    script = script_language(language)
    if script is False:
        return text
    flags = _foreign_flags(text)
    if not any(flags) or (script is None and foreign_share(text) >= 0.5):
        return text
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if not flags[i]:
            out.append(text[i])
            i += 1
            continue
        while out and (out[-1].isspace() or out[-1] in _RUN_SEPARATORS):
            out.pop()  # the ", " in front of the run
        while i < n and (
            flags[i]
            or text[i].isspace()
            or text[i] in _RUN_SEPARATORS
            or unicodedata.category(text[i]).startswith("M")
        ):
            i += 1  # the run, its marks, its separators and any run right after
        out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def segment_drop_reason(text, *, language, temperature=0.0, compression_ratio=0.0) -> str | None:
    """Why one decoded segment is not kept, or None to keep it.

    "foreign script" for a Latin-script language and a segment at least
    _SEGMENT_FOREIGN_SHARE foreign; "repetition loop after the fallback" when
    its window was sampled (temperature > 0) and still compresses beyond
    _MAX_COMPRESSION_RATIO, and the segment's own text does as well.
    `temperature` and `compression_ratio` are the 30-s window's, shared by
    every segment in it: normal speech decoded next to a loop must not go
    with it (239 characters of German beside 30× "und dann" made a window of
    2.61). A low-confidence segment is never dropped for its score alone:
    that is a hard-to-hear sentence, and losing it is worse.
    """
    if not text or not str(text).strip():
        return None
    if script_language(language) is True and foreign_share(text) >= _SEGMENT_FOREIGN_SHARE:
        return "foreign script"
    try:
        sampled = float(temperature or 0) > 0
        window_looped = float(compression_ratio or 0) > _MAX_COMPRESSION_RATIO
    except (TypeError, ValueError):
        return None  # a malformed segment field proves nothing
    if sampled and window_looped and _compression_ratio(text) > _MAX_COMPRESSION_RATIO:
        return "repetition loop after the fallback"
    return None


def _compression_ratio(text) -> float:
    """faster-whisper's own measure (`get_compression_ratio`): the UTF-8
    length over its zlib-compressed length — high for repetitive text."""
    data = str(text).encode("utf-8")
    return len(data) / len(zlib.compress(data))


def _words(text) -> list[str]:
    """Lowercased whitespace tokens without their outer punctuation, so
    "contract-manager," and "Contract-Manager." are one word (inner hyphens
    stay). Symbols are kept: a "♪ ♪ ♪ …" loop still counts as words."""
    words = []
    for token in str(text or "").lower().split():
        start, end = 0, len(token)
        while start < end and unicodedata.category(token[start]).startswith("P"):
            start += 1
        while end > start and unicodedata.category(token[end - 1]).startswith("P"):
            end -= 1
        if start < end:
            words.append(token[start:end])
    return words


def _longest_repeat(words: list[str], n: int) -> int:
    """How often one n-gram repeats back to back in its longest run: L
    consecutive positions with words[j] == words[j + n] are a period-n stretch
    of L + n words, i.e. (L + n) // n complete repeats."""
    if len(words) < n:
        return 0
    best = run = 0
    for j in range(len(words) - n):
        run = run + 1 if words[j] == words[j + n] else 0
        best = max(best, run)
    return (best + n) // n


def implausible_reason(text, seconds, prompt="") -> str | None:
    """Why `text` cannot be what `seconds` of audio said, or None when it can.

    The phrase reads after "it looks like a recognition error: ". Checked as
    loop, prompt echo, length — a loop that is also too long is named for its
    cause. A `seconds` that is no usable length skips the length check only.
    """
    if not text or not str(text).strip():
        return None
    words = _words(text)
    for n in range(1, _MAX_LOOP_NGRAM + 1):
        repeats = _longest_repeat(words, n)
        if repeats >= _MIN_LOOP_REPEATS and repeats * n >= _LOOP_SHARE * len(words):
            return f"the same words repeat {repeats} times"
    prompt_words = _words(prompt)
    count = len(words)
    sized = count >= _LONG_ECHO_WORDS or count >= _ECHO_PROMPT_SHARE * len(prompt_words)
    # Space-joined with a space at each end: no word holds a space, so this
    # matches exactly a run of whole words.
    if sized and _MIN_ECHO_WORDS <= count <= len(prompt_words):
        if f" {' '.join(words)} " in f" {' '.join(prompt_words)} ":
            return "it repeats the initial prompt"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return None
    # `seconds >= 0` is also False for NaN: no usable length, nothing to measure.
    if seconds >= 0 and len(text) > max(_MIN_ALLOWED_CHARS, seconds * _MAX_CHARS_PER_SECOND):
        return f"{len(text)} characters from {seconds:.1f} s of audio"
    return None
