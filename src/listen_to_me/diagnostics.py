"""Self-diagnosis actions for the Settings window: model download, microphone
test, end-to-end transcription test and the hardware/model status probes
behind the Whisper page's status card.

Qt-free on purpose: everything here runs on a worker thread and reports back
through plain callables, which the Settings window marshals onto the Qt main
thread via signals (never touch Qt from here). Heavy deps (numpy, sounddevice,
faster-whisper/openvino) are imported lazily inside the functions, matching
the rest of the codebase.
"""

from __future__ import annotations

import logging
import time

from .audio import SAMPLE_RATE, Recorder

log = logging.getLogger(__name__)

# Peak levels (float32 full scale = 1.0) separating "no signal at all" from a
# working-but-too-quiet microphone: ~-46 dBFS and ~-26 dBFS. Normal speech at
# a sane input volume peaks well above 0.05.
_SILENT_PEAK = 0.005
_QUIET_PEAK = 0.05

# How often the level callback fires / the cancel flag is polled while a test
# records.
_LEVEL_INTERVAL_S = 0.1


def probe_cuda() -> dict:
    """Whether an NVIDIA CUDA GPU is usable by the faster-whisper backend.

    Returns ``{"available": bool, "count": int, "error": str | None}``. Asks
    CTranslate2 (the engine that would actually run the model) instead of any
    other CUDA binding, so the answer matches what transcription will do. Never
    raises — a missing ctranslate2 or a broken driver is reported as an error
    string so the status card can show *why* nothing was found.
    """
    try:
        import ctranslate2

        count = int(ctranslate2.get_cuda_device_count())
        return {"available": count > 0, "count": count, "error": None}
    except Exception as exc:
        log.debug("CUDA probe failed", exc_info=True)
        return {"available": False, "count": 0, "error": str(exc)}


def probe_openvino() -> dict:
    """Whether the optional OpenVINO backend is installed and which Intel
    devices it sees.

    Returns ``{"installed": bool, "devices": list, "error": str | None}`` where
    each device is ``{"device": "GPU", "name": "Intel(R) Arc(TM) …"}``. The
    install check imports openvino_genai (what the backend actually needs, not
    just openvino); the device list comes from the OpenVINO core so the user
    can see whether their GPU/NPU driver is picked up. Never raises.
    """
    try:
        import openvino_genai  # noqa: F401 — presence check only
    except ImportError:
        return {"installed": False, "devices": [], "error": None}
    except Exception as exc:
        log.debug("openvino_genai probe failed", exc_info=True)
        return {"installed": False, "devices": [], "error": str(exc)}
    devices: list[dict] = []
    error: str | None = None
    try:
        import openvino

        core = openvino.Core()
        for dev in core.available_devices:
            try:
                name = str(core.get_property(dev, "FULL_DEVICE_NAME")).strip()
            except Exception:
                name = ""
            devices.append({"device": str(dev), "name": name})
    except Exception as exc:
        log.debug("OpenVINO device probe failed", exc_info=True)
        error = str(exc)
    return {"installed": True, "devices": devices, "error": error}


def model_cache_status(snapshot: dict) -> dict:
    """Whether the model the snapshot describes is already on disk (so loading
    it won't download). Disk-only, never touches the network, never raises.

    Returns ``{"target": str, "cached": bool, "error": str | None}`` — target
    is what would be fetched (the OpenVINO Hugging Face repo id for that
    backend, the model id otherwise); error carries the "this preset has no
    OpenVINO conversion" message so the status card can warn before a download
    is even attempted.
    """
    model = str(snapshot.get("model") or "")
    model_dir = snapshot.get("model_dir")
    try:
        if snapshot.get("backend") == "openvino":
            from .transcriber_openvino import _model_is_cached, openvino_model_repo

            repo = openvino_model_repo(model, snapshot.get("openvino_precision") or "int8")
            return {"target": repo, "cached": _model_is_cached(repo, model_dir), "error": None}
        from .transcriber import _model_is_cached

        return {"target": model, "cached": _model_is_cached(model, model_dir), "error": None}
    except Exception as exc:  # e.g. a preset without an OpenVINO conversion
        return {"target": model, "cached": False, "error": str(exc)}


def hardware_status(snapshot: dict) -> dict:
    """Everything the Settings status card shows, in one worker-thread call:
    CUDA availability, OpenVINO install/devices and the model cache state."""
    return {
        "cuda": probe_cuda(),
        "openvino": probe_openvino(),
        "model": model_cache_status(snapshot),
    }


