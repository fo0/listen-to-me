"""Audio capture via sounddevice/PortAudio — microphones and loopback inputs.

A loopback (monitor) input is what makes recording the computer's *output*
possible: "Monitor of ..." on PipeWire/PulseAudio, "Stereo Mix" or a virtual
cable (VB-CABLE, VoiceMeeter) on Windows, BlackHole on macOS. Nothing here can
request a WASAPI loopback stream — sounddevice 0.5.6 exposes no loopback
option and the PortAudio in its Windows wheel (V19.7.0-devel) does not export
`PaWasapi_IsLoopback` — so such a device is a plain input device with an
awkward format. Hence `input_device_profiles()`, which the ranking in
`system_audio.py` reads to identify the candidates, and the recorder's
native-format fallback: a loopback input rarely offers 16 kHz mono, and
PortAudio does not resample.
"""

from __future__ import annotations

import logging
import math
import sys
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from .resample import Resampler, downmix_to_mono

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what Whisper expects

# Memory backstop for one take, matching the top of the Settings range for
# max_seconds. The recorder keeps every captured chunk in RAM until stop(), so
# a cap it never reaches is an unbounded list — the config consumer (app.py)
# clamps the setting; this catches any other caller.
MAX_RECORDING_SECONDS = 3600

# Band split (Hz) and the band RMS that maps to a full-scale level — tuned so
# normal speech sweeps the overlay animation over most of its range. The low
# band starts above 0 Hz so a microphone's DC offset and subsonic rumble don't
# show up as a permanent fake low-band level.
_LOW_CUT_HZ = 50.0
_BAND_SPLIT_HZ = (300.0, 2000.0)
_LEVEL_REF_RMS = 0.12

# Opened instead when a device refuses 16 kHz mono and reports no usable rate
# of its own — every loopback input seen in the wild runs at the output's rate.
_FALLBACK_SAMPLE_RATE = 48000


