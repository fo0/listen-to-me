"""Configuration handling: JSON file in the platform config directory."""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import sys
import tempfile
import time
from pathlib import Path

from .choices import default_mute_targets

log = logging.getLogger(__name__)

DEFAULT_ASSISTANT_PROMPT = """\
You are a dictation post-processor. You receive the raw output of a \
speech-to-text engine.

Your job:
- Fix punctuation, capitalization and obvious transcription mistakes.
- Remove filler words and false starts (uh, um, "you know", "äh", "ähm") \
unless they carry meaning.
- Apply formatting the speaker explicitly dictates (e.g. "new paragraph", \
"bullet list", "quote ... end quote").
- Keep the language of the input text. Never translate.
- Do not add, summarize or omit content.

Return ONLY the cleaned text — no explanations, no quotes, no markdown fences.\
"""

DEFAULTS: dict = {
    # Global hotkey in pynput format, e.g. "<ctrl>+<alt>+<space>".
    "hotkey": "<ctrl>+<alt>+<space>",
    # "toggle": press once to start, again to stop.
    # "hold": true push-to-talk — record only while the keys are held down.
    "hotkey_mode": "toggle",
    # Whisper language code ("auto" = detect automatically).
    "language": "auto",
    # Whisper model: preset name (tiny/base/small/…) or any CTranslate2
    # model id from Hugging Face. Downloaded automatically on first use.
    "model": "small",
    # Where downloaded models are stored. null = the Hugging Face default
    # cache (~/.cache/huggingface/hub).
    "model_dir": None,
    # Transcription backend: "faster-whisper" (NVIDIA CUDA / CPU, default),
    # "openvino" (Intel CPU / GPU / NPU — needs the optional openvino-genai
    # package: pip install openvino-genai, or the [openvino] extra) or
    # "parakeet" (NVIDIA Parakeet TDT via ONNX, fastest — needs the
    # [parakeet] extra). See choices.BACKENDS / transcriber.create_transcriber.
    "backend": "faster-whisper",
    # Device for the faster-whisper and parakeet backends: auto / cpu / cuda.
    # (The openvino backend has its own openvino_device below.)
    "device": "auto",
    # CTranslate2 compute type: auto / int8 / int8_float16 / float16 / float32.
    # "auto" = int8 on the CPU, float16 on a GPU that supports it — resolved
    # against the installed CTranslate2 (transcriber.resolve_runtime), never
    # CTranslate2's "default", which runs the float16 presets as float32 on
    # a CPU.
    "compute_type": "auto",
    # OpenVINO device (openvino backend): auto / cpu / gpu / npu.
    # "auto" prefers the GPU, then the NPU, then the CPU.
    "openvino_device": "auto",
    # Precision of the pre-converted OpenVINO model to download: int8 (small +
    # fast, recommended), fp16 (most accurate) or int4 (smallest).
    "openvino_precision": "int8",
    # Which ONNX variant of the Parakeet model to download (parakeet backend):
    # int8 (small + fast on CPU, recommended) or fp32 (most accurate, GPU).
    "parakeet_quantization": "int8",
    # sounddevice input device index, null = system default.
    "input_device": None,
    # Hard cap for a single recording.
    "max_seconds": 300,
    # How to insert text at the cursor: "paste" (clipboard + Ctrl+V) or "type".
    "injection_mode": "paste",
    # Experimental: type already-stable parts of the transcript at the cursor
    # WHILE recording instead of waiting for the end. Append-only (never
    # deletes or corrects), always simulated typing (never paste) and plain
    # text only: control characters are stripped and typing pauses while
    # Ctrl/Alt/Shift/Win is physically held, so no accidental key combination
    # can fire. Skips the assistant post-processing (it rewrites the whole
    # text, but typed text can't be taken back). faster-whisper backend only;
    # in hold mode only for hotkeys without modifiers (e.g. <f9>).
    "live_typing": False,
    # Whether a finished transcript also goes to the clipboard:
    # "on_failure" (default) = only when it could not be inserted at the cursor,
    # so it can be pasted manually instead of being fetched from the history;
    # "always" = every transcript stays on the clipboard (this suppresses
    # restore_clipboard — putting the old content back would undo it);
    # "off" = never touch the clipboard beyond what paste mode needs.
    "clipboard_copy": "on_failure",
    "restore_clipboard": True,
    "notifications": True,
    "beep": True,
    "autostart": False,
    # When true the app starts silently into the tray; when false (default)
    # the settings window opens on launch so the app is visibly running.
    "start_in_tray": False,
    # Floating always-on-top status icon.
    "overlay": {
        "enabled": True,
        # Keep the icon above every other window and re-apply that continuously.
        # Windows strips WS_EX_TOPMOST behind Qt's back (an explorer restart
        # does it to every topmost window, fullscreen apps take the band for
        # themselves), and Qt's raise_() never puts it back — the icon is then
        # still there but buried, which reads as "it vanished". Off leaves it an
        # ordinary window that other windows may cover.
        "always_on_top": True,
        # Briefly show the transcribed text next to the icon after a recording.
        "show_preview": True,
        # Experimental: transcribe in the background *while* recording and show
        # a rolling live preview of what was understood so far. Costs CPU.
        "live_preview": False,
        # How long the finished transcript stays visible (seconds).
        "preview_seconds": 6,
        # Saved position of the floating icon (null = bottom right). "x"/"y"
        # are desktop coordinates; "screen" identifies the monitor the icon was
        # left on (EDID identity, else the device name) and "rel_x"/"rel_y" are
        # the position inside that monitor. The monitor anchor is what survives
        # a reboot: desktop coordinates move whenever the arrangement, a
        # resolution or the primary screen changes — see overlay._screen_key.
        "x": None,
        "y": None,
        "screen": None,
        "rel_x": None,
        "rel_y": None,
    },
    # Optional Whisper initial prompt (domain vocabulary hint, not an instruction).
    "initial_prompt": "",
    # Deterministic find/replace rules applied to every finished transcript,
    # one "find => replace" per line (blank lines and "#" comments allowed).
    # Matching is case-insensitive and on whole words; the replacement is
    # inserted verbatim. Where initial_prompt only biases recognition, this
    # fixes what the recognizer got wrong anyway — see app.apply_replacements.
    # Not applied to live typing (that text is already at the cursor).
    "replacements": "",
    "vad_filter": True,
    # Decoding beam size (faster-whisper backend only): 5 = best accuracy
    # (default), 1 = greedy — roughly 1.5-2x faster at slightly lower accuracy.
    "beam_size": 5,
    # Keep a local history of transcribed text (never the audio) so a lost
    # transcript can be recovered from Settings → History. Stored in
    # history.json next to this config file.
    "history_enabled": True,
    # How many of the most recent transcripts to keep.
    "history_max": 200,
    # In-app updater (checks the GitHub Releases of this repo).
    "update_check_on_start": True,
    "include_prereleases": False,
    # Skip TLS certificate verification for every outbound HTTPS connection:
    # the Whisper model downloads, the assistant and the updater — including
    # the exe download that replaces the running program file (ADR-0006,
    # superseding ADR-0002; see netutil.py). Only for corporate proxies that
    # intercept HTTPS with a self-signed certificate — insecure, leave off
    # otherwise.
    "insecure_ssl": False,
    # Optional LLM post-processing via an OpenAI-compatible API (e.g. Ollama).
    "assistant": {
        "enabled": False,
        "base_url": "http://localhost:11434/v1",
        "api_key": "",
        "model": "llama3.2",
        "system_prompt": DEFAULT_ASSISTANT_PROMPT,
        "temperature": 0.2,
        "timeout": 120,
    },
    # Mute other applications (Discord, Teams, …) while a recording runs, so the
    # dictation isn't transmitted into a voice call. Each target sends a global
    # mute keybind — configure the SAME combination here and in that app.
    "integrations": {
        # Master switch — off by default; turn it on (Settings → Integrations)
        # when you dictate during voice calls. Individual targets are enabled
        # below.
        "mute_while_recording": False,
        # Each target: name, whether it's enabled, the keybind (pynput format)
        # and the mode. "hold" = push-to-mute (key held while recording),
        # "toggle" = toggle-mute (tapped once at start and once at stop).
        # The presets carry each app's documented mute keybind so it doesn't
        # have to be looked up, and all ship disabled — see
        # choices.MUTE_PRESETS, which is the single source of truth and also
        # holds the per-app setup note the Settings page shows. A stored list
        # replaces this one wholesale (_merge/_coerce), so an existing config
        # keeps its targets on upgrade and reaches the presets through the
        # Integrations page's "Add app" menu instead.
        "targets": default_mute_targets(),
    },
}


