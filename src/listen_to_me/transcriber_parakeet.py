"""Local speech-to-text via NVIDIA Parakeet TDT (onnx-asr / ONNX Runtime).

The optional third transcription backend (``cfg["backend"] == "parakeet"``).
It runs ``nvidia/parakeet-tdt-0.6b-v3`` — a 25-language transducer model
(German included, CC-BY-4.0) that decodes an order of magnitude faster than
the Whisper large-v3-turbo class at comparable accuracy, with punctuation,
capitalization and automatic language detection built in. Because it is not
a Whisper model, the Whisper-specific options (model preset, language,
initial prompt, VAD filter, beam size, compute type) do not apply here.

Requires the optional ``onnx-asr`` package (``pip install "onnx-asr[cpu,hub]"``,
or the ``[parakeet]`` extra); imported lazily so the app runs without it as
long as the backend isn't selected. Mirrors the public surface of
:class:`listen_to_me.transcriber.Transcriber` (``ensure_loaded`` /
``transcribe`` / ``preview`` / ``loaded``). GPU degradation is simpler than
the other backends: the ONNX Runtime provider list always ends with the CPU
provider, so a missing/broken CUDA setup falls back per session load rather
than needing an error-string contract.
"""

from __future__ import annotations

import logging
import os
import threading

from .audio import SAMPLE_RATE
from .transcriber import _PREVIEW_WINDOW_SECONDS

log = logging.getLogger(__name__)

# onnx-asr preset name and the Hugging Face repo it resolves to. The repo id
# is needed separately for the offline cache probe (and the status card).
MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
MODEL_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"

# Subdirectory used below cfg["model_dir"] (when set) so the download never
# mixes with the CT2/OpenVINO model folders in the same directory.
_MODEL_DIRNAME = "parakeet-tdt-0.6b-v3-onnx"

_INSTALL_HINT = (
    "The Parakeet backend needs the optional onnx-asr package. Install it "
    'with: pip install "onnx-asr[cpu,hub]" — or set Backend = faster-whisper '
    "in Settings → Whisper."
)


def _quantization(cfg_value: str) -> str | None:
    """Map the config value to onnx-asr's quantization argument (None = fp32)."""
    return None if cfg_value == "fp32" else (cfg_value or "int8")


def _resolve_providers(device: str) -> list[str]:
    """ONNX Runtime execution providers for the configured device.

    "auto" prefers CUDA, then DirectML (Windows), then the CPU. Only providers
    the installed onnxruntime build actually offers are requested, and the CPU
    provider is always appended, so a missing GPU (or a CPU-only wheel) means
    a slower run — never an error.
    """
    try:
        import onnxruntime

        available = set(onnxruntime.get_available_providers())
    except Exception:
        log.debug("onnxruntime provider probe failed", exc_info=True)
        available = set()
    preferred = {
        "cuda": ["CUDAExecutionProvider"],
        "cpu": [],
    }.get(device, ["CUDAExecutionProvider", "DmlExecutionProvider"])  # "auto"
    providers: list[str] = [p for p in preferred if p in available]
    providers.append("CPUExecutionProvider")
    return providers


def _model_is_cached(quantization: str | None, model_dir) -> bool:
    """Whether the Parakeet model is already on disk, so loading won't download.

    With a custom model_dir the backend downloads into a subdirectory it fully
    controls, so that directory existing is the answer. Otherwise probe the
    Hugging Face cache offline for the encoder of the selected quantization —
    the file the download could least plausibly be missing. Any uncertainty
    counts as "not cached", same contract as the other backends.
    """
    try:
        if model_dir:
            return os.path.isdir(os.path.join(str(model_dir), _MODEL_DIRNAME))
        from huggingface_hub import hf_hub_download

        suffix = f".{quantization}" if quantization else ""
        hf_hub_download(MODEL_REPO, f"encoder-model{suffix}.onnx", local_files_only=True)
        return True
    except Exception:
        return False