def band_levels(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> tuple[float, float, float]:
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


def _wasapi_auto_convert(sd, device: int | str | None) -> object | None:
    """`WasapiSettings(auto_convert=True)` for a WASAPI device, else None —
    which is what `extra_settings` defaults to anyway.

    Called only for a caller that passed `os_convert` (see `Recorder.start`).
    WASAPI in shared mode can insert the OS rate/channel converter, and then a
    loopback device locked to 48 kHz stereo accepts a 16 kHz mono stream
    outright: nothing to resample here at all. Everything is guarded because
    none of it may cost us the plain open attempt that works today — the
    settings class exists only in the Windows PortAudio build, and the host
    API of a device index that just disappeared cannot be resolved.
    """
    if sys.platform != "win32":
        return None
    try:
        info = sd.query_devices(device, "input")
        api = sd.query_hostapis(int(info["hostapi"]))
        if "wasapi" not in str(api.get("name", "")).lower():
            return None
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        log.debug("could not build the WASAPI auto-convert settings", exc_info=True)
        return None


def _native_input_format(sd, device: int | str | None) -> tuple[int, int]:
    """The `(samplerate, channels)` to open `device` with after it refused
    16 kHz mono: its own default rate, and at most two channels.

    Two is plenty — they are averaged into mono immediately, and an 8-channel
    loopback would only pay bandwidth for six more copies of the same
    programme. A device offering a single channel gets one.
    """
    info = sd.query_devices(device, "input")
    rate = int(round(float(info.get("default_samplerate", 0) or 0)))
    if rate <= 0:
        log.debug(
            "device %s reports no default samplerate — trying %d Hz",
            device, _FALLBACK_SAMPLE_RATE,
        )
        rate = _FALLBACK_SAMPLE_RATE
    return rate, max(1, min(2, int(info.get("max_input_channels", 1) or 1)))


class Recorder:
    def __init__(self):
        self._stream = None
        self._chunks: list = []
        self._frames = 0
        self._max_frames = 0
        self._on_limit: Callable[[], None] | None = None
        self._on_ended: Callable[[], None] | None = None
        self._lock = threading.Lock()
        # Callback invocations of the running (or last) take that reported a
        # PortAudio status flag — input overflow, i.e. frames the device
        # produced while the callback was late. Reset by start(), kept past
        # stop() so the caller can mention it next to an empty transcript.
        self._dropped = 0
        self._status_warned = False
        # Set only when the device refused 16 kHz mono (see start()). Like
        # _dropped, both survive stop() so the finished take can still be
        # asked what it recorded; start() resets them.
        self._resampler: Resampler | None = None
        self._stream_format: tuple[int, int] | None = None

    @property
    def active(self) -> bool:
        return self._stream is not None

    @property
    def dropped_buffers(self) -> int:
        """How many audio buffers PortAudio flagged (dropped frames) during the
        running or most recent take."""
        return self._dropped

    @property
    def stream_format(self) -> tuple[int, int] | None:
        """The `(samplerate, channels)` the running (or most recent) stream was
        actually opened with — `(16000, 1)` unless the device refused it. None
        before the first start()."""
        return self._stream_format

    @property
    def resampling(self) -> bool:
        """Whether the callback is converting to 16 kHz mono, i.e. the
        native-format fallback was used. What the recorder stores is 16 kHz
        mono either way; the callers that care are the frame-exact features."""
        return self._resampler is not None

    def start(
        self,
        device: int | str | None = None,
        max_seconds: int = 300,
        on_limit: Callable[[], None] | None = None,
        on_ended: Callable[[], None] | None = None,
        *,
        os_convert: bool = False,
    ) -> None:
        """Open the input stream. `on_limit` fires when max_seconds is reached;
        `on_ended` fires when the stream dies on its own (device unplugged,
        PortAudio abort) — never for stop() or the max-length case. Both are
        invoked on PortAudio's callback thread.

        `os_convert` asks the OS to convert the format where it can — on
        Windows through WASAPI's `auto_convert` in shared mode, which often
        makes a device offering only 48 kHz stereo accept a 16 kHz mono stream
        outright and skips this module's resampler entirely. Opt-in, and off
        for the microphone: it changes how the stream is opened and no
        Windows driver's reaction to that can be predicted from the outside,
        while a microphone gains nothing from it — it already opens at 16 kHz
        mono. System audio is the source that needs it, its loopback devices
        being the ones that refuse the plain format.
        """
        import sounddevice as sd

        if self._stream is not None:
            raise RuntimeError("recording already active")

        self._chunks = []
        self._frames = 0
        seconds = max(1, int(max_seconds))
        if seconds > MAX_RECORDING_SECONDS:
            log.warning(
                "max_seconds %d exceeds the %d s ceiling — the recording stops there",
                seconds, MAX_RECORDING_SECONDS,
            )
            seconds = MAX_RECORDING_SECONDS
        self._max_frames = seconds * SAMPLE_RATE
        self._on_limit = on_limit
        self._on_ended = on_ended
        self._dropped = 0
        self._status_warned = False
        # Per take: the fallback below installs a fresh converter, and a
        # previous take's filter tail must never bleed into this one.
        self._resampler = None

        def callback(indata, frames, time_info, status):
            if status:
                # Input overflow means the device produced frames while this
                # callback was late — they are gone, and the transcript will
                # miss words. One WARNING per take: on an overloaded machine
                # the flag repeats on every callback, and the count carries
                # the rest of the story (see dropped_buffers).
                self._dropped += 1
                if self._status_warned:
                    log.debug("audio status: %s", status)
                else:
                    self._status_warned = True
                    log.warning(
                        "audio status: %s — audio buffers are being dropped, the "
                        "transcript may miss words (the system is overloaded)",
                        status,
                    )
            resampler = self._resampler
            if resampler is None:
                block = indata.copy()  # PortAudio reuses its buffer
            else:
                # Converted here, inside the callback, deliberately:
                # everything downstream — snapshot(), stop(), self._frames,
                # the max-length cap, the live preview, livetype.py — counts
                # in 16 kHz mono frames, so converting later would need a
                # frame-domain translation in every one of them. The cost is
                # two numpy ops on a ~1024-frame block (a mean and one 64-tap
                # convolution). The downmix allocates, so PortAudio's buffer
                # is not retained here either.
                block = resampler.process(downmix_to_mono(indata))
                frames = len(block)
                if frames == 0:
                    return  # nothing came out of this block: nothing to count
            with self._lock:
                self._chunks.append(block)
                self._frames += frames
                if self._frames >= self._max_frames:
                    raise sd.CallbackStop

        def finished():
            # Fires whenever the stream ends. Snapshot the callbacks:
            # Recorder.stop() nulls the attributes from the main thread, and
            # re-reading one between check and call would raise inside the
            # PortAudio callback thread.
            cb = self._on_limit
            if self._frames >= self._max_frames and cb is not None:
                cb()  # CallbackStop: the max recording length was reached
                return
            ended = self._on_ended
            if ended is not None:
                # Not stop() (that nulls the callback before stopping) and
                # not the length cap: the stream died on its own. Without
                # this signal the app would keep showing RECORDING while
                # nothing is captured — silent loss of everything spoken
                # from here on. Deliberately NOT gated on self._stream: a
                # death during start() can fire before the stream is
                # published, and the app-side RECORDING guard drops any
                # ordering that no longer applies.
                ended()

        # 16 kHz mono first — what Whisper wants and what every microphone
        # delivers, so the ordinary dictation path is what it always was:
        # os_convert defaults off, and `extra_settings=None` is what
        # sounddevice fills in by itself. With os_convert the WASAPI
        # auto-convert hint rides along on this attempt: it often makes a
        # loopback device accept 16 kHz mono outright, and then there is
        # nothing to convert below.
        native: tuple[int, int] | None = None
        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=device,
                callback=callback,
                finished_callback=finished,
                extra_settings=_wasapi_auto_convert(sd, device) if os_convert else None,
            )
        except sd.PortAudioError as exc:
            # A loopback input is usually locked to the output's format
            # (48 kHz stereo) and PortAudio does not resample, so an invalid
            # sample rate / channel count is not a broken device here: record
            # in the device's own format and convert. `sd.PortAudioError` is
            # looked up only in this handler, so a stand-in sounddevice module
            # carrying no more than InputStream/CallbackStop still drives the
            # attempt above.
            native = _native_input_format(sd, device)
            stream = sd.InputStream(
                samplerate=native[0],
                channels=native[1],
                dtype="float32",
                device=device,
                callback=callback,
                finished_callback=finished,
            )
            # Assigned before start(): the callback reads it, and the first
            # callback can fire the moment the stream runs.
            self._resampler = Resampler(native[0], SAMPLE_RATE)
            log.info(
                "device %s refused %d Hz mono (%s) — recording at %d Hz / %d channel(s), "
                "converted to %d Hz mono in the callback",
                device, SAMPLE_RATE, exc, native[0], native[1], SAMPLE_RATE,
            )
        self._stream_format = (SAMPLE_RATE, 1) if native is None else native
        # Published to self._stream only once it actually runs: a stream that
        # opens but fails to start (device pulled between open and start) would
        # otherwise leave `active` True forever, so every later start() raised
        # "recording already active" and the hotkey was dead until restart.
        try:
            stream.start()
        except Exception:
            self._on_limit = None
            self._on_ended = None
            try:
                stream.close()
            except Exception:
                log.debug("could not close the unstarted audio stream", exc_info=True)
            raise
        self._stream = stream
        log.info("recording started (device=%s, max=%ss)", device, max_seconds)

    def snapshot(
        self, max_frames: int | None = None, start_frame: int | None = None
    ) -> np.ndarray:
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

    def stop(self) -> np.ndarray:
        """Stop recording and return the audio as a 1-D float32 numpy array."""
        import numpy as np

        stream, self._stream = self._stream, None
        self._on_limit = None
        self._on_ended = None
        if stream is not None:
            try:
                try:
                    stream.stop()
                finally:
                    # A failed stop() must still close: the stream object and
                    # its device session would otherwise leak for the process
                    # lifetime.
                    stream.close()
            except Exception:
                log.exception("error closing audio stream")
        resampler = self._resampler
        if resampler is not None:
            # The stream is closed, so no callback can be in flight: the last
            # few milliseconds still inside the filter and the interpolator
            # can be appended here. Without this they are simply cut off the
            # end of every take.
            try:
                tail = resampler.flush()
            except Exception:
                log.exception("could not flush the resampler — the take loses its last few ms")
                tail = None
            if tail is not None and len(tail):
                with self._lock:
                    self._chunks.append(tail)
                    self._frames += len(tail)
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype="float32")
        audio = np.concatenate(chunks).flatten()
        log.info(
            "recording stopped: %.1fs%s",
            len(audio) / SAMPLE_RATE,
            f" ({self._dropped} audio buffers dropped)" if self._dropped else "",
        )
        return audio


