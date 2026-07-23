"""Local speech-to-text on Intel hardware via OpenVINO GenAI (WhisperPipeline).

The optional second transcription backend (``cfg["backend"] == "openvino"``),
covering Intel CPUs, integrated/discrete GPUs (Xe / Arc) and NPUs ("AI Boost"
in Core Ultra). It loads pre-converted OpenVINO IR models published by the
``OpenVINO`` organisation on Hugging Face, so no torch/optimum conversion ever
happens at runtime — a plain download, like the faster-whisper backend.

Requires the optional ``openvino-genai`` package (``pip install openvino-genai``,
or the ``[openvino]`` extra); everything here imports it lazily so
the app runs without it as long as the backend isn't selected. Mirrors the
public surface of :class:`listen_to_me.transcriber.Transcriber` (``ensure_loaded``
/ ``transcribe`` / ``preview`` / ``loaded``) and its session CPU fallback.
"""

from __future__ import annotations

import logging
import os
import threading

from .audio import SAMPLE_RATE
from .choices import GERMAN_TURBO_CT2
from .transcriber import _PREVIEW_WINDOW_SECONDS

log = logging.getLogger(__name__)

# Model presets that exist as CTranslate2 conversions but were never published
# by the OpenVINO organisation — mapping them would 404 on download.
_UNAVAILABLE_PRESETS = ("distil-small.en", "distil-medium.en", "distil-large-v3.5")

_INSTALL_HINT = (
    "The OpenVINO backend needs the optional openvino-genai package. "
    "Install it with: pip install openvino-genai — or set "
    "Backend = faster-whisper in Settings → Whisper."
)


def openvino_model_repo(model: str, precision: str) -> str:
    """Map a model preset + precision to its pre-converted Hugging Face repo id,
    e.g. ("small", "int8") → "OpenVINO/whisper-small-int8-ov".

    A value containing "/" is treated as an explicit repo id (or a local path)
    and passed through verbatim, so any OpenVINO IR model can be used. Raises
    ValueError for the presets that have no OpenVINO conversion.
    """
    if model == GERMAN_TURBO_CT2:
        # The German preset is a CTranslate2 conversion — passing it through
        # verbatim would download a model this backend cannot load.
        raise ValueError(
            "The German fine-tuned model has no OpenVINO conversion — switch "
            "Backend to faster-whisper in Settings → Whisper to use it."
        )
    if "/" in model or os.sep in model:
        return model
    if model in _UNAVAILABLE_PRESETS:
        raise ValueError(
            f"The model '{model}' has no OpenVINO conversion — pick another model "
            "(e.g. small or distil-large-v3), or switch back to the faster-whisper "
            "backend in Settings → Whisper."
        )
    base = "distil-whisper-large-v3" if model == "distil-large-v3" else f"whisper-{model}"
    return f"OpenVINO/{base}-{precision}-ov"


def _model_is_cached(repo: str, model_dir) -> bool:
    """Whether the OpenVINO model is already on disk (local dir or a complete
    Hugging Face snapshot), so loading it won't download. Any uncertainty counts
    as "not cached" — same contract as the faster-whisper cache probe."""
    try:
        if os.path.isdir(repo):
            return True
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo,
            local_files_only=True,
            cache_dir=str(model_dir) if model_dir else None,
        )
        return True
    except Exception:
        return False