class ParakeetTranscriber:
    backend = "parakeet"

    def __init__(self, cfg):
        self.cfg = cfg
        self._model = None
        self._key = None
        self._lock = threading.Lock()  # protects model loading
        self._use_lock = threading.Lock()  # serializes transcription runs

    def _current_key(self):
        return (
            self.cfg["device"],
            self.cfg["parakeet_quantization"],
            self.cfg["model_dir"],
        )

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._key == self._current_key()

    # ------------------------------------------------------------ loading

    def ensure_loaded(self, notify=None) -> None:
        """Load the Parakeet model, reloading if the settings changed.

        Downloads the ONNX model from Hugging Face on first use (into
        cfg["model_dir"] or the Hugging Face cache) and loads from disk on
        every later run — onnx-asr itself resolves offline-first, so restarts
        never re-download.
        """
        with self._lock:
            self._ensure_loaded_locked(notify)

    def _ensure_loaded_locked(self, notify=None) -> None:
        key = self._current_key()
        if self._model is not None and key == self._key:
            return
        device, quant_cfg, model_dir = key
        quantization = _quantization(quant_cfg)
        try:
            import onnx_asr
        except ImportError as exc:
            raise RuntimeError(_INSTALL_HINT) from exc

        cached = _model_is_cached(quantization, model_dir)
        if notify is not None:
            if cached:
                notify(f"Loading Parakeet model '{MODEL_NAME}'…")
            else:
                notify(
                    f"Downloading Parakeet model '{MODEL_NAME}' — "
                    "one-time setup, this can take a few minutes."
                )
        path = os.path.join(str(model_dir), _MODEL_DIRNAME) if model_dir else None
        providers = _resolve_providers(device)
        try:
            model = onnx_asr.load_model(
                MODEL_NAME,
                path,
                quantization=quantization,
                providers=providers,
            )
        except FileNotFoundError:
            # onnx-asr treats an *existing* custom model directory as a
            # complete offline copy — an interrupted first download leaves it
            # permanently incomplete. Make the fix obvious instead of
            # surfacing a bare "file not found".
            if path is not None and os.path.isdir(path):
                raise RuntimeError(
                    f"The Parakeet model folder '{path}' is incomplete "
                    "(interrupted download?) — delete that folder and try "
                    "again to re-download."
                ) from None
            raise
        except Exception as exc:
            # A GPU provider that is available but broken (driver/DLL) can
            # still fail at session creation. Retry once on the CPU alone so
            # transcription keeps working — mirroring the other backends.
            if len(providers) <= 1:
                raise
            log.warning(
                "Parakeet load failed on %s (%s) — using the CPU this session",
                providers[0],
                exc,
            )
            if notify is not None:
                notify(
                    "GPU acceleration unavailable for Parakeet — switched to "
                    "CPU for this session. Check the NVIDIA driver/CUDA "
                    "libraries, or set Device = CPU in Settings → Whisper.",
                    True,  # force: important even when notifications are off
                )
            model = onnx_asr.load_model(
                MODEL_NAME,
                path,
                quantization=quantization,
                providers=["CPUExecutionProvider"],
            )
        self._model = model
        self._key = key
        log.info(
            "parakeet model %s: %s / %s / providers=%s (dir=%s)",
            "loaded from cache" if cached else "downloaded",
            MODEL_NAME,
            quantization or "fp32",
            providers,
            model_dir,
        )

    # ----------------------------------------------------------- decoding

    def transcribe(self, audio, notify=None) -> str:
        self.ensure_loaded(notify=notify)
        with self._use_lock:
            model = self._model
            if model is None:
                raise RuntimeError("Parakeet model is not loaded")
            text = str(model.recognize(audio, sample_rate=SAMPLE_RATE)).strip()
        log.info("transcribed %.1fs -> %d chars (parakeet)", len(audio) / SAMPLE_RATE, len(text))
        return text

    def preview(self, audio) -> str | None:
        """Fast transcription of the tail of an ongoing recording — same
        contract as the faster-whisper preview: None when the model isn't
        loaded yet or another transcription is running. There is no cheaper
        decoding mode to drop to; the model is fast enough as it is."""
        if not self.loaded:
            return None
        if not self._use_lock.acquire(blocking=False):
            return None
        try:
            audio = audio[-_PREVIEW_WINDOW_SECONDS * SAMPLE_RATE :]
            return str(self._model.recognize(audio, sample_rate=SAMPLE_RATE)).strip()
        finally:
            self._use_lock.release()
