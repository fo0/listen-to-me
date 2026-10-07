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
import math
import os
import threading
from pathlib import Path

from .audio import SAMPLE_RATE
from .choices import OPENVINO_UNSUPPORTED_MODELS, openvino_alternative
from .hallucination import (
    PROMPT_TOKEN_BUDGET,
    estimate_prompt_tokens,
    prompt_tail,
    strip_foreign_runs,
    trim_silence,
)
from .transcriber import _PREVIEW_WINDOW_SECONDS

log = logging.getLogger(__name__)

_INSTALL_HINT = (
    "The OpenVINO backend needs the optional openvino-genai package. "
    "Install it with: pip install openvino-genai — or set "
    "Backend = faster-whisper in Settings → Engine."
)

# The output budget per second of audio (#293): a prompt echo ran takes of
# 0.5–2.7 s out to 1547 characters each. A cap below the speech is a
# transcript cut short without a word, so it sits well above any real rate.
# Measured with the Whisper tokenizer, German runs 0.25 tokens a character,
# technical German 0.32: the 30 characters a second App._process still
# accepts from a microphone are up to ~10 tokens a second, and system audio
# played at 2× has no such limit at all. 16 cuts neither; the floor leaves a
# short take room, and implausible_reason catches the loop the cap bounds.
_TOKENS_PER_SECOND = 16.0
_MIN_NEW_TOKENS = 32

# Whisper's decoder has 448 positions per 30-s window, shared with what GenAI
# puts in front of the output: <|startoftranscript|>, language, task and
# <|notimestamps|>, plus <|startofprev|> and the prompt when there is one.
_DECODER_POSITIONS = 448
_SOT_TOKENS = 4

# Takes shorter than this get no initial prompt (#293): all four echo takes
# were 0.5–2.7 s — too little audio to outweigh a prompt, so the decoder read
# the prompt back instead — while a vocabulary hint matters for real speech.
_MIN_PROMPT_SECONDS = 3.0


def _is_count(value) -> bool:
    """Whether `value` is a real token count — not None, a bool, 0, or the
    SIZE_MAX GenAI reports for "unset"."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2**32


def _token_room(config, prompt_tokens: int) -> int:
    """The most tokens GenAI itself lets one window generate. An unset
    max_new_tokens reads as SIZE_MAX, and GenAI then stops a window at
    max_length minus its context. A cap set at or above that bound replaces
    it, and a looping window then decodes past the decoder's 448 positions:
    one window of a 120-s take generated 960 tokens (openvino-genai 2026.4,
    CPU), and the NPU's KV cache is a fixed 448."""
    length = getattr(config, "max_length", None)
    room = (length if _is_count(length) else _DECODER_POSITIONS) - _SOT_TOKENS
    if prompt_tokens:
        room -= 1 + prompt_tokens  # <|startofprev|> and the prompt
    current = getattr(config, "max_new_tokens", None)
    return min(room, current) if _is_count(current) else room


def _prompt_tokens(pipe, prompt: str) -> int:
    """How many tokens GenAI puts in front for `prompt` (it encodes " " +
    prompt). Falls back to the UTF-8 byte count: byte-level BPE never needs
    more tokens than bytes, so the room is never overestimated."""
    text = " " + prompt
    try:
        return int(pipe.get_tokenizer().encode(text, add_special_tokens=False).input_ids.get_size())
    except Exception:
        log.debug("could not count the prompt's tokens — using its byte length", exc_info=True)
        return len(text.encode("utf-8"))


def openvino_model_repo(model: str, precision: str) -> str:
    """Map a model preset + precision to its pre-converted Hugging Face repo id,
    e.g. ("small", "int8") → "OpenVINO/whisper-small-int8-ov".

    A value containing "/" is treated as an explicit repo id (or a local path)
    and passed through verbatim, so any OpenVINO IR model can be used. Raises
    ValueError for the presets that have no OpenVINO conversion.
    """
    # Checked before the "/" passthrough below: the German preset is a
    # CTranslate2 repo id, so passing it through verbatim would download a
    # model this backend cannot load. The message leads with the fix that keeps
    # the backend the user chose — swapping the *model* — because the model is
    # the incompatible half; recommending faster-whisper first sent people with
    # an Intel machine and no NVIDIA GPU off the only backend that fits their
    # hardware (#112).
    if model in OPENVINO_UNSUPPORTED_MODELS:
        raise ValueError(
            f"The model '{model}' has no OpenVINO conversion — pick "
            f"'{openvino_alternative(model)}' (or another model) in Settings → "
            "Engine. Only if you need this exact model, switch Backend back to "
            "faster-whisper, which can run it."
        )
    if "/" in model or os.sep in model:
        return model
    base = "distil-whisper-large-v3" if model == "distil-large-v3" else f"whisper-{model}"
    return f"OpenVINO/{base}-{precision}-ov"