def open_path(path: str | os.PathLike[str]) -> None:
    """Open a folder (or file) in the platform's file manager. User-invoked."""
    path = str(path)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 — user-invoked
            return
        import subprocess

        cmd = ["open", path] if sys.platform == "darwin" else ["xdg-open", path]
        subprocess.Popen(cmd)
    except Exception:
        log.exception("could not open %s", path)


def default_model_dir() -> Path:
    """The Hugging Face hub cache faster-whisper downloads models into
    when no custom model folder is configured (mirrors huggingface_hub)."""
    hub_cache = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub_cache:
        return Path(hub_cache)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def config_dir() -> Path:
    # `or`, not a .get() default: a set-but-empty variable must count as unset
    # (the XDG spec says so explicitly) — Path("") is the current directory,
    # which would scatter config/history/lock files across launch locations.
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
        return base / "ListenToMe"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ListenToMe"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    return base / "listen-to-me"


def _finite_number(default, value):
    """``type(default)(value)``, or None when that is not a usable number.

    ``json.load`` accepts the ``NaN``/``Infinity`` literals, and ``int()`` of
    those raises (ValueError/OverflowError) — unguarded, one such hand-edited
    key once cost the whole config, not just the broken value. Non-finite
    floats are rejected too: a ``NaN`` max_seconds or temperature fails much
    later, where nothing can report it.
    """
    try:
        coerced = type(default)(value)
    except (ValueError, OverflowError):
        return None
    if isinstance(coerced, float) and not math.isfinite(coerced):
        return None
    return coerced