class OpenVinoTranscriber:
    backend = "openvino"

    def __init__(self, cfg):
        self.cfg = cfg
        self._pipe = None
        self._key = None
        self._device: str | None = None  # device the pipeline actually loaded on
        self._lock = threading.Lock()  # protects pipeline loading
        self._use_lock = threading.Lock()  # serializes transcription runs
        # Like the faster-whisper backend: when loading/running on a GPU/NPU
        # fails, we force the CPU for the session — but only while the config
        # still asks for that same (device, precision) setup, so changing
        # either in Settings retries the device.
        self._cpu_fallback_for: tuple | None = None

    # ------------------------------------------------------------- keying

    @property
    def _forced_cpu(self) -> bool:
        """Whether the session CPU fallback currently applies. True only while
        the configured device/precision still match the setup that failed;
        editing either in Settings makes this False again (a fresh retry).
        Precision is part of the key because GPU/NPU data-type support varies —
        an int4 model can fail on a device where the int8 one runs."""
        return self._cpu_fallback_for == (
            self.cfg["openvino_device"],
            self.cfg["openvino_precision"],
        )

    def _current_key(self):
        # Evaluate the fallback once so the resulting device stays consistent
        # even if the config is edited concurrently (no torn key) — the same
        # pattern as the faster-whisper backend.
        forced = self._forced_cpu
        device = "cpu" if forced else self.cfg["openvino_device"]
        return (
            self.cfg["model"],
            self.cfg["openvino_precision"],
            device,
            self.cfg["model_dir"],
        )

    @property
    def loaded(self) -> bool:
        return self._pipe is not None and self._key == self._current_key()

    def _resolve_device(self, configured: str) -> str:
        """Turn the configured device into an OpenVINO device string.

        "auto" prefers a GPU over the NPU over the CPU — the GPU is usually the
        fastest of the three, the NPU the most power-efficient. Probing failures
        fall back to the CPU rather than raising."""
        if configured != "auto":
            return configured.upper()
        try:
            import openvino

            available = openvino.Core().available_devices  # e.g. ["CPU","GPU","NPU"]
            for pick in ("GPU", "NPU"):
                # Multi-device systems enumerate as "GPU.0", "GPU.1", …
                if any(dev == pick or dev.startswith(pick + ".") for dev in available):
                    return pick
        except Exception:
            log.exception("OpenVINO device probe failed — using the CPU")
        return "CPU"

    # ------------------------------------------------------------ loading

    def ensure_loaded(self, notify=None) -> None:
        """Load the Whisper pipeline, reloading if the settings changed.

        Downloads the pre-converted OpenVINO model from Hugging Face on first
        use (into cfg["model_dir"] or the Hugging Face cache) and loads from
        that cache on every later run. A failure to load on the GPU/NPU falls
        back to the CPU for this session and retries, so transcription keeps
        working — mirroring the faster-whisper CUDA fallback."""
        with self._lock:
            self._ensure_loaded_locked(notify)

    def _ensure_loaded_locked(self, notify=None) -> None:
        key = self._current_key()
        if self._pipe is not None and key == self._key:
            return
        model_name, precision, device_cfg, model_dir = key
        repo = openvino_model_repo(model_name, precision)  # ValueError is actionable
        try:
            import openvino_genai
        except ImportError as exc:
            raise RuntimeError(_INSTALL_HINT) from exc

        cached = _model_is_cached(repo, model_dir)
        if notify is not None:
            if cached:
                notify(f"Loading Whisper model '{repo}'…")
            else:
                notify(
                    f"Downloading Whisper model '{repo}' — "
                    "one-time setup, this can take a few minutes."
                )
        if os.path.isdir(repo):
            path = repo
        else:
            from huggingface_hub import snapshot_download

            # Already cached → resolve straight from disk, skipping the network
            # revision check so restarts are fast and work fully offline.
            path = snapshot_download(
                repo,
                cache_dir=str(model_dir) if model_dir else None,
                local_files_only=cached,
            )
        device = self._resolve_device(device_cfg)
        try:
            self._pipe = openvino_genai.WhisperPipeline(path, device)
        except Exception as exc:
            if self._maybe_force_cpu(device, exc, notify):
                self._ensure_loaded_locked(None)  # retry on the CPU, no re-notify
                return
            raise
        self._device = device
        self._key = key
        log.info(
            "openvino whisper model %s: %s on %s (dir=%s)",
            "loaded from cache" if cached else "downloaded",
            repo,
            device,
            model_dir,
        )

    def _maybe_force_cpu(self, device: str, exc: Exception, notify) -> bool:
        """Handle a pipeline load/inference failure.

        The model files are already on disk when the pipeline is constructed, so
        a failure here means the device could not compile/run the model (missing
        driver, unsupported hardware, out of device memory). Unlike CUDA there
        is no stable error-string contract to distinguish causes, so any failure
        on a GPU/NPU forces the CPU for the rest of the session; on the CPU the
        error is a real one and is re-raised by the caller."""
        if self._forced_cpu or device == "CPU":
            return False
        log.warning("OpenVINO %s unavailable (%s) — using the CPU this session", device, exc)
        self._cpu_fallback_for = (
            self.cfg["openvino_device"],
            self.cfg["openvino_precision"],
        )
        self._pipe = None
        self._key = None
        if notify is not None:
            notify(
                f"Intel {device} acceleration unavailable — switched to CPU for "
                "this session. Check your Intel GPU/NPU driver, or set "
                "Intel device = CPU in Settings → Whisper.",
                True,  # force: important even when notifications are off
            )
        return True

    # ----------------------------------------------------------- decoding

    def _decode(self, audio) -> str:
        """Run the pipeline on `audio` and return the text. Caller holds _use_lock."""
        pipe = self._pipe
        if pipe is None:
            raise RuntimeError("Whisper model is not loaded")
        config = pipe.get_generation_config()
        language = self.cfg["language"]
        if language not in ("", "auto"):
            config.language = f"<|{language}|>"
            config.task = "transcribe"
        prompt = self.cfg["initial_prompt"]
        if prompt and hasattr(config, "initial_prompt"):
            config.initial_prompt = prompt
        # The pipeline chunks audio longer than 30 s internally (sliding
        # window); it expects a plain float list at 16 kHz, which is exactly
        # what the Recorder captures.
        result = pipe.generate(audio.tolist(), config)
        texts = getattr(result, "texts", None)
        return (texts[0] if texts else str(result)).strip()

    def transcribe(self, audio, notify=None) -> str:
        self.ensure_loaded(notify=notify)
        try:
            with self._use_lock:
                text = self._decode(audio)
        except Exception as exc:
            if not self._recover_on_cpu(exc, notify):
                raise
            with self._use_lock:
                text = self._decode(audio)
        log.info("transcribed %.1fs -> %d chars (openvino)", len(audio) / SAMPLE_RATE, len(text))
        return text

    def _recover_on_cpu(self, exc: Exception, notify) -> bool:
        """After an inference failure on a GPU/NPU, force the CPU and reload
        there. Returns True when the caller should retry, False to re-raise.

        Judges the failure by the device the pipeline actually loaded on — a
        fresh probe could no longer list a device that just died and would skip
        the fallback, leaving the session stuck on a dead pipeline (the CT2
        backend's _effective_device serves the same purpose)."""
        with self._lock:
            if not self._maybe_force_cpu(self._device or "CPU", exc, notify):
                return False
            self._ensure_loaded_locked(notify)
        return True

    def preview(self, audio) -> str | None:
        """Fast transcription of the tail of an ongoing recording — same
        contract as the faster-whisper preview: None when the model isn't
        loaded yet or another transcription is running."""
        if not self.loaded:
            return None
        if not self._use_lock.acquire(blocking=False):
            return None
        try:
            audio = audio[-_PREVIEW_WINDOW_SECONDS * SAMPLE_RATE :]
            return self._decode(audio)
        finally:
            self._use_lock.release()
