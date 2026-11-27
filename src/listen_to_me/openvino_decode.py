"""The decode guards of the OpenVINO backend (#293): the per-take output cap,
the decoder's own per-window token room and the prompt's token count, plus
the shortest take that gets an initial prompt. Split out of
`transcriber_openvino`; Qt-free, and `openvino_genai` is never imported here.
"""

from __future__ import annotations

import logging

# The backend's logger, as before the split — the log file prints logger names.
log = logging.getLogger("listen_to_me.transcriber_openvino")

# The output budget per second of audio (#293): a prompt echo ran takes of
# 0.5–2.7 s out to 1547 characters each. A cap below the speech is a
# transcript cut short without a word, so it sits well above any real rate.
# Measured with the Whisper tokenizer, German runs 0.25 tokens a character,
# technical German 0.32: the 30 characters a second App._process still
# accepts from a microphone are up to ~10 tokens a second, and system audio
# played at 2× has no such limit at all. 16 cuts neither; the floor leaves a
# short take room, and implausible_reason catches the loop the cap bounds.
_TOKENS_PER_SECOND = 16.0
_MIN_NEW_TOKENS = 32

# Whisper's decoder has 448 positions per 30-s window, shared with what GenAI
# puts in front of the output: <|startoftranscript|>, language, task and
# <|notimestamps|>, plus <|startofprev|> and the prompt when there is one.
_DECODER_POSITIONS = 448
_SOT_TOKENS = 4

# Takes shorter than this get no initial prompt (#293): all four echo takes
# were 0.5–2.7 s — too little audio to outweigh a prompt, so the decoder read
# the prompt back instead — while a vocabulary hint matters for real speech.
_MIN_PROMPT_SECONDS = 3.0


def _is_count(value) -> bool:
    """Whether `value` is a real token count — not None, a bool, 0, or the
    SIZE_MAX GenAI reports for "unset"."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2**32


def _token_room(config, prompt_tokens: int) -> int:
    """The most tokens GenAI itself lets one window generate. An unset
    max_new_tokens reads as SIZE_MAX, and GenAI then stops a window at
    max_length minus its context. A cap set at or above that bound replaces
    it, and a looping window then decodes past the decoder's 448 positions:
    one window of a 120-s take generated 960 tokens (openvino-genai 2026.4,
    CPU), and the NPU's KV cache is a fixed 448."""
    length = getattr(config, "max_length", None)
    room = (length if _is_count(length) else _DECODER_POSITIONS) - _SOT_TOKENS
    if prompt_tokens:
        room -= 1 + prompt_tokens  # <|startofprev|> and the prompt
    current = getattr(config, "max_new_tokens", None)
    return min(room, current) if _is_count(current) else room


def _prompt_tokens(pipe, prompt: str) -> int:
    """How many tokens GenAI puts in front for `prompt` (it encodes " " +
    prompt). Falls back to the UTF-8 byte count: byte-level BPE never needs
    more tokens than bytes, so the room is never overestimated."""
    text = " " + prompt
    try:
        return int(pipe.get_tokenizer().encode(text, add_special_tokens=False).input_ids.get_size())
    except Exception:
        log.debug("could not count the prompt's tokens — using its byte length", exc_info=True)
        return len(text.encode("utf-8"))