def _coerce(key: str, default, value):
    """`value` narrowed to the type its default implies — or `default` when the
    stored value cannot be used at all.

    Same reasoning as the section guard in `_merge`, one level down: a scalar of
    the wrong type slips through the merge just as far and fails much later,
    where nothing can report it. ``"history_max": "many"`` raises inside
    ``App.__init__`` — before the tray, the overlay or any window exists — so
    the app simply never appears and only the log file says why. Repairing the
    plausible hand-edits (a quoted number) and falling back to the default for
    everything else keeps a broken value to the one option it belongs to.

    A default of ``None`` carries no type information (``model_dir``,
    ``input_device``, ``overlay.x/y`` accept null *and* a value), so anything
    stored under such a key is passed through unchanged.
    """
    if default is None:
        return value
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        # 0/1 from a hand-edit is unambiguous; nothing else is.
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
    elif isinstance(default, (int, float)):
        # bool is an int subclass — `true` where a number belongs is a mistake,
        # not a 1, so it must not sneak through the isinstance checks below.
        if isinstance(value, bool):
            pass
        elif isinstance(value, (int, float)):
            coerced = _finite_number(default, value)
            if coerced is not None:
                return coerced
        elif isinstance(value, str):
            # "300" instead of 300 is the classic hand-edit; keep the value.
            coerced = _finite_number(default, value.strip())
            if coerced is not None:
                return coerced
    elif isinstance(value, type(default)):
        return value
    log.warning(
        "config key %r holds unusable %s value %.60r, expected %s — keeping the default %r",
        key, type(value).__name__, value, type(default).__name__, default,
    )
    return default


def _merge(base: dict, override: dict) -> dict:
    """Deep-merge `override` into `base` (the defaults), so new keys appear on
    upgrade without touching what the user configured.

    A stored value that is NOT a dict where the default is one is dropped: it
    would replace a whole nested section (overlay/assistant/integrations) with
    a scalar, and code like ``cfg["overlay"]["enabled"]`` then raises during
    startup — before any UI exists to report it. A hand-edited or truncated
    config.json must cost at most the affected section, never the app. Scalars
    are type-checked against their default by `_coerce` for the same reason.
    """
    for key, value in override.items():
        if isinstance(base.get(key), dict):
            if isinstance(value, dict):
                _merge(base[key], value)
            else:
                log.warning(
                    "config key %r is %s, expected an object — keeping the defaults",
                    key, type(value).__name__,
                )
        elif key in base:
            base[key] = _coerce(key, base[key], value)
        else:
            # A key the defaults don't know (an option of an older build, or a
            # typo): kept verbatim — there is no type to check it against, and
            # nothing reads it.
            base[key] = value
    return base