def record_clip(device, seconds: float, on_level=None, is_cancelled=None):
    """Record ``seconds`` of audio and return it as a 1-D float32 numpy array.

    ``on_level`` (optional) receives the recent peak (0.0–1.0) every ~100 ms,
    called from this worker thread. ``is_cancelled`` (optional) is polled at
    the same rate; returning True stops the recording early.
    """
    import numpy as np

    recorder = Recorder()
    try:
        # start() inside the try: if the stream opens but starting it fails,
        # the finally still runs stop(), which closes the opened handle.
        recorder.start(device=device, max_seconds=max(1, int(round(seconds))))
        # round() before int(): 5.0 / 0.1 is 49.99… in floats — plain int()
        # would silently record one tick (0.1 s) short.
        for _ in range(int(round(seconds / _LEVEL_INTERVAL_S))):
            if is_cancelled is not None and is_cancelled():
                break
            time.sleep(_LEVEL_INTERVAL_S)
            if on_level is not None:
                tail = recorder.snapshot(max_frames=SAMPLE_RATE // 5)
                peak = float(np.max(np.abs(tail))) if len(tail) else 0.0
                on_level(min(1.0, peak))
    finally:
        audio = recorder.stop()
    return audio


def clip_stats(audio) -> dict:
    """Peak/RMS statistics and a verdict for a recorded clip.

    The verdict classifies what the microphone test heard: "silent" (no signal
    at all — wrong device, OS permission, hardware mute), "quiet" (a signal
    arrives but is too low for reliable recognition) or "ok".
    """
    import numpy as np

    seconds = len(audio) / SAMPLE_RATE
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
    if peak < _SILENT_PEAK:
        verdict = "silent"
    elif peak < _QUIET_PEAK:
        verdict = "quiet"
    else:
        verdict = "ok"
    return {"peak": peak, "rms": rms, "seconds": seconds, "verdict": verdict}


class DiagnosticsEngine:
    """Runs the Settings-window diagnostics against a *snapshot* of the UI
    values — a plain dict holding exactly the config keys the transcribers
    read — so tests exercise what is currently entered, saved or not.

    The transcriber built for a snapshot is cached and reused while the
    snapshot stays unchanged, so "Download model" followed by "Test
    transcription" loads the model only once. The Settings window runs at most
    one diagnostic at a time (worker threads are serialized behind a busy
    flag), so there is no internal locking here.
    """

    def __init__(self):
        self._transcriber = None
        self._key: tuple | None = None

    def _transcriber_for(self, snapshot: dict):
        from .transcriber import create_transcriber

        key = tuple(sorted(snapshot.items()))
        if self._transcriber is None or key != self._key:
            # The snapshot dict acts as the transcriber's cfg: both backends
            # only ever read cfg["key"], which a plain dict provides.
            self._transcriber = create_transcriber(dict(snapshot))
            self._key = key
        return self._transcriber

    def prepare_model(self, snapshot: dict, notify=None) -> str:
        """Download (first use) and load the model the snapshot describes.
        Returns a short human-readable success message."""
        transcriber = self._transcriber_for(snapshot)
        transcriber.ensure_loaded(notify=notify)
        return (
            f"Model '{snapshot['model']}' is downloaded and ready "
            f"({transcriber.backend} backend)."
        )

    def mic_test(self, device, seconds: float = 3.0, on_level=None, is_cancelled=None) -> dict:
        """Record a short clip from ``device`` and return its clip_stats()."""
        audio = record_clip(device, seconds, on_level=on_level, is_cancelled=is_cancelled)
        return clip_stats(audio)

    def transcription_test(
        self,
        snapshot: dict,
        device,
        seconds: float = 5.0,
        on_status=None,
        on_level=None,
        is_cancelled=None,
    ) -> str:
        """End-to-end check: load the model, record a short clip and
        transcribe it. Returns the recognized text ("" when cancelled or
        nothing was understood). Nothing is inserted or written to history."""

        def status(message) -> None:
            if on_status is not None:
                on_status(str(message))

        transcriber = self._transcriber_for(snapshot)
        # The transcribers call notify(message[, force]); route it to status.
        transcriber.ensure_loaded(notify=lambda message, force=False: status(message))
        if is_cancelled is not None and is_cancelled():
            return ""
        status(f"Recording {seconds:.0f} s — speak now…")
        audio = record_clip(device, seconds, on_level=on_level, is_cancelled=is_cancelled)
        if is_cancelled is not None and is_cancelled():
            return ""
        if len(audio) / SAMPLE_RATE < 0.3:
            raise RuntimeError("the test recording came back empty — microphone problem?")
        status("Transcribing…")
        return transcriber.transcribe(audio, notify=lambda message, force=False: status(message))