def list_input_devices() -> list[tuple[int, str]]:
    import sounddevice as sd

    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            devices.append((idx, dev.get("name", f"Device {idx}")))
    return devices


def list_output_devices() -> list[tuple[int, str]]:
    """(index, name) of every device PortAudio can play to.

    Mirror of `list_input_devices` for the Settings UI: a loopback candidate
    ("Monitor of ...", "Stereo Mix", a virtual cable) only means something
    next to the output it belongs to. Never raises — a page that cannot name
    the outputs still has to render."""
    try:
        import sounddevice as sd

        return [
            (idx, dev.get("name", f"Device {idx}"))
            for idx, dev in enumerate(sd.query_devices())
            if dev.get("max_output_channels", 0) > 0
        ]
    except Exception:
        log.exception("could not list output devices")
        return []


def input_device_profiles() -> list[dict]:
    """One dict per input device, with the keys `index`, `name`, `hostapi`
    (the host API *name*), `channels` (max input channels) and `samplerate`
    (the device default, as a float).

    What the loopback-candidate ranking in `system_audio.py` reads
    (`loopback_candidates` / `resolve_loopback_device`): the host API name
    separates a WASAPI monitor entry from the same card's WDM-KS one, and the
    channels plus the rate say whether a candidate can be recorded at all.
    Every value is a plain JSON-able type, and every step is best-effort — an
    unresolvable host API index yields `""`, an unreadable device entry is
    skipped, and a PortAudio that cannot be asked gives `[]` rather than
    raising into a settings page.
    """
    try:
        import sounddevice as sd

        devices = list(enumerate(sd.query_devices()))
    except Exception:
        log.exception("could not enumerate the input devices")
        return []
    try:
        hostapis = list(sd.query_hostapis())
    except Exception:
        log.debug("could not resolve the host API names", exc_info=True)
        hostapis = []
    profiles: list[dict] = []
    for idx, dev in devices:
        try:
            channels = int(dev.get("max_input_channels", 0) or 0)
            if channels <= 0:
                continue
            api = dev.get("hostapi")
            hostapi = ""
            if isinstance(api, int) and 0 <= api < len(hostapis):
                hostapi = str(hostapis[api].get("name", "") or "")
            profiles.append(
                {
                    "index": idx,
                    "name": str(dev.get("name", f"Device {idx}")),
                    "hostapi": hostapi,
                    "channels": channels,
                    "samplerate": float(dev.get("default_samplerate", 0.0) or 0.0),
                }
            )
        except Exception:
            log.debug("input device %s has an unreadable profile — skipped", idx, exc_info=True)
    return profiles
