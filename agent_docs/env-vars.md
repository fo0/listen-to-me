# Environment Variables & Secret Locations

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps the three the agent must know; this file is the full list.

The app reads **no custom env vars for its own config** — settings live in `config.json` under the platform config dir (`config.py → config_dir()`). There is no `.env` file and no `.env.example`. Everything below is third-party, platform, or set by the release pipeline for itself.

## Variables

| Variable                                                 | Description                                                                                                                                                                                                                                                                                                                                                    | Default                    |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| `HF_HOME` / `HF_HUB_CACHE` / `HUGGINGFACE_HUB_CACHE`     | Where faster-whisper / OpenVINO / onnx-asr cache downloaded models                                                                                                                                                                                                                                                                                             | `~/.cache/huggingface/hub` |
| `QT_QPA_PLATFORM`                                        | Set to `offscreen` for headless Qt (the CI smoke test uses this)                                                                                                                                                                                                                                                                                               | (unset)                    |
| `APPDATA` / `XDG_CONFIG_HOME`                            | Base for the app config dir (`ListenToMe` / `listen-to-me`)                                                                                                                                                                                                                                                                                                    | OS default                 |
| `PYTHONPATH`                                             | `src` when running from a checkout (`PYTHONPATH=src python -m listen_to_me`). Note: an autostart entry registered from such a checkout starts nothing — `autostart.launch_problem()` detects it                                                                                                                                                                | (unset)                    |
| `PYINSTALLER_RESET_ENVIRONMENT` / `_MEIPASS2` / `_PYI_*` | PyInstaller one-file internals. Any in-app (re)launch of the frozen exe must go through `updater._swap_env()`, which strips the inherited ones and sets the reset flag                                                                                                                                                                                         | set by PyInstaller         |
| `COMSPEC` / `SystemRoot`                                 | Windows only, read-only: where `updater._cmd_exe()` finds the interpreter that runs the update-swap batch. `%COMSPEC%` first, then `%SystemRoot%\System32\cmd.exe`; a bare `cmd` off `PATH` is only the last resort, so `PATH` is not the trust boundary of the exe-replacing code path                                                                        | set by Windows             |
| `PORTAUDIO_COMMIT` / `PORTAUDIO_DLL`                     | Release pipeline only, never read by the app: the PortAudio master commit the `build-windows` job builds, and where the resulting WASAPI-loopback DLL lands. Its three consumers — the size listing, the export verification and PyInstaller's `--add-binary` — all read the path from the variable, so no step can drift from the built file (#194, ADR-0010) | set in `release.yml`       |

## Secrets Locations

| Secret class      | Where it lives                                                             | Never commit |
| ----------------- | -------------------------------------------------------------------------- | ------------ |
| Assistant API key | user's `config.json` → `assistant.api_key` (local, outside the repo)       | ✅ Never     |
| CI/CD secrets     | GitHub Actions `GITHUB_TOKEN` (auto-provided; used for the release upload) | ✅ Never     |
| Test fixtures     | Synthetic values only — never real credentials                             | ✅ Never     |

Rules: the app stores no secrets in-repo; the only user secret (the optional assistant API key) lives in their local config file. Never log it, never commit a real one. Never run `gh secret set` without an explicit user command. The `security-review` skill scans for committed secrets.

## Adding a new variable

1. Add a row above with description + default.
2. If it is a secret, add a row to _Secrets Locations_ and request the value from the user — never invent one.
3. If it changes app behavior, reflect it in `README.md` and, when it becomes a config option, in `config.py DEFAULTS` + the Settings UI.

<!-- Generated by claude-code-optimizer v1.42.0 -->