def _looks_like_openvino_model(repo: str) -> bool | None:
    """Whether `repo` ships OpenVINO IR files (``openvino_*.xml``).

    Custom model ids are passed through verbatim, so a CTranslate2 id entered
    while this backend is selected downloads a model the pipeline cannot load
    and only fails at load time with a cryptic error. Listing the files first
    turns that into an actionable message before the download starts.

    Returns None when it cannot be determined — offline, a private repo, any
    hub error — so the caller stays permissive rather than blocking a model
    that may well work.
    """
    try:
        if os.path.isdir(repo):
            names = os.listdir(repo)
        else:
            from huggingface_hub import list_repo_files

            names = list_repo_files(repo)
    except Exception:
        log.debug("could not list the files of %r for the format check", repo, exc_info=True)
        return None
    return any(
        name.startswith("openvino_") and name.endswith(".xml")
        for name in (os.path.basename(str(entry)) for entry in names)
    )


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


def _pipeline_properties(device: str, model_dir) -> dict:
    """OpenVINO properties for a pipeline on `device`.

    A GPU or NPU compiles the model on every load — tens of seconds up to
    minutes for large-v3-turbo on an NPU — and OpenVINO can cache the compiled
    blob: with ``CACHE_DIR`` the next start of the same model/device/driver is
    a file read (openvino.genai#1992 measured minutes → seconds on the NPU).
    The CPU plugin compiles fast and its blob would only cost disk, so it gets
    none. The cache sits under the user's own config dir — or next to a custom
    model folder — never under the shared temp dir (see theme._asset_dir for
    what a guessable path there costs). A cache dir that cannot be created is
    a warning and a slower load, never a failed one.
    """
    if device == "CPU":
        return {}
    from .config import config_dir

    root = Path(str(model_dir)) if model_dir else config_dir() / "cache"
    cache = root / "openvino-cache"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning(
            "could not create the OpenVINO compile cache %s — loading without it",
            cache,
            exc_info=True,
        )
        return {}
    return {"CACHE_DIR": str(cache)}


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
        # ((prompt, key, id(pipe)), tail, its token count) of the last
        # _prompt_tail() answer: tokenised and logged once per prompt and
        # pipeline, never once per take.
        self._prompt_memo: tuple | None = None
        # The prompt the last final decode handed the model, "" for none: a
        # take too short for one gets none (#293), and App._process must not
        # look for an echo of a prompt the model never read.
        self.last_prompt = ""

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

    @property
    def runtime(self) -> tuple[str, str] | None:
        """(device, precision) the loaded pipeline actually runs with — e.g.
        ("GPU", "int8"): what "auto" resolved to, or the CPU after a session
        fallback. None while nothing is loaded. Same contract as
        Transcriber.runtime, so the Settings status card shows the effective
        device for every backend."""
        if not self.loaded or self._device is None or self._key is None:
            return None
        return self._device, self._key[1]

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

    def ensure_loaded(self, notify=None, progress=None) -> None:
        """Load the Whisper pipeline, reloading if the settings changed.

        Downloads the pre-converted OpenVINO model from Hugging Face on first
        use (into cfg["model_dir"] or the Hugging Face cache) and loads from
        that cache on every later run. A failure to load on the GPU/NPU falls
        back to the CPU for this session and retries, so transcription keeps
        working — mirroring the faster-whisper CUDA fallback.

        `progress` follows the same contract as the faster-whisper backend: it
        is called from a background thread while the download runs and once
        with ``label=None`` when it ends."""
        with self._lock:
            self._ensure_loaded_locked(notify, progress)

    def _ensure_loaded_locked(self, notify=None, progress=None) -> None:
        if self._cpu_fallback_for is not None and not self._forced_cpu:
            # The config moved away from the setup that failed: drop the
            # marker so a later RETURN to that device/precision retries it
            # instead of silently re-forcing the CPU.
            self._cpu_fallback_for = None
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
        # Only custom ids can carry the wrong format — the mapped presets are
        # known OpenVINO repos — and only the first (downloading) load pays for
        # the remote listing; "cached" only proves the files were downloaded
        # (not that they ever loaded), so the pipeline failure path below
        # re-checks the local copy before reporting a cryptic load error.
        custom = "/" in model_name or os.sep in model_name
        if custom and not cached and _looks_like_openvino_model(repo) is False:
            raise ValueError(
                f"'{repo}' does not look like an OpenVINO model — it has no "
                "openvino_*.xml files (a CTranslate2 or Transformers model "
                "cannot be loaded by this backend). Pick an OpenVINO IR repo "
                "such as OpenVINO/whisper-small-int8-ov, or switch Backend to "
                "faster-whisper in Settings → Engine."
            )
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

            from .progress import DownloadWatcher, hub_cache_dir, hub_repo_size

            def download():
                # Already cached → resolve straight from disk, skipping the
                # network revision check so restarts are fast and work offline.
                return snapshot_download(
                    repo,
                    cache_dir=str(model_dir) if model_dir else None,
                    local_files_only=cached,
                )

            if cached or progress is None:
                path = download()
            else:
                # snapshot_download fetches the whole repo, so its full size is
                # exactly what the percentage is of — no file filter needed.
                watcher = DownloadWatcher(
                    hub_cache_dir(repo, model_dir),
                    hub_repo_size(repo),
                    progress,
                    label=f"Downloading {repo}",
                )
                with watcher:
                    path = download()
        device = self._resolve_device(device_cfg)
        properties = _pipeline_properties(device, model_dir)
        try:
            try:
                self._pipe = openvino_genai.WhisperPipeline(path, device, **properties)
            except Exception:
                if not properties:
                    raise
                # A plugin or driver that rejects the cache property must not
                # read as "device unusable": retry once bare, and only then
                # let the device fallback judge the failure.
                log.warning(
                    "OpenVINO %s failed to load with %s — retrying without the compile cache",
                    device,
                    sorted(properties),
                    exc_info=True,
                )
                self._pipe = openvino_genai.WhisperPipeline(path, device)
        except Exception as exc:
            if custom and _looks_like_openvino_model(path) is False:
                # A wrong-format custom model that slipped past the download
                # check (hub unreachable then, cached now): name the actual
                # problem instead of a cryptic load error — and don't let
                # _maybe_force_cpu blame the device for it.
                raise ValueError(
                    f"'{repo}' is not an OpenVINO model — it has no "
                    "openvino_*.xml files (a CTranslate2 or Transformers "
                    "model cannot be loaded by this backend). Pick an "
                    "OpenVINO IR repo such as OpenVINO/whisper-small-int8-ov, "
                    "or switch Backend to faster-whisper in Settings → "
                    "Engine."
                ) from exc
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
                "Intel device = CPU in Settings → Engine.",
                True,  # force: important even when notifications are off
            )
        return True

    # ----------------------------------------------------------- decoding

    def _decode(self, audio, *, final: bool = False) -> str | None:
        """Run the pipeline on `audio` and return the text, or None when no
        pipeline is loaded (a concurrent CPU fallback nulled it mid-reload).
        Caller holds _use_lock.

        The #293 guards: `final` (what reaches the cursor) first trims the
        silence Whisper invents text in — previews, run every tick, skip that.
        Every decode gets an output budget scaled to its audio, no prompt when
        too short to outweigh one (else only the tail Whisper reads), and
        foreign runs cut."""
        pipe = self._pipe
        if pipe is None:
            return None
        if final:
            before = len(audio)
            audio = trim_silence(audio, SAMPLE_RATE)
            if len(audio) != before:
                log.debug("trimmed %.1f s of silence", (before - len(audio)) / SAMPLE_RATE)
        seconds = len(audio) / SAMPLE_RATE  # after the trim: what is decoded
        config = pipe.get_generation_config()
        language = self.cfg["language"]
        if language not in ("", "auto"):
            config.language = f"<|{language}|>"
            config.task = "transcribe"
        # Only the tail Whisper reads, and only for the first 30-s window.
        prompt, prompt_tokens = self._prompt_tail(pipe, self.cfg["initial_prompt"])
        prompted = ""
        if prompt and hasattr(config, "initial_prompt"):
            if seconds >= _MIN_PROMPT_SECONDS:
                config.initial_prompt = prompted = prompt
            else:
                log.debug("initial prompt skipped for a %.1f-s take", seconds)
        if final:
            self.last_prompt = prompted
        if hasattr(config, "max_new_tokens"):
            # GenAI applies the cap per 30-s chunk (a 4130-character OpenVINO
            # dictation is in the field logs, far beyond 448 tokens). Only a
            # cap below GenAI's own per-window bound is set — on a long take
            # the bound stays as it is; only a short take gets a tight one.
            cap = max(_MIN_NEW_TOKENS, math.ceil(seconds * _TOKENS_PER_SECOND))
            if cap < _token_room(config, prompt_tokens if prompted else 0):
                config.max_new_tokens = cap
        # No repetition guard is set, on purpose (#293). GenAI applies
        # no_repeat_ngram_size only in its beam-search sampler, and this
        # pipeline decodes greedily — the output is identical with and
        # without it (openvino-genai 2026.4.1); in the beam path its n-gram
        # history includes the prompt, so it would forbid dictating prompt
        # terms in their listed order. repetition_penalty reweights every
        # token of normal speech. The length cap above and the app-level
        # implausible_reason check carry the loop protection.
        # The pipeline chunks audio longer than 30 s internally (sliding
        # window); it expects a plain float list at 16 kHz, which is exactly
        # what the Recorder captures.
        result = pipe.generate(audio.tolist(), config)
        texts = getattr(result, "texts", None)
        text = (texts[0] if texts else str(result)).strip()
        cleaned = strip_foreign_runs(text, language)
        if cleaned != text:
            # A preview repeats every tick: one INFO line per take, not per tick.
            log.log(
                logging.INFO if final else logging.DEBUG,
                "foreign-script run stripped from the transcript: %.60r",
                text,
            )
        return cleaned

    def _prompt_tail(self, pipe, prompt) -> tuple[str, int]:
        """(tail, tokens it puts in front of the output) of `prompt`: the last
        223 tokens Whisper reads, starting on a whole term (#293).

        Cut with the pipeline's own tokenizer: GenAI never truncates a prompt
        — every token goes in front of the first window — and the character
        estimate is far off for dense scripts (a Chinese list came out at 1334
        tokens, a Japanese one at 641: generate() refused both, and a
        `JIRA-4000, …` list at 417 left the first window 26 tokens of room).
        The estimate is only the fallback for a pipeline whose tokenizer is
        unavailable or fails. GenAI hands `initial_prompt` to the first 30-s
        window of a take only, like faster-whisper without
        condition_on_previous_text. Memoised per prompt and pipeline (caller
        holds _use_lock), so the cut is tokenised and logged once per prompt.
        """
        prompt = str(prompt or "")
        key = (prompt, self._key, id(pipe))
        if self._prompt_memo is not None and self._prompt_memo[0] == key:
            return self._prompt_memo[1], self._prompt_memo[2]
        encode = decode = None
        counts: list[int] = []
        try:
            tokenizer = pipe.get_tokenizer()
        except Exception:
            log.debug("the pipeline has no tokenizer — estimating the prompt tail", exc_info=True)
        else:

            def encode(text):
                # The ids GenAI itself builds: it encodes " " + prompt.
                tokens = tokenizer.encode(" " + text, add_special_tokens=False)
                ids = [int(i) for i in tokens.input_ids.data[0]]
                counts.append(len(ids))
                return ids

            def decode(ids):
                return tokenizer.decode(ids)

        tail = prompt_tail(prompt, encode=encode, decode=decode)
        if tail != prompt.strip():
            log.info(
                "initial prompt is %s%d tokens — only the last %d reach the model",
                "" if counts else "about ",
                counts[0] if counts else estimate_prompt_tokens(prompt),
                PROMPT_TOKEN_BUDGET,
            )
        # What the tail costs in front of the output, for _token_room.
        used = _prompt_tokens(pipe, tail) if tail else 0
        self._prompt_memo = (key, tail, used)
        return tail, used

    def transcribe(self, audio, notify=None, progress=None) -> str:
        self.ensure_loaded(notify=notify, progress=progress)
        try:
            with self._use_lock:
                text = self._decode(audio, final=True)
            if text is None:
                raise RuntimeError("Whisper model is not loaded")
        except Exception as exc:
            if not self._recover_on_cpu(exc, notify):
                raise
            with self._use_lock:
                text = self._decode(audio, final=True)
            if text is None:
                # `from exc`: keeps the GPU/NPU failure that triggered the CPU
                # retry as the reported cause instead of a second, unrelated
                # error raised while handling it (same as transcriber.py).
                raise RuntimeError("Whisper model is not loaded") from exc
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
            return self._decode(audio)  # None (fallback mid-reload) = skipped tick
        finally:
            self._use_lock.release()
