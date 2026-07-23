"""Local speech-to-text via faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import os
import threading

from .audio import SAMPLE_RATE

log = logging.getLogger(__name__)

# The live preview only transcribes the most recent part of the recording so
# each pass stays cheap even for long recordings.
_PREVIEW_WINDOW_SECONDS = 30

# Substrings that mark the NVIDIA CUDA GPU being unusable — a missing/unloadable
# library (cuBLAS / cuDNN / the CUDA runtime), a driver mismatch or no device —
# e.g. the classic "Library cublas64_12.dll is not found or cannot be loaded".
# Matched case-insensitively; "cuda" also covers "cudart" and "CUDA-capable".
_CUDA_ERROR_MARKERS = ("cublas", "cudnn", "cuda")

# Transient GPU runtime failures that are NOT a permanent "GPU unavailable"
# condition: out-of-memory just means this run didn't fit. Falling back to the
# CPU for the whole session (and claiming the libraries are missing) would be
# wrong, so these are excluded even though they mention CUDA.
_CUDA_TRANSIENT_MARKERS = ("out of memory", "outofmemory")

# Compute types that only exist on a GPU. When we fall back to the CPU we relax
# these to "auto" so the reload doesn't fail again for a different reason.
_GPU_ONLY_COMPUTE = ("float16", "int8_float16")


def is_cuda_library_error(exc) -> bool:
    """Whether `exc` means the NVIDIA CUDA GPU is unavailable (missing/unloadable
    library, driver mismatch, no device) rather than a transient runtime error.

    Used to turn the cryptic raw error into an automatic CPU fallback and an
    actionable, user-facing message instead of forwarding the DLL name verbatim.
    Transient failures such as out-of-memory are deliberately excluded so a
    one-off error doesn't permanently downgrade the session to the CPU.
    """
    text = str(exc).lower()
    if not any(marker in text for marker in _CUDA_ERROR_MARKERS):
        return False
    return not any(marker in text for marker in _CUDA_TRANSIENT_MARKERS)


def _model_is_cached(model_name: str, model_dir) -> bool:
    """Whether the model is already on disk, so loading it won't download.

    A local directory is a ready-to-use model. Otherwise probe the Hugging Face
    cache offline (``local_files_only=True`` never touches the network): a
    complete snapshot resolves to a path, a missing or partial one raises. Any
    uncertainty counts as "not cached" so we fall back to the normal,
    download-capable load path — never a false "already downloaded".
    """
    try:
        if os.path.isdir(model_name):
            return True
        from faster_whisper.utils import download_model

        download_model(
            model_name,
            local_files_only=True,
            cache_dir=str(model_dir) if model_dir else None,
        )
        return True
    except Exception:
        return False


def create_transcriber(cfg):
    """Build the transcription backend selected by cfg["backend"].

    "faster-whisper" (the default) covers NVIDIA CUDA and the CPU; "openvino"
    covers Intel CPUs/GPUs/NPUs via OpenVINO GenAI; "parakeet" runs NVIDIA's
    Parakeet TDT model via onnx-asr (fastest, not a Whisper model). All classes
    expose the same surface (ensure_loaded / transcribe / preview / loaded /
    backend), so App never needs to know which one it holds."""
    if cfg["backend"] == "openvino":
        from .transcriber_openvino import OpenVinoTranscriber

        return OpenVinoTranscriber(cfg)
    if cfg["backend"] == "parakeet":
        from .transcriber_parakeet import ParakeetTranscriber

        return ParakeetTranscriber(cfg)
    return Transcriber(cfg)


class Transcriber:
    backend = "faster-whisper"

    def __init__(self, cfg):
        self.cfg = cfg
        self._model = None
        self._key = None
        self._lock = threading.Lock()  # protects model loading
        self._use_lock = threading.Lock()  # serializes transcription runs
        # When a CUDA/GPU library failure forces the CPU, we record the exact
        # (device, compute_type) config it happened for. The fallback stays
        # active only while the config still asks for that same GPU setup, so
        # changing the device or compute type in Settings automatically retries
        # it — with no re-notify on unrelated saves. Not persisted; a restart
        # clears it too.
        self._cpu_fallback_for: tuple | None = None

    @property
    def _forced_cpu(self) -> bool:
        """Whether the session CPU fallback currently applies. True only while
        the configured device/compute still match the setup that failed on the
        GPU; editing either in Settings makes this False again (a fresh retry)."""
        return self._cpu_fallback_for == (self.cfg["device"], self.cfg["compute_type"])

    def _effective_device(self) -> str:
        """The device to actually load on: the configured one, unless a GPU
        library failure this session forced a fallback to the CPU."""
        return "cpu" if self._forced_cpu else self.cfg["device"]

    def _current_key(self):
        # Evaluate the fallback once so the device and compute type stay mutually
        # consistent even if the config is edited concurrently (no torn key).
        forced = self._forced_cpu
        device = "cpu" if forced else self.cfg["device"]
        compute_type = self.cfg["compute_type"]
        if forced and compute_type in _GPU_ONLY_COMPUTE:
            compute_type = "auto"  # a GPU-only precision can't run on the CPU
        return (self.cfg["model"], device, compute_type, self.cfg["model_dir"])

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._key == self._current_key()

    def ensure_loaded(self, notify=None) -> None:
        """Load the Whisper model, reloading if the settings changed.

        The model is fetched from Hugging Face on first use and cached locally
        (in cfg["model_dir"] if set, otherwise the Hugging Face cache). Every
        later run — including every app restart — only reloads it from that
        cache; there is no second download. The notification reflects which of
        the two is happening instead of always warning about a download.

        If loading on the GPU fails because the CUDA libraries are missing, it
        automatically falls back to the CPU for this session (see
        _maybe_force_cpu) and retries, so transcription keeps working.
        """
        with self._lock:
            self._ensure_loaded_locked(notify)

    def _ensure_loaded_locked(self, notify=None) -> None:
        """Load/reload the model. Caller must hold self._lock."""
        key = self._current_key()
        if self._model is not None and key == self._key:
            return
        model_name, device, compute_type, model_dir = key
        cached = _model_is_cached(model_name, model_dir)
        if notify is not None:
            if cached:
                notify(f"Loading Whisper model '{model_name}'…")
            else:
                notify(
                    f"Downloading Whisper model '{model_name}' — "
                    "one-time setup, this can take a few minutes."
                )
        from faster_whisper import WhisperModel

        try:
            self._model = WhisperModel(
                model_name,
                device=device,
                compute_type="default" if compute_type == "auto" else compute_type,
                download_root=str(model_dir) if model_dir else None,
                # Already cached → load straight from disk, skipping the network
                # revision check so restarts are fast and work fully offline.
                local_files_only=cached,
            )
        except Exception as exc:
            if self._maybe_force_cpu(device, exc, notify):
                # Retry on the CPU. notify=None: _maybe_force_cpu already told the
                # user we switched, so don't repeat the "Loading model…" toast.
                self._ensure_loaded_locked(None)
                return
            raise
        self._key = key
        log.info(
            "whisper model %s: %s / %s / %s (dir=%s)",
            "loaded from cache" if cached else "downloaded",
            *key,
        )

    def _maybe_force_cpu(self, device: str, exc: Exception, notify) -> bool:
        """Handle a model load/inference failure.

        If the NVIDIA CUDA GPU is unavailable (missing libraries, driver mismatch
        or no device) and we aren't already on the CPU, switch to the CPU for the
        rest of this session, drop the failed model, notify the user once and
        return True so the caller retries. Otherwise return False — the caller
        should re-raise.
        """
        if self._forced_cpu or device == "cpu" or not is_cuda_library_error(exc):
            return False
        log.warning("GPU transcription unavailable (%s) — using the CPU this session", exc)
        self._cpu_fallback_for = (self.cfg["device"], self.cfg["compute_type"])
        self._model = None
        self._key = None
        if notify is not None:
            notify(
                "GPU acceleration unavailable — switched to CPU for this "
                "session. Open the tray menu → Help to enable your GPU, or set "
                "Device = CPU in Settings → Whisper.",
                True,  # force: important even when notifications are off
            )
        return True

    def _decode_segments(self, audio, *, beam_size: int, condition_on_previous_text: bool = True):
        """Run the model on `audio` and return ([(end_seconds, text), …], info).
        Caller holds _use_lock."""
        # Snapshot the model: a concurrent CPU fallback (which holds only _lock,
        # not _use_lock) may null self._model between preview()'s loaded-check and
        # here. Bind it once so we never dereference None mid-decode.
        model = self._model
        if model is None:
            raise RuntimeError("Whisper model is not loaded")
        language = self.cfg["language"]
        segments, info = model.transcribe(
            audio,
            language=None if language in ("", "auto") else language,
            initial_prompt=self.cfg["initial_prompt"] or None,
            vad_filter=bool(self.cfg["vad_filter"]),
            beam_size=beam_size,
            condition_on_previous_text=condition_on_previous_text,
        )
        return [(float(s.end), s.text.strip()) for s in segments], info

    def _decode(self, audio, *, beam_size: int, condition_on_previous_text: bool = True):
        """Run the model on `audio` and return (text, info). Caller holds _use_lock."""
        segments, info = self._decode_segments(
            audio, beam_size=beam_size, condition_on_previous_text=condition_on_previous_text
        )
        text = " ".join(part for _end, part in segments if part).strip()
        return text, info

    def transcribe(self, audio, notify=None) -> str:
        self.ensure_loaded(notify=notify)
        # Clamp instead of trusting the config file: beam_size 0/negative would
        # crash faster-whisper mid-recording.
        beam_size = max(1, int(self.cfg["beam_size"] or 5))
        try:
            with self._use_lock:
                text, info = self._decode(audio, beam_size=beam_size)
        except Exception as exc:
            # The CUDA libraries are often only touched at inference time, so the
            # cuBLAS/cuDNN failure can surface here rather than at load. Fall back
            # to the CPU and retry once instead of failing the transcription.
            if not self._recover_on_cpu(exc, notify):
                raise
            with self._use_lock:
                text, info = self._decode(audio, beam_size=beam_size)
        log.info(
            "transcribed %.1fs -> %d chars (language=%s)",
            len(audio) / SAMPLE_RATE,
            len(text),
            getattr(info, "language", "?"),
        )
        return text

    def _recover_on_cpu(self, exc: Exception, notify) -> bool:
        """After an inference failure, force the CPU and reload there if the
        cause was the missing CUDA libraries. Returns True when the caller should
        retry, False when it should re-raise."""
        with self._lock:
            if not self._maybe_force_cpu(self._effective_device(), exc, notify):
                return False
            self._ensure_loaded_locked(notify)
        return True

    def preview(self, audio) -> str | None:
        """Fast, low-quality transcription of the tail of an ongoing recording.

        Returns None when the model isn't loaded yet (the preview must never
        trigger a silent download — that's the real transcribe()'s job, with a
        notification) or when another transcription is already running (previews
        are skipped rather than queued). Uses greedy decoding to stay cheap.
        """
        if not self.loaded:
            return None
        if not self._use_lock.acquire(blocking=False):
            return None
        try:
            audio = audio[-_PREVIEW_WINDOW_SECONDS * SAMPLE_RATE :]
            text, _info = self._decode(audio, beam_size=1, condition_on_previous_text=False)
            return text
        finally:
            self._use_lock.release()

    def preview_segments(self, audio) -> list[tuple[float, str]] | None:
        """Like preview(), but per segment: [(end_seconds, text), …] with the
        end timestamps relative to the start of `audio`. Drives the live-typing
        agreement policy (livetype.py), which needs to know *where* a stable
        segment ends so it can advance its committed-audio offset. The audio is
        deliberately not windowed here — the caller controls the window, and a
        hidden cut would shift every timestamp. Same None contract as preview().
        """
        if not self.loaded:
            return None
        if not self._use_lock.acquire(blocking=False):
            return None
        try:
            segments, _info = self._decode_segments(
                audio, beam_size=1, condition_on_previous_text=False
            )
            return [(end, text) for end, text in segments if text]
        finally:
            self._use_lock.release()
