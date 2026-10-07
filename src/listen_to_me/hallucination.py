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
said. Whisper also reads only the last 223 prompt tokens (faster-whisper's
`get_prompt`: `previous_tokens[-(448 // 2 - 1):]`), so `prompt_tail` hands it
that tail instead of a term cut in half. Qt-free and numpy-free at import
(only `trim_silence` imports numpy, inside the call).
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata

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

# faster-whisper's own `log_prob_threshold`: a sampled segment below it failed
# the gate at every temperature and was only accepted because the ladder ended.
_FALLBACK_MIN_LOGPROB = -1.0

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
# prompt is the prompt echoed back; fewer prove nothing ("Ja, gut").
_MIN_ECHO_WORDS = 3

# Prompt tokens Whisper reads (448 // 2 - 1), and the characters one token is
# assumed to cover without a tokenizer — low for a German/English term list,
# so the estimate errs toward a tail the model will not cut again.
PROMPT_TOKEN_BUDGET = 223
_CHARS_PER_TOKEN_ESTIMATE = 3.0

# Letters not named "LATIN …" that Latin text uses: µ (MICRO SIGN), ª, º.
_LATIN_EXTRAS = frozenset("\u00b5\u00aa\u00ba")
# What a broken multi-byte token decodes to — never dictated.
_REPLACEMENT = "\ufffd"
# What surrounds a garbage run and goes with it, so no ", ," is left behind.
_RUN_SEPARATORS = frozenset(",.;:\u00b7\u3001\u3002\uff0c")
# Where a cut prompt tail may resume; fullwidth marks too, for CJK term lists.
_TERM_SEPARATORS = frozenset(",;\n\uff0c\u3001\uff1b")


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


def segment_drop_reason(text, *, language, temperature=0.0, avg_logprob=0.0) -> str | None:
    """Why one decoded segment is not kept, or None to keep it.

    "foreign script" for a Latin-script language and a segment at least
    _SEGMENT_FOREIGN_SHARE foreign; "low-confidence fallback" when it was
    sampled (temperature > 0) and still scored below _FALLBACK_MIN_LOGPROB. A
    temperature-0 segment with a poor score is kept: that is a hard-to-hear
    sentence, the decoder's best effort, not a guess.
    """
    if not text or not str(text).strip():
        return None
    if script_language(language) is True and foreign_share(text) >= _SEGMENT_FOREIGN_SHARE:
        return "foreign script"
    try:
        doubted = float(temperature or 0) > 0 and float(avg_logprob or 0) < _FALLBACK_MIN_LOGPROB
    except (TypeError, ValueError):
        doubted = False  # a malformed segment field proves nothing
    return "low-confidence fallback" if doubted else None


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
    # Space-joined with a space at each end: no word holds a space, so this
    # matches exactly a run of whole words.
    if _MIN_ECHO_WORDS <= len(words) <= len(prompt_words):
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


def estimate_prompt_tokens(prompt) -> int:
    """A tokenizer-free estimate of the prompt's token count."""
    return math.ceil(len(str(prompt or "").strip()) / _CHARS_PER_TOKEN_ESTIMATE)


def prompt_exceeds_window(prompt) -> bool:
    """Whether Whisper would ignore the start of this prompt (by estimate)."""
    return estimate_prompt_tokens(prompt) > PROMPT_TOKEN_BUDGET


def _drop_cut_term(tail: str) -> str:
    """`tail` without its first fragment up to and including the first
    separator — the term the cut went through. A tail with no separator at
    all (an unpunctuated CJK prompt) is kept whole rather than emptied."""
    for index, ch in enumerate(tail):
        if ch.isspace() or ch in _TERM_SEPARATORS:
            return tail[index + 1 :].strip()
    return tail.strip()


def prompt_tail(prompt, *, budget=PROMPT_TOKEN_BUDGET, encode=None, decode=None) -> str:
    """What of `prompt` Whisper will actually read: the stripped prompt when
    it fits `budget` tokens, else its tail, starting on a whole term.

    With `encode`/`decode` (the model's tokenizer, text ↔ token ids) the tail
    is the last `budget` tokens; without them, or when either fails, the last
    `budget * _CHARS_PER_TOKEN_ESTIMATE` characters. Never raises.
    """
    text = str(prompt or "").strip()
    budget = max(0, int(budget))
    if not text or budget == 0:
        return ""
    if encode is not None and decode is not None:
        try:
            ids = list(encode(text))
            if len(ids) <= budget:
                return text
            tail = decode(ids[-budget:])
            if isinstance(tail, str):
                return _drop_cut_term(tail)
            log.debug("prompt decode returned %s, not text — estimating", type(tail).__name__)
        except Exception:
            log.debug("prompt tokenization failed — estimating the tail by length", exc_info=True)
    limit = int(budget * _CHARS_PER_TOKEN_ESTIMATE)
    if len(text) <= limit:
        return text
    # One character more than fits: when that one is a separator the cut fell
    # on a boundary, and only it is dropped — the first term stays whole.
    return _drop_cut_term(text[-limit - 1 :])[-limit:]


def speech_bounds(levels, *, relative=0.05, floor=0.003) -> tuple[int, int] | None:
    """(first, last) index of the levels that count as speech, or None.

    A level counts from `relative` of the loudest one, never below `floor`,
    so pure room noise has no speech instead of its own hiss as the reference.
    """
    values = [value if math.isfinite(value) else 0.0 for value in map(float, levels)]
    if not values:
        return None
    threshold = max(floor, max(values) * relative)
    loud = [index for index, value in enumerate(values) if value >= threshold]
    return (loud[0], loud[-1]) if loud else None


def trim_silence(audio, sample_rate, *, frame_seconds=0.03, pad_seconds=0.3):
    """`audio` without the silence before the first and after the last speech
    frame, keeping `pad_seconds` on each side so no soft onset or trailing
    consonant is lost — silence is where Whisper invents text. Returns `audio`
    itself when there is nothing to trim, no speech, or anything fails (no
    numpy, odd input): trimming is an optimisation, never a lost take."""
    try:
        import numpy as np

        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim != 1 or samples.size == 0:
            return audio
        frame = max(1, int(sample_rate * frame_seconds))
        count = -(-samples.size // frame)  # the last partial frame counts too
        frames = np.pad(samples.astype(np.float64), (0, count * frame - samples.size))
        frames = frames.reshape(count, frame)
        bounds = speech_bounds(np.sqrt(np.mean(frames * frames, axis=1)).tolist())
        if bounds is None:
            return audio
        pad = max(0, int(sample_rate * pad_seconds))
        start = max(0, bounds[0] * frame - pad)
        end = min(samples.size, (bounds[1] + 1) * frame + pad)
        if start == 0 and end == samples.size:
            return audio
        return audio[start:end]
    except Exception:
        log.debug("could not trim the silence around a take", exc_info=True)
        return audio
