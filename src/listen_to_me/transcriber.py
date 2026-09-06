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

# What "auto" means for the compute type, best candidate first, per device.
# Neither of CTranslate2's own answers fits a dictation app: its "auto" picks
# the *fastest* supported type (int8_float16 on a GPU — a precision loss the
# GPU has no need for), and faster-whisper's default, "default", keeps the
# *converted* type — float16 for every Systran/distil preset, which no CPU can
# run, so CTranslate2 silently widens it to float32, the slowest CPU path of
# all. That was this app's "auto" until 2026-09: every default installation
# without an NVIDIA GPU transcribed in float32. On the CPU int8 is 2–4× faster
# at a WER difference below noise; on a GPU float16 keeps the full accuracy.
# The candidates are checked against what the installed CTranslate2 reports
# as supported (float16 needs compute capability ≥ 7.0, int8 needs an
# instruction set the CPU has), never assumed.
_AUTO_COMPUTE_PREFERENCE = {
    "cpu": ("int8", "int8_float32", "float32"),
    "cuda": ("float16", "int8_float16", "int8", "float32"),
}


def resolve_runtime(device: str, compute_type: str) -> tuple[str, str]:
    """The (device, compute_type) pair actually handed to CTranslate2.

    ``device="auto"`` becomes ``"cuda"`` when CTranslate2 sees a CUDA GPU,
    else ``"cpu"``; ``compute_type="auto"`` becomes the first entry of
    _AUTO_COMPUTE_PREFERENCE that device supports. Explicit choices pass
    through untouched. Whenever CTranslate2 cannot be asked — not installed,
    a CUDA runtime that throws on the probe — the pair is handed on as
    ``"auto"`` / ``"default"``, i.e. CTranslate2's own resolution (the old
    behaviour), so a failed probe can never prevent a load that would have
    worked. Never raises.
    """
    passthrough = "default" if compute_type == "auto" else compute_type
    try:
        import ctranslate2
    except Exception:
        log.debug("ctranslate2 unavailable for the runtime probe", exc_info=True)
        return device, passthrough
    if device == "auto":
        try:
            count = int(ctranslate2.get_cuda_device_count())
            # Worth a line in the log: "no GPU" and "GPU present but cuBLAS
            # missing" look identical to the user, and this is what tells
            # them apart when the CUDA fallback fires later.
            log.info("ctranslate2 sees %d CUDA device(s)", count)
            device = "cuda" if count > 0 else "cpu"
        except Exception:
            log.debug("CUDA device probe failed — leaving the device to CTranslate2", exc_info=True)
            return "auto", passthrough
    if compute_type != "auto":
        return device, compute_type
    try:
        supported = set(ctranslate2.get_supported_compute_types(device))
    except Exception:
        log.debug("compute type probe failed on %s — using CTranslate2's default", device, exc_info=True)
        return device, "default"
    for candidate in _AUTO_COMPUTE_PREFERENCE.get(device, ()):
        if candidate in supported:
            return device, candidate
    return device, "default"


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


def hub_repo_id(model_name: str) -> str | None:
    """The Hugging Face repo a model preset resolves to — the one
    faster-whisper would download from.

    None for a local directory (nothing is fetched) and whenever the preset
    table cannot be read, which costs the download only its progress display.
    The table is faster-whisper's own and private, so it is reached defensively
    rather than mirrored here, where it would silently rot out of date.
    """
    if not model_name or os.path.isdir(model_name):
        return None
    if "/" in model_name:
        return model_name  # an explicit repo id, used verbatim
    try:
        from faster_whisper.utils import _MODELS

        return _MODELS.get(model_name)
    except Exception:
        log.debug("could not resolve the hub repo of %r", model_name, exc_info=True)
        return None


