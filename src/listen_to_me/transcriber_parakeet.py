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
``transcribe`` / ``preview`` / ``loaded``) and its session CPU fallback: a
GPU provider can fail at session creation *or* only at the first ``Run()``
(broken cuDNN, device lost), and like the OpenVINO backend there is no
stable error-string contract to distinguish causes — so any failure while a
GPU provider is active forces the CPU for the session and retries once.
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
    "in Settings → Engine."
)


def _quantization(cfg_value: str) -> str | None:
    """Map the config value to onnx-asr's quantization argument (None = fp32)."""
    return None if cfg_value == "fp32" else (cfg_value or "int8")


def _download_filter(quantization: str | None):
    """Which files of MODEL_REPO a download of `quantization` fetches.

    The repo ships both variants side by side (int8 ≈ 0.7 GB next to fp32 ≈
    2.5 GB), so counting all of it would leave an int8 download stuck at a
    fifth of the bar. The variant is spelled into the file name
    (``encoder-model.int8.onnx``); the handful of shared files carry no marker
    and are counted with fp32 — a fraction of a megabyte either way.
    """

    def keep(name: str) -> bool:
        return (".int8." in name) == (quantization == "int8")

    return keep


def _download_watcher(quantization: str | None, model_dir, progress):
    """A DownloadWatcher over the folder the Parakeet model downloads into —
    the backend's own directory under a custom model folder, the Hugging Face
    cache otherwise."""
    from .progress import DownloadWatcher, hub_cache_dir, hub_repo_size

    if model_dir:
        folder = os.path.join(str(model_dir), _MODEL_DIRNAME)
    else:
        folder = hub_cache_dir(MODEL_REPO)
    return DownloadWatcher(
        folder,
        hub_repo_size(MODEL_REPO, keep=_download_filter(quantization)),
        progress,
        label=f"Downloading {MODEL_NAME}",
    )


