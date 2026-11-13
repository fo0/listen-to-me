"""Whisper reads only the last 223 prompt tokens (faster-whisper's
`get_prompt`: `previous_tokens[-(448 // 2 - 1):]`), so `prompt_tail` hands it
that tail instead of a term cut in half (#293). Qt-free, stdlib only."""

from __future__ import annotations

import math
import unicodedata

from .hallucination import log

# Prompt tokens Whisper reads (448 // 2 - 1), and the characters one token is
# assumed to cover without a tokenizer. Measured with the real Whisper
# tokenizer, a German/English technical term list runs 2.6 characters a token
# (578 characters = 223 tokens), so 2.5 errs toward a tail the model will not
# cut again. CJK, Kana and Hangul are far denser — a Chinese list ran about 2
# tokens a character — so each of those characters counts as 2 tokens.
PROMPT_TOKEN_BUDGET = 223
_CHARS_PER_TOKEN_ESTIMATE = 2.5
_DENSE_CHAR_TOKENS = 2
_DENSE_SCRIPTS = (
    "CJK UNIFIED IDEOGRAPH",
    "CJK COMPATIBILITY IDEOGRAPH",
    "HIRAGANA",
    "KATAKANA",
    "HALFWIDTH KATAKANA",
    "HANGUL",
)
# Where a cut prompt tail may resume; fullwidth marks too, for CJK term lists.
_TERM_SEPARATORS = frozenset(",;\n\uff0c\u3001\uff1b")


def _is_dense(ch: str) -> bool:
    """A CJK ideograph, Kana or Hangul character: _DENSE_CHAR_TOKENS each."""
    return ord(ch) > 0x2FFF and unicodedata.name(ch, "").startswith(_DENSE_SCRIPTS)


def _estimate(length: int, dense: int) -> float:
    return _DENSE_CHAR_TOKENS * dense + (length - dense) / _CHARS_PER_TOKEN_ESTIMATE


def estimate_prompt_tokens(prompt) -> int:
    """A tokenizer-free estimate of the prompt's token count."""
    text = str(prompt or "").strip()
    return math.ceil(_estimate(len(text), sum(map(_is_dense, text))))


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
    is the last `budget` tokens; without them, or when either fails, the
    longest tail `estimate_prompt_tokens` puts within `budget`. Never raises.
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
    start, dense = len(text), 0
    while start > 0:
        dense += _is_dense(text[start - 1])
        if _estimate(len(text) - start + 1, dense) > budget:
            break
        start -= 1
    if start == 0:
        return text
    # One character more than fits: when that one is a separator the cut fell
    # on a boundary, and only it is dropped — the first term stays whole.
    return _drop_cut_term(text[start - 1 :])[-(len(text) - start) :]