def _download_watcher(model_name: str, model_dir, progress):
    """A DownloadWatcher over the cache folder `model_name` downloads into.

    Falls back to a watcher with no directory (which reports nothing) when the
    repo cannot be resolved — a model download must never fail because its
    progress display could not be set up.
    """
    from .progress import DownloadWatcher, hub_cache_dir, hub_repo_size

    repo = hub_repo_id(model_name)
    folder = hub_cache_dir(repo, model_dir) if repo else None
    total = hub_repo_size(repo) if repo else None
    return DownloadWatcher(folder, total, progress, label=f"Downloading {model_name}")


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
        # (device, compute_type) the loaded model actually runs with — the
        # config's "auto" values resolved by resolve_runtime(). None until a
        # model is loaded; reset whenever the model is dropped.
        self._runtime: tuple[str, str] | None = None

    @property
    def runtime(self) -> tuple[str, str] | None:
        """(device, compute_type) of the currently loaded model, e.g.
        ("cpu", "int8") for the default config on a machine without a GPU —
        what "auto" resolved to. None while nothing is loaded."""
        return self._runtime if self.loaded else None

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

    def ensure_loaded(self, notify=None, progress=None) -> None:
        """Load the Whisper model, reloading if the settings changed.

        The model is fetched from Hugging Face on first use and cached locally
        (in cfg["model_dir"] if set, otherwise the Hugging Face cache). Every
        later run — including every app restart — only reloads it from that
        cache; there is no second download. The notification reflects which of
        the two is happening instead of always warning about a download.

        `progress(label, fraction, done, total)` — optional — is called from a
        background thread while a download runs, and once with ``label=None``
        when it is over (see progress.DownloadWatcher). It never fires for a
        load from cache, which is the case that needs no progress bar.

        If loading on the GPU fails because the CUDA libraries are missing, it
        automatically falls back to the CPU for this session (see
        _maybe_force_cpu) and retries, so transcription keeps working.
        """
        with self._lock:
            self._ensure_loaded_locked(notify, progress)

    def _ensure_loaded_locked(self, notify=None, progress=None) -> None:
        """Load/reload the model. Caller must hold self._lock."""
        if self._cpu_fallback_for is not None and not self._forced_cpu:
            # The config moved away from the setup that failed: drop the
            # marker so a later RETURN to that GPU setup retries it instead
            # of silently re-forcing the CPU (an explicit re-selection is a
            # retry request).
            self._cpu_fallback_for = None
        key = self._current_key()
        if self._model is not None and key == self._key:
            return
        model_name, device, compute_type, model_dir = key
        # Resolved once per load, right here, so the log line below and the
        # `runtime` property describe the pair the model really runs with.
        run_device, run_compute = resolve_runtime(device, compute_type)
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

        def load():
            return WhisperModel(
                model_name,
                device=run_device,
                compute_type=run_compute,
                download_root=str(model_dir) if model_dir else None,
                # Already cached → load straight from disk, skipping the network
                # revision check so restarts are fast and work fully offline.
                local_files_only=cached,
            )

        try:
            if cached or progress is None:
                self._model = load()
            else:
                # Only the downloading load is watched: WhisperModel does the
                # fetching itself, so the bytes are counted where they land.
                with _download_watcher(model_name, model_dir, progress):
                    self._model = load()
        except Exception as exc:
            if self._maybe_force_cpu(device, exc, notify):
                # Retry on the CPU. notify=None: _maybe_force_cpu already told the
                # user we switched, so don't repeat the "Loading model…" toast.
                # No progress either — the model is on disk by now.
                self._ensure_loaded_locked(None)
                return
            raise
        self._key = key
        self._runtime = (run_device, run_compute)
        log.info(
            "whisper model %s: %s / %s / %s (dir=%s) — running on %s as %s",
            "loaded from cache" if cached else "downloaded",
            *key,
            run_device,
            run_compute,
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
        self._runtime = None
        if notify is not None:
            notify(
                "GPU acceleration unavailable — switched to CPU for this "
                "session. Open the tray menu → Help to enable your GPU, or set "
                "Device = CPU in Settings → Engine.",
                True,  # force: important even when notifications are off
            )
        return True

    def _decode_segments(self, audio, *, beam_size: int, condition_on_previous_text: bool = True):
        """Run the model on `audio` and return ([(end_seconds, text), …], info),
        or None when no model is loaded. Caller holds _use_lock."""
        # Snapshot the model: a concurrent CPU fallback (which holds only _lock,
        # not _use_lock) may null self._model between preview()'s loaded-check and
        # here. Bind it once so we never dereference None mid-decode. Returning
        # None instead of raising keeps that transient race a skipped preview
        # tick — transcribe() turns it into an error, its only correct meaning
        # there.
        model = self._model
        if model is None:
            return None
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
        """Run the model on `audio` and return (text, info), or None when no
        model is loaded. Caller holds _use_lock."""
        decoded = self._decode_segments(
            audio, beam_size=beam_size, condition_on_previous_text=condition_on_previous_text
        )
        if decoded is None:
            return None
        segments, info = decoded
        text = " ".join(part for _end, part in segments if part).strip()
        return text, info

    def transcribe(self, audio, notify=None, progress=None) -> str:
        self.ensure_loaded(notify=notify, progress=progress)
        # Clamp instead of trusting the config file: beam_size 0/negative would
        # crash faster-whisper mid-recording.
        beam_size = max(1, int(self.cfg["beam_size"] or 5))
        try:
            with self._use_lock:
                decoded = self._decode(audio, beam_size=beam_size)
            if decoded is None:
                raise RuntimeError("Whisper model is not loaded")
            text, info = decoded
        except Exception as exc:
            # The CUDA libraries are often only touched at inference time, so the
            # cuBLAS/cuDNN failure can surface here rather than at load. Fall back
            # to the CPU and retry once instead of failing the transcription.
            if not self._recover_on_cpu(exc, notify):
                raise
            with self._use_lock:
                decoded = self._decode(audio, beam_size=beam_size)
            if decoded is None:
                # `from exc`: without it the traceback reads as if this retry
                # were an error raised while handling the GPU failure, which
                # buries the cause the user actually needs to see in the log.
                raise RuntimeError("Whisper model is not loaded") from exc
            text, info = decoded
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
            decoded = self._decode(audio, beam_size=1, condition_on_previous_text=False)
            if decoded is None:
                return None  # concurrent CPU fallback mid-reload — skip this tick
            text, _info = decoded
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
            decoded = self._decode_segments(
                audio, beam_size=1, condition_on_previous_text=False
            )
            if decoded is None:
                return None  # concurrent CPU fallback mid-reload — skip this tick
            segments, _info = decoded
            return [(end, text) for end, text in segments if text]
        finally:
            self._use_lock.release()
