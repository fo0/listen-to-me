# API Reference

Listen To Me is a desktop GUI app — it exposes **no served HTTP API**. This file documents the interfaces it *does* have: a small CLI, the config schema, and the two external HTTP services it *consumes*.

## Command-Line Interface

Entry point: `listen_to_me.app:main` (console scripts `listen-to-me` / `listen-to-me-gui`; also `python -m listen_to_me`).

| Flag | Effect |
|------|--------|
| `--version` | Print `Listen To Me <version>` and exit `0`. Does **not** import Qt. |
| `--selftest` | Run the packaging self-test (`selftest.run`); writes `<tempdir>/listen-to-me-selftest.log`, exits non-zero on failure. Used by CI after the PyInstaller build. |
| _(none)_ | Launch the tray app. A localhost single-instance lock (port `52697`) makes a second launch exit quietly. |

Own flags are stripped before Qt sees `sys.argv` (`sys.argv[:1]`), so they never clash with Qt options.

## Configuration Schema

Config is a JSON file in the platform config dir (`config.py → config_dir()`):
- Windows: `%APPDATA%\ListenToMe\config.json`
- Linux: `~/.config/listen-to-me/config.json`
- macOS: `~/Library/Application Support/ListenToMe/config.json`

The authoritative schema is `DEFAULTS` in `src/listen_to_me/config.py` (deep-merged over the stored file, so new keys appear automatically on upgrade). Top-level groups: hotkey/model/device settings, `overlay`, `assistant`, `integrations`, plus `history_*`, `update_*` flags. When adding a key: update `DEFAULTS`, wire it into `settings_ui.py`, and reflect it in the README settings table.

`history.json` (next to the config) stores recent transcript **text only** — never audio.

## Consumed External Services

### Assistant — OpenAI-compatible Chat Completions (`assistant.py`, optional)
- **Endpoint:** `POST {base_url}/chat/completions` (default `base_url` = `http://localhost:11434/v1`, i.e. local Ollama; works with LM Studio, llama.cpp, OpenWebUI, or a hosted API).
- **Auth:** `Authorization: Bearer <api_key>` when `assistant.api_key` is set (stored in the user's local config).
- **Request:** `model`, `messages` (system prompt + the raw transcript), `temperature`, `timeout` — all from `cfg["assistant"]`.
- **Use:** post-processes the transcript (punctuation, filler removal, dictated formatting). On any failure the raw transcript is inserted instead (fail-soft).

### Updater — GitHub Releases API (`updater.py`)
- **Endpoint:** GitHub Releases of `fo0/listen-to-me`.
- **Use:** lists releases newer than the running build with changelogs; on a frozen Windows build, downloads the new `.exe` and swaps it in on restart.
- **Failure mode:** best-effort — a network/API error is silent (startup check) or surfaced in the Updates page.

### Model download — Hugging Face Hub (via faster-whisper)
- Whisper models are fetched from Hugging Face on first use into the HF hub cache (or `model_dir`). Later loads are fully offline (`local_files_only`). No direct HTTP code in this repo — handled inside faster-whisper.

## Internal Event Interface

`App.post(kind, payload)` is the thread-safe channel from any background thread to the main loop. Event kinds handled in `app.py → _handle`: `toggle`, `hotkey_press`, `hotkey_release`, `preview_text`, `flash_text`, `toggle_overlay`, `cancel`, `auto_stop`, `done`, `notify`, `settings`, `updates`, `help`, `open_config`, `quit`. This is the app's real "API surface" for wiring new triggers.
