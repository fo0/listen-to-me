"""Trimming the silence where Whisper invents text (#293); numpy only inside the call."""

from __future__ import annotations

import math

from .hallucination import log


def speech_bounds(levels, *, relative=0.05, floor=0.003) -> tuple[int, int] | None:
    """(first, last) index of the levels that count as speech, or None.

    A level counts from `relative` of the take's 90th-percentile level, never
    below `floor`, so pure room noise has no speech instead of its own hiss as
    the reference. Not of the loudest level: one key click or mic bump 30
    times louder than quiet speech set a bar the whole dictation stayed under
    (a 30-ms click before 3 s of speech kept 0.5 s of the take). A transient
    shorter than a tenth of the take no longer sets that bar.
    """
    values = [value if math.isfinite(value) else 0.0 for value in map(float, levels)]
    if not values:
        return None
    reference = sorted(values)[math.ceil(0.9 * len(values)) - 1]
    threshold = max(floor, reference * relative)
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
