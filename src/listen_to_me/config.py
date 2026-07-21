"""Configuration handling: JSON file in the platform config directory."""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
from pathlib import Path

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
    # Transcription backend: "faster-whisper" (NVIDIA CUDA / CPU, default) or
    # "openvino" (Intel CPU / GPU / NPU — needs the optional openvino-genai
    # package: pip install openvino-genai, or the [openvino] extra).
    "backend": "faster-whisper",
    # Whisper device (faster-whisper backend): auto / cpu / cuda.
    "device": "auto",
    # CTranslate2 compute type: auto / int8 / int8_float16 / float16 / float32.
    "compute_type": "auto",
    # OpenVINO device (openvino backend): auto / cpu / gpu / npu.
    # "auto" prefers the GPU, then the NPU, then the CPU.
    "openvino_device": "auto",
    # Precision of the pre-converted OpenVINO model to download: int8 (small +
    # fast, recommended), fp16 (most accurate) or int4 (smallest).
    "openvino_precision": "int8",
    # sounddevice input device index, null = system default.
    "input_device": None,
    # Hard cap for a single recording.
    "max_seconds": 300,
    # How to insert text at the cursor: "paste" (clipboard + Ctrl+V) or "type".
    "injection_mode": "paste",
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
        # Briefly show the transcribed text next to the icon after a recording.
        "show_preview": True,
        # Experimental: transcribe in the background *while* recording and show
        # a rolling live preview of what was understood so far. Costs CPU.
        "live_preview": False,
        # How long the finished transcript stays visible (seconds).
        "preview_seconds": 6,
        # Saved position of the floating icon (null = bottom right).
        "x": None,
        "y": None,
    },
    # Optional Whisper initial prompt (domain vocabulary hint, not an instruction).
    "initial_prompt": "",
    "vad_filter": True,
    # Keep a local history of transcribed text (never the audio) so a lost
    # transcript can be recovered from Settings → History. Stored in
    # history.json next to this config file.
    "history_enabled": True,
    # How many of the most recent transcripts to keep.
    "history_max": 200,
    # In-app updater (checks the GitHub Releases of this repo).
    "update_check_on_start": True,
    "include_prereleases": False,
    # Skip TLS certificate verification for ALL outbound HTTPS connections
    # (Whisper model downloads, the update check, the assistant). Only for
    # corporate proxies that intercept HTTPS with a self-signed certificate —
    # insecure, leave off otherwise.
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
        # The Discord preset is disabled by default — enable it and set a
        # matching "Push to Mute" keybind in Discord to use it. The suggested
        # <f9> deliberately shares no keys with the default recording hotkey
        # (<ctrl>+<alt>+<space>): a hold-mode keybind that reused those modifiers
        # would desync them when released while you still hold the record chord.
        "targets": [
            {
                "name": "Discord",
                "enabled": False,
                "mode": "hold",
                "hotkey": "<f9>",
            },
        ],
    },
}


def open_path(path) -> None:
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
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / "ListenToMe"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ListenToMe"
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "listen-to-me"


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def atomic_write_json(path: Path, data) -> None:
    """Write `data` as pretty JSON to `path` atomically: a sibling temp file is
    written and then `os.replace`d over the target, so a crash mid-write never
    leaves a truncated file. The parent directory is created if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else config_dir() / "config.json"
        # Captured before load(), which writes the defaults when the file is
        # missing. True only on the very first launch — drives the one-time
        # onboarding wizard.
        self.first_run = not self.path.exists()
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
        except Exception:
            log.exception("could not read %s — using defaults", self.path)
            self.data = copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        atomic_write_json(self.path, self.data)

    def __getitem__(self, key: str):
        return self.data[key]

    def __setitem__(self, key: str, value) -> None:
        self.data[key] = value