# Short labels for the status card / log: the provider that leads the list
# is the one ONNX Runtime places the session on.
_PROVIDER_LABELS = {
    "CUDAExecutionProvider": "cuda",
    "DmlExecutionProvider": "directml",
    "CPUExecutionProvider": "cpu",
}


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
        self._providers: list[str] | None = None  # providers of the loaded session
        self._lock = threading.Lock()  # protects model loading
        self._use_lock = threading.Lock()  # serializes transcription runs
        # Like the other backends: a GPU failure forces the CPU for the rest
        # of the session, but only while the config still asks for the same
        # device — changing it in Settings retries the GPU.
        self._cpu_fallback_for: str | None = None

    @property
    def _forced_cpu(self) -> bool:
        return self._cpu_fallback_for == self.cfg["device"]

    def _current_key(self):
        return (
            self.cfg["device"],
            self.cfg["parakeet_quantization"],
            self.cfg["model_dir"],
        )

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._key == self._current_key()

    @property
    def runtime(self) -> tuple[str, str] | None:
        """(device, precision) of the loaded model — the leading execution
        provider the session was created with ("cuda" / "directml" / "cpu")
        and the ONNX variant ("int8" / "fp32"). None while nothing is loaded.
        Same contract as Transcriber.runtime."""
        if not self.loaded or not self._providers or self._key is None:
            return None
        provider = self._providers[0]
        return _PROVIDER_LABELS.get(provider, provider), _quantization(self._key[1]) or "fp32"

    # ------------------------------------------------------------ loading

    def ensure_loaded(self, notify=None, progress=None) -> None:
        """Load the Parakeet model, reloading if the settings changed.

        Downloads the ONNX model from Hugging Face on first use (into
        cfg["model_dir"] or the Hugging Face cache) and loads from disk on
        every later run — onnx-asr itself resolves offline-first, so restarts
        never re-download.

        `progress` follows the same contract as the other backends: called
        from a background thread while the download runs, and once with
        ``label=None`` when it ends.
        """
        with self._lock:
            self._ensure_loaded_locked(notify, progress)

    def _ensure_loaded_locked(self, notify=None, progress=None) -> None:
        if self._cpu_fallback_for is not None and not self._forced_cpu:
            # The config moved away from the device that failed: drop the
            # marker so a later RETURN to it retries the GPU instead of
            # silently re-forcing the CPU.
            self._cpu_fallback_for = None
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
        providers = ["CPUExecutionProvider"] if self._forced_cpu else _resolve_providers(device)
        if device == "cuda" and not self._forced_cpu and "CUDAExecutionProvider" not in providers:
            # The default [parakeet] extra installs the CPU-only onnxruntime
            # wheel — an explicit CUDA choice silently running on the CPU
            # forever is exactly the failure mode this app must not have.
            log.warning("CUDA requested, but this onnxruntime build offers no CUDA provider")
            if notify is not None:
                notify(
                    "Device = CUDA is set, but the installed onnxruntime has "
                    "no CUDA support — Parakeet runs on the CPU. Install "
                    "onnxruntime-gpu, or set Device = CPU in Settings → "
                    "Engine.",
                    True,  # force: important even when notifications are off
                )
        def load(chosen):
            return onnx_asr.load_model(
                MODEL_NAME,
                path,
                quantization=quantization,
                providers=chosen,
            )

        try:
            if cached or progress is None:
                model = load(providers)
            else:
                # Only the downloading load is watched: onnx-asr fetches the
                # files itself, so the bytes are counted where they land.
                with _download_watcher(quantization, model_dir, progress):
                    model = load(providers)
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
                    "libraries, or set Device = CPU in Settings → Engine.",
                    True,  # force: important even when notifications are off
                )
            providers = ["CPUExecutionProvider"]
            # No watcher: the files are on disk by the time a provider fails.
            model = load(providers)
        self._model = model
        self._key = key
        self._providers = providers
        log.info(
            "parakeet model %s: %s / %s / providers=%s (dir=%s)",
            "loaded from cache" if cached else "downloaded",
            MODEL_NAME,
            quantization or "fp32",
            providers,
            model_dir,
        )

    # ----------------------------------------------------------- decoding

    def transcribe(self, audio, notify=None, progress=None) -> str:
        self.ensure_loaded(notify=notify, progress=progress)
        try:
            text = self._recognize(audio)
        except Exception as exc:
            # ONNX Runtime surfaces GPU failures (broken cuDNN, device lost)
            # at Run(), not only at session creation — reload on the CPU and
            # retry once, mirroring the other backends.
            if not self._recover_on_cpu(exc, notify):
                raise
            text = self._recognize(audio)
        log.info("transcribed %.1fs -> %d chars (parakeet)", len(audio) / SAMPLE_RATE, len(text))
        return text

    def _recognize(self, audio) -> str:
        with self._use_lock:
            model = self._model
            if model is None:
                raise RuntimeError("Parakeet model is not loaded")
            return str(model.recognize(audio, sample_rate=SAMPLE_RATE)).strip()

    def _recover_on_cpu(self, exc: Exception, notify) -> bool:
        """After an inference failure while a GPU provider was active, force
        the CPU for this session and reload. Returns True when the caller
        should retry, False (already CPU-only) when it should re-raise."""
        with self._lock:
            if self._forced_cpu or not self._providers or self._providers == [
                "CPUExecutionProvider"
            ]:
                return False
            log.warning(
                "Parakeet inference failed on %s (%s) — using the CPU this session",
                self._providers[0],
                exc,
            )
            self._cpu_fallback_for = self.cfg["device"]
            self._model = None
            self._key = None
            if notify is not None:
                notify(
                    "GPU acceleration unavailable for Parakeet — switched to "
                    "CPU for this session. Check the NVIDIA driver/CUDA "
                    "libraries, or set Device = CPU in Settings → Engine.",
                    True,  # force: important even when notifications are off
                )
            self._ensure_loaded_locked(None)
        return True

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
            # Snapshot the model like the other backends: a concurrent reload
            # may swap self._model between the loaded-check and here — decoding
            # on the previous instance is fine, dereferencing None would not be.
            model = self._model
            if model is None:
                return None
            audio = audio[-_PREVIEW_WINDOW_SECONDS * SAMPLE_RATE :]
            return str(model.recognize(audio, sample_rate=SAMPLE_RATE)).strip()
        finally:
            self._use_lock.release()