def _restrict_to_owner(path: Path) -> None:
    """Take group and other off a file's mode (0600 on POSIX), best effort.

    Everything written through :func:`atomic_write_json` is private to the
    user: config.json carries the assistant API key in clear text, and
    history.json every transcript that was ever dictated. The default umask
    leaves both world-readable (0644), so on a shared machine any other local
    account can read the key and the dictation history straight out of the
    config dir.

    Applied to the temp file before the replace, so the target never exists
    with the wider mode even briefly. On Windows os.chmod only toggles the
    read-only bit — harmless here (0600 keeps the file writable), and access
    control comes from the per-user profile directory instead. A filesystem
    that cannot represent the mode (FAT, some network shares) must never cost
    the write itself, hence the catch.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        log.debug("could not restrict the permissions of %s", path, exc_info=True)


def atomic_write_json(path: Path, data) -> None:
    """Write `data` as pretty JSON to `path` atomically: a sibling temp file is
    written and then `os.replace`d over the target, so a crash mid-write never
    leaves a truncated file. The parent directory is created if needed.

    The temp file is fsync'd before the replace. Closing it only hands the
    bytes to the OS cache; without the flush a power loss or OS crash can land
    the rename ahead of the data and leave a zero-length config.json /
    history.json — the very outcome this helper exists to prevent.

    The file is restricted to its owner before the replace — see
    :func:`_restrict_to_owner` for why that matters here.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temp name per writer: two processes saving the same file (the
    # accepted old-build/new-build coexistence, or an unguarded fallback run)
    # would otherwise truncate each other's temp file mid-write and rename the
    # mangled result into place — the exact corruption this helper prevents.
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        _restrict_to_owner(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def sweep_stale_tmp(directory: Path, max_age_s: float = 3600.0) -> None:
    """Best-effort removal of orphaned atomic-write temp files.

    mkstemp gives every writer a unique name, so a hard kill between write
    and replace leaves ``<file>.<random>.tmp`` behind forever (the old fixed
    temp name at least overwrote itself). Age-gated so a concurrent writer's
    in-flight temp file is never touched.
    """
    cutoff = time.time() - max_age_s
    try:
        for tmp in Path(directory).glob("*.tmp"):
            try:
                if tmp.stat().st_mtime < cutoff:
                    tmp.unlink()
                    log.info("removed stale temp file %s", tmp)
            except OSError:
                pass
    except OSError:
        pass


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else config_dir() / "config.json"
        # The config dir collects our own atomic-write leftovers (config and
        # history share it); sweep them once per process start.
        sweep_stale_tmp(self.path.parent)
        # Captured before load(), which writes the defaults when the file is
        # missing. True only on the very first launch — drives the one-time
        # onboarding wizard.
        self.first_run = not self.path.exists()
        # True while the file on disk could not be read: the in-memory data is
        # just the defaults then, and save() must not overwrite what may still
        # be an intact config (e.g. an AV/indexer holding the file at logon).
        self.load_failed = False
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                with open(self.path, encoding="utf-8") as fh:
                    stored = json.load(fh)
                self.data = _merge(copy.deepcopy(DEFAULTS), stored)
            else:
                self.save()
            self.load_failed = False
        except Exception:
            log.exception("could not read %s — using defaults", self.path)
            self.data = copy.deepcopy(DEFAULTS)
            self.load_failed = True

    def save(self) -> bool:
        """Write the config to disk; True when it arrived there.

        Never raises: every caller sits at a UI or worker boundary where an
        unhandled OSError (disk full, read-only dir) would either crash the
        app or — in a --windowed build — vanish into a devnull stderr. The
        False return is the caller's cue to tell the user.

        A config whose *read* failed is preserved, not overwritten: the
        in-memory data is only the defaults, so saving would turn a transient
        read failure into permanent loss of every setting. The unreadable
        file is moved aside once (config.json.bad, replacing any older .bad —
        the newest casualty is the one worth keeping) so later saves work and
        the original stays recoverable; if even that fails, the save is
        refused.
        """
        if self.load_failed:
            bad = self.path.with_name(self.path.name + ".bad")
            try:
                os.replace(self.path, bad)
            except FileNotFoundError:
                pass  # nothing left on disk to preserve
            except OSError:
                log.warning(
                    "not saving %s — the file could not be read at startup and "
                    "may still be intact",
                    self.path,
                )
                return False
            else:
                log.warning("moved the unreadable config aside to %s", bad)
            self.load_failed = False
        try:
            atomic_write_json(self.path, self.data)
        except Exception:
            log.exception("could not save %s", self.path)
            return False
        return True

    def reset(self) -> bool:
        """Restore every setting to DEFAULTS and write them out. True when they
        arrived on disk (same contract as save()).

        The in-memory data is reset either way, so the running app applies the
        defaults even if the file could not be written — the caller surfaces
        the False. `load_failed` is deliberately left alone: its handling in
        save() moves an unreadable config.json aside to .bad instead of
        overwriting it, which is exactly as useful here (the user gets the
        defaults, the file they could not load stays recoverable).
        """
        log.info("resetting %s to the factory defaults", self.path)
        self.data = copy.deepcopy(DEFAULTS)
        return self.save()

    def __getitem__(self, key: str):
        return self.data[key]

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value
