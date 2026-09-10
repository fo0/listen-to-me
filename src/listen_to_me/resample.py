"""Sample-rate conversion for the capture path — numpy only, no sounddevice.

Audio does not always arrive in the format Whisper wants. A loopback/monitor
device runs at the *output's* rate (48 kHz stereo as a rule) and PortAudio
does not resample, so a take captured from one has to be downmixed and
converted to 16 kHz mono somewhere. This module is that somewhere: `audio.py`
calls both pieces inside its PortAudio callback, so everything the recorder
stores is 16 kHz mono and no consumer downstream needs a frame-domain
translation.

Free of sounddevice and of any module-scope numpy import, deliberately: the
rules here are arithmetic over arrays, so `selftest.py` can check them on a
machine with no audio device at all, and importing this module costs nothing
that `--version` would have to pay for.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


# Anti-alias filter of the downsampling path (see Resampler). 64 taps at a 3:1
# decimation — the 48 kHz loopback case — put the transition band between
# roughly 5 kHz and 9 kHz. The count grows with the ratio to keep that width
# in Hz, capped so a pathological rate pair cannot build a kernel whose
# convolution misses the callback deadline.
_FIR_TAPS = 64
_FIR_MAX_TAPS = 512
_FIR_CUTOFF = 0.45  # of the destination rate, i.e. just under its Nyquist


def downmix_to_mono(block: np.ndarray) -> np.ndarray:
    """Mean across the channels of a `(frames, channels)` float32 block.

    Returns a 1-D float32 array; a block that is already 1-D comes back
    unchanged. Loopback inputs deliver the output's channel layout (stereo as
    a rule) and both channels carry the same programme, so the mean keeps a
    centred signal at its level where summing would clip it. numpy only, no
    sounddevice: checkable headlessly.
    """
    import numpy as np

    arr = np.asarray(block)
    if arr.ndim == 1:
        return arr.astype("float32", copy=False)
    return arr.mean(axis=1, dtype="float32")


class Resampler:
    """Fixed-ratio sample-rate conversion that carries its state across blocks.

    A loopback device runs at the output's rate (48 kHz as a rule) and
    PortAudio does not resample, so the capture callback has to. Two
    properties are the whole point of this class:

    - **The state survives the block boundary.** The FIR tail, the last
      filtered sample and the fractional read position are kept, so a stream
      converted block by block comes out as one conversion over the
      concatenated stream would. Resampling each block on its own restarts the
      interpolator at every boundary — a step in the waveform, i.e. a click
      ~47 times a second, which Whisper hears as well as the user does.
    - **It is anti-aliased.** Decimating 48 kHz to 16 kHz without a pre-filter
      folds everything above 8 kHz back into the band Whisper reads: a 12 kHz
      cymbal or a cheap DAC's switching whine lands around 4 kHz and becomes
      words nobody said. A windowed-sinc low-pass (Blackman window, cutoff at
      `_FIR_CUTOFF` × the destination rate) runs first, then linear
      interpolation at the fractional output positions.

    Accuracy contract, checkable with numpy alone (`selftest.py` asserts it):

    - `len(process(block))` is `len(block) * dst_rate / src_rate` ±1 sample
      and the deviation does not accumulate over a run of unequal blocks. Two
      known offsets bracket a whole take: the first block is short by the
      initial phase (one output step — 0.33 samples at 48 → 16 kHz, 2 when
      upsampling 2×), and `flush()` adds the filter's ring-out (`taps - 1`
      input samples, i.e. 21 output samples at 48 → 16 kHz).
    - A 440 Hz sine keeps its RMS within ~10 % (measured: 0.9993 of the input,
      and the same for 100/1000/3000/4000 Hz) — the passband is flat.
    - A tone above the destination Nyquist frequency is attenuated instead of
      aliased down: >1000× at 12 kHz for 48 → 16 kHz (measured 38000× in the
      steady state), where a decimation without the pre-filter would pass it
      at full level, folded to 4 kHz. A test tone that starts and stops
      abruptly carries its own broadband click and measures only ~350× — fade
      the ends when checking the filter rather than the test signal.
    - Equal rates are a cheap pass-through: no filter, no interpolation, no
      group delay, `process` hands the block back and `flush` returns nothing.
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        import numpy as np

        self.src_rate = int(src_rate)
        self.dst_rate = int(dst_rate)
        # Nonsense rates (a device that reported none) degrade to the
        # pass-through rather than dividing by zero inside a callback.
        usable = self.src_rate > 0 and self.dst_rate > 0
        self.passthrough = not usable or self.src_rate == self.dst_rate
        self._step = 1.0 if self.passthrough else self.src_rate / self.dst_rate
        # Only decimation aliases — upsampling needs no pre-filter, and one
        # would only add its group delay.
        self._taps = None if self._step <= 1.0 else self._build_taps()
        self._tail = None if self._taps is None else np.zeros(self._taps.size - 1, dtype="float32")
        # Where the next output sample sits, in filtered input samples counted
        # from the previous block's last one (`_prev`, index 0 of the working
        # array in `_interpolate`). Starting at 1.0 puts the first output
        # exactly on the first real sample, weighting the initial `_prev` — a
        # sample that never existed — zero.
        self._phase = 1.0
        self._prev = 0.0

    def _build_taps(self) -> np.ndarray:
        import numpy as np

        count = int(min(_FIR_MAX_TAPS, _FIR_TAPS * max(1.0, self._step / 3.0)))
        count += 1 - count % 2  # odd: a symmetric kernel with an integer delay
        cutoff = _FIR_CUTOFF * self.dst_rate / self.src_rate  # cycles per input sample
        k = np.arange(count, dtype="float64") - (count - 1) / 2.0
        taps = np.sinc(2.0 * cutoff * k) * np.blackman(count)
        taps /= float(np.sum(taps))  # unity DC gain: the passband level is kept
        return taps.astype("float32")

    def process(self, block: np.ndarray) -> np.ndarray:
        """The converted samples for this block, as a 1-D float32 array."""
        import numpy as np

        if self.passthrough:
            return np.asarray(block, dtype="float32")
        x = np.asarray(block, dtype="float32").reshape(-1)
        if x.size == 0:
            return np.zeros(0, dtype="float32")
        if self._taps is not None:
            # Overlap-save: the previous block's tail is prepended, so every
            # returned sample saw a full kernel and the filter has no boundary
            # of its own. "valid" then returns exactly len(x) samples.
            padded = np.concatenate((self._tail, x))
            filtered = np.convolve(padded, self._taps, mode="valid")
            self._tail = padded[padded.size - self._tail.size :]
        else:
            filtered = x
        return self._interpolate(filtered)

    def flush(self) -> np.ndarray:
        """Whatever the filter and the interpolator still hold at the end of
        the stream — the last millisecond or so, dropped otherwise. Idempotent:
        a second call returns nothing, so a double `stop()` cannot append the
        same tail twice."""
        import numpy as np

        if self._tail is None:  # pass-through or upsampling: no filter to drain
            return np.zeros(0, dtype="float32")
        tail, self._tail = self._tail, np.zeros_like(self._tail)
        if not np.any(tail):
            return np.zeros(0, dtype="float32")
        # Ring the filter out with silence: the samples still inside the kernel
        # are exactly the ones the last process() could not return yet.
        drained = np.convolve(
            np.concatenate((tail, np.zeros(tail.size, dtype="float32"))),
            self._taps,
            mode="valid",
        )
        return self._interpolate(drained)

    def _interpolate(self, filtered: np.ndarray) -> np.ndarray:
        """Linear interpolation at `_step` spacing, continuing across blocks."""
        import numpy as np

        n = filtered.size
        if n == 0:
            return np.zeros(0, dtype="float32")
        # Index 0 is the previous block's last sample, so an output position
        # that falls between two blocks interpolates across the seam.
        work = np.concatenate((np.array([self._prev], dtype="float32"), filtered))
        count = max(0, math.ceil((n - self._phase) / self._step))
        out = np.zeros(0, dtype="float32")
        if count:
            pos = self._phase + self._step * np.arange(count, dtype="float64")
            # Clipped so work[idx + 1] stays in range even when the ceil above
            # rounded the last position a hair past the end of the block.
            idx = np.clip(pos.astype("int64"), 0, n - 1)
            frac = (pos - idx).astype("float32")
            out = work[idx] * (1.0 - frac) + work[idx + 1] * frac
        # The next block's index 0 is this block's last sample: the same
        # coordinate system shifted by n. Keeps _phase inside [0, _step).
        self._phase = self._phase + self._step * count - n
        self._prev = float(filtered[-1])
        return out.astype("float32", copy=False)
