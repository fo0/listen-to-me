"""Local speech-to-text via NVIDIA Parakeet TDT (onnx-asr / ONNX Runtime).

The optional third transcription backend (``cfg["backend"] == "parakeet"``).
It runs one of the Parakeet TDT 0.6B exports in ``MODELS`` (picked by
``cfg["parakeet_model"]``): NVIDIA's ``parakeet-tdt-0.6b-v3`` — a 25-language
transducer model (German included, CC-BY-4.0) that decodes an order of
magnitude faster than the Whisper large-v3-turbo class at comparable accuracy,
with punctuation, capitalization and automatic language detection built in —
or primeline's German fine-tune of it, same architecture and speed. Because
neither is a Whisper model, the Whisper-specific options (model preset,
language, initial prompt, VAD filter, beam size, compute type) do not apply
here.

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
from .parakeet_models import (
    MODELS,
    ParakeetModel,
    download_filter,
    fetch_pinned,
    missing_files,
    model_path,
    parakeet_model,
)
from .transcriber import _PREVIEW_WINDOW_SECONDS

log = logging.getLogger(__name__)

_INSTALL_HINT = (
    "The Parakeet backend needs the optional onnx-asr package. Install it "
    'with: pip install "onnx-asr[cpu,hub]" — or set Backend = faster-whisper '
    "in Settings → Engine."
)


def _quantization(cfg_value: str) -> str | None:
    """Map the config value to onnx-asr's quantization argument (None = fp32)."""
    return None if cfg_value == "fp32" else (cfg_value or "int8")


def _download_watcher(model: ParakeetModel, quantization: str | None, model_dir, progress):
    """A DownloadWatcher over the folder `model` downloads into — the
    backend's own directory under a custom model folder, the Hugging Face
    cache otherwise. The total is read at the revision that is downloaded:
    a pinned commit's files are not necessarily the ones on main."""
    from .progress import DownloadWatcher, hub_cache_dir, hub_repo_size

    folder = model_path(model, model_dir) or hub_cache_dir(model.repo)
    return DownloadWatcher(
        folder,
        hub_repo_size(model.repo, keep=download_filter(quantization), revision=model.revision),
        progress,
        label=f"Downloading {model.title}",
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


def _preload_cuda_dlls() -> None:
    """Let ONNX Runtime find pip-installed CUDA / cuDNN libraries.

    onnxruntime-gpu bundles no CUDA. On Windows the DLLs must be on PATH —
    unless ``onnxruntime.preload_dlls()`` (ORT ≥ 1.21) loads the copies the
    ``nvidia-*`` wheels install first, which is the one torch-free way to make
    ``pip install "onnxruntime-gpu[cuda,cudnn]"`` just work. Without it the
    CUDA provider fails at session creation with a missing-DLL error that the
    session fallback then blames on the GPU. Older builds lack the function
    and every failure here is a debug line: the provider list already decides
    what runs, this only improves its odds.
    """
    try:
        import onnxruntime

        preload = getattr(onnxruntime, "preload_dlls", None)
        if preload is not None:
            preload(cuda=True, cudnn=True)
    except Exception:
        log.debug("onnxruntime.preload_dlls failed", exc_info=True)


def _model_is_cached(model: ParakeetModel, quantization: str | None, model_dir) -> bool:
    """Whether `model` is already on disk, so loading won't download.

    An onnx-asr preset in a custom model_dir downloads into a subdirectory the
    backend fully controls, so that directory existing is the answer (onnx-asr
    itself treats it that way). Otherwise probe the Hugging Face cache offline
    for the encoder of the selected quantization — the file the download could
    least plausibly be missing. A pinned model is fetched by this module, so
    every file of the quantization is checked, in its folder or in the cached
    snapshot of its commit. Any uncertainty counts as "not cached", same
    contract as the other backends.
    """
    try:
        path = model_path(model, model_dir)
        if model.revision is not None:
            folder = path or fetch_pinned(model, quantization, None, offline=True)
            return not missing_files(folder, quantization)
        if path is not None:
            return os.path.isdir(path)
        from huggingface_hub import hf_hub_download

        suffix = f".{quantization}" if quantization else ""
        hf_hub_download(model.repo, f"encoder-model{suffix}.onnx", local_files_only=True)
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
        # The model last: device and quantization keep the indices that
        # `runtime` and the session fallback read. Normalised through the
        # registry, so an unknown value and the default share one key.
        return (
            self.cfg["device"],
            self.cfg["parakeet_quantization"],
            self.cfg["model_dir"],
            parakeet_model(self.cfg["parakeet_model"]).id,
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
        every later run — onnx-asr resolves its presets offline-first, and a
        pinned model is fetched with ``local_files_only`` once it is cached,
        so restarts never re-download or even ask the network.

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
        device, quant_cfg, model_dir, model_id = key
        spec = MODELS[model_id]
        quantization = _quantization(quant_cfg)
        try:
            import onnx_asr
        except ImportError as exc:
            raise RuntimeError(_INSTALL_HINT) from exc

        cached = _model_is_cached(spec, quantization, model_dir)
        if notify is not None:
            if cached:
                notify(f"Loading the Parakeet model '{spec.title}'…")
            else:
                notify(
                    f"Downloading the Parakeet model '{spec.title}' — "
                    "one-time setup, this can take a few minutes."
                )
        path = model_path(spec, model_dir)
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
        if "CUDAExecutionProvider" in providers:
            _preload_cuda_dlls()

        # Where onnx-asr reads the model from: a preset's own folder (None =
        # onnx-asr's lookup in the HF cache), or the pinned download's folder.
        where = path
        watch = not cached and progress is not None

        def load(chosen):
            return onnx_asr.load_model(
                spec.onnx_asr_model,
                where,
                quantization=quantization,
                providers=chosen,
            )

        if spec.revision is not None:
            # A pinned model is this module's own download, which onnx-asr
            # then only reads. Done ahead of the session fallback below on
            # purpose: a download that fails is no GPU problem.
            if watch:
                with _download_watcher(spec, quantization, model_dir, progress):
                    where = fetch_pinned(spec, quantization, path, offline=cached)
            else:
                where = fetch_pinned(spec, quantization, path, offline=cached)
            watch = False  # on disk now — the load below fetches nothing
        try:
            if not watch:
                model = load(providers)
            else:
                # Only the downloading load is watched: onnx-asr fetches its
                # presets itself, so the bytes are counted where they land.
                with _download_watcher(spec, quantization, model_dir, progress):
                    model = load(providers)
        except FileNotFoundError:
            # onnx-asr treats an *existing* custom model directory as a
            # complete offline copy — an interrupted first download leaves it
            # permanently incomplete. Make the fix obvious instead of
            # surfacing a bare "file not found". (A pinned model's folder is
            # completed by fetch_pinned instead, which names what is missing.)
            if spec.revision is None and path is not None and os.path.isdir(path):
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
            spec.id,
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
