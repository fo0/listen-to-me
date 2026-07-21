"""Microphone recording via sounddevice/PortAudio."""

from __future__ import annotations

import logging
import math
import threading

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what Whisper expects

# Band split (Hz) and the band RMS that maps to a full-scale level — tuned so
# normal speech sweeps the overlay animation over most of its range. The low
# band starts above 0 Hz so a microphone's DC offset and subsonic rumble don't
# show up as a permanent fake low-band level.
_LOW_CUT_HZ = 50.0
_BAND_SPLIT_HZ = (300.0, 2000.0)
_LEVEL_REF_RMS = 0.12


def band_levels(samples, sample_rate: int = SAMPLE_RATE) -> tuple[float, float, float]:
    """Low/mid/high band levels (each 0.0-1.0) of a short mono sample block.

    Drives the overlay's animated microphone widget from the audio the
    recorder captures anyway. The square root compresses the response so
    quiet speech still moves the animation visibly.
    """
    import numpy as np

    n = len(samples)
    if n < 32:
        return 0.0, 0.0, 0.0
    amp = np.abs(np.fft.rfft(samples)) * (2.0 / n)  # per-bin sine amplitude
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    edges = (_LOW_CUT_HZ, _BAND_SPLIT_HZ[0], _BAND_SPLIT_HZ[1], sample_rate / 2.0 + 1.0)
    levels = []
    for lo, hi in zip(edges, edges[1:]):
        band = amp[(freqs >= lo) & (freqs < hi)]
        rms = math.sqrt(float(np.sum(np.square(band))) / 2.0)
        levels.append(min(1.0, math.sqrt(rms / _LEVEL_REF_RMS)))
    return levels[0], levels[1], levels[2]


class Recorder:
    def __init__(self):
        self._stream = None
        self._chunks: list = []
        self._frames = 0
        self._max_frames = 0
        self._on_limit = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._stream is not None

    def start(self, device=None, max_seconds: int = 300, on_limit=None) -> None:
        import sounddevice as sd

        if self._stream is not None:
            raise RuntimeError("recording already active")

        self._chunks = []
        self._frames = 0
        self._max_frames = max(1, int(max_seconds)) * SAMPLE_RATE
        self._on_limit = on_limit

        def callback(indata, frames, time_info, status):
            if status:
                log.debug("audio status: %s", status)
            with self._lock:
                self._chunks.append(indata.copy())
                self._frames += frames
                if self._frames >= self._max_frames:
                    raise sd.CallbackStop

        def finished():
            # Fires when CallbackStop ended the stream (max length reached).
            if self._frames >= self._max_frames and self._on_limit is not None:
                self._on_limit()

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            device=device,
            callback=callback,
            finished_callback=finished,
        )
        self._stream.start()
        log.info("recording started (device=%s, max=%ss)", device, max_seconds)

    def snapshot(self, max_frames: int | None = None, start_frame: int | None = None):
        """Return the audio captured so far without stopping the recording.

        ``max_frames`` returns only the most recent ``max_frames`` samples;
        ``start_frame`` returns everything from that absolute frame offset on
        (live typing uses it to skip already-committed audio). Both bound the
        concatenation to the requested tail, so a periodic caller stays
        O(tail) per call instead of O(total length). Safe to call from any
        thread.
        """
        import numpy as np

        if max_frames is not None and max_frames <= 0:
            return np.zeros(0, dtype="float32")
        with self._lock:
            want = max_frames
            if start_frame is not None:
                # Resolved under the lock: the frame counter must match the
                # chunk list, or audio appended in between would silently
                # shift where the returned tail starts.
                tail = self._frames - max(0, int(start_frame))
                want = tail if want is None else min(want, tail)
                if want <= 0:
                    return np.zeros(0, dtype="float32")
            if want is not None:
                kept: list = []
                total = 0
                for chunk in reversed(self._chunks):
                    kept.append(chunk)
                    total += len(chunk)
                    if total >= want:
                        break
                chunks = list(reversed(kept))
            else:
                chunks = list(self._chunks)
        if not chunks:
            return np.zeros(0, dtype="float32")
        audio = np.concatenate(chunks).flatten()
        if want is not None and len(audio) > want:
            audio = audio[-want:]
        return audio

    def stop(self):
        """Stop recording and return the audio as a 1-D float32 numpy array."""
        import numpy as np

        stream, self._stream = self._stream, None
        self._on_limit = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("error closing audio stream")
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype="float32")
        audio = np.concatenate(chunks).flatten()
        log.info("recording stopped: %.1fs", len(audio) / SAMPLE_RATE)
        return audio


def list_input_devices() -> list[tuple[int, str]]:
    import sounddevice as sd

    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            devices.append((idx, dev.get("name", f"Device {idx}")))
    return devices
