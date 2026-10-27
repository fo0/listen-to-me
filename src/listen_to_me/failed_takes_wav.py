"""The audio format a failed take is kept in: 16 kHz mono 16-bit PCM WAV (#363).

`failed_takes` writes a take's float samples here and reads them back for a
retry. Split out of the store so the store stays about what is kept and for
how long, and this about the bytes.

Stdlib `wave` for the container; numpy, where present, for the conversion —
it is imported lazily, and a pure-stdlib path does the same work without it,
so the self-test exercises the whole round trip on the CI runner, which
installs no numpy.
"""

from __future__ import annotations

import os
import sys
import tempfile
import wave
from array import array
from pathlib import Path

from .audio import SAMPLE_RATE

MAX_SECONDS = 2 * 3600  # the longest cap a take can have is an hour


def pcm16(audio) -> bytes:
    """Float samples as little-endian 16-bit PCM, clipped to [-1, 1] first —
    a sample outside it would wrap around to its opposite in int16."""
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
        return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    clipped = (max(-1.0, min(1.0, x if x == x else 0.0)) for x in map(float, audio))
    pcm = array("h", (int(x * 32767.0) for x in clipped))
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


def samples(pcm: bytes):
    """16-bit PCM back as float32 samples: a numpy array (what the
    transcribers take), or an ``array("f")`` where numpy is missing."""
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        return (np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32767.0).astype(np.float32)
    values = array("h")
    values.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder != "little":
        values.byteswap()
    return array("f", (value / 32767.0 for value in values))


def write_temp(directory: Path, prefix: str, pcm: bytes) -> Path:
    """`pcm` as a WAV in a fresh temp file in `directory` (mkstemp: 0600, a
    ``.tmp`` name), flushed to disk; the caller renames it into place."""
    fd, name = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            with wave.open(fh, "wb") as writer:  # leaves `fh` open
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(SAMPLE_RATE)
                writer.writeframes(pcm)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return tmp


def read(path: Path):
    """A kept take's audio as float32 samples at `SAMPLE_RATE`. ValueError
    for a file this app did not write (another format, or longer than any
    take can be); OSError / wave.Error for one that cannot be read."""
    if path.is_symlink():
        raise OSError(f"{path} is a symlink — refusing to read it")
    with wave.open(str(path), "rb") as reader:
        shape = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate())
        if shape != (1, 2, SAMPLE_RATE):
            raise ValueError(f"{path.name} is not a 16 kHz mono 16-bit recording")
        if reader.getnframes() > MAX_SECONDS * SAMPLE_RATE:
            raise ValueError(f"{path.name} is longer than any recording this app makes")
        pcm = reader.readframes(reader.getnframes())
    return samples(pcm)
