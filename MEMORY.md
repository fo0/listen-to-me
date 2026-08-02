# Memory — Long-Term

Stable project knowledge. **Read at session start.** Rules: `agent_docs/memory_process.md`.

## Architecture Decisions

Structured decisions live in `docs/adr/`. Grep there before contradicting one. This section holds only short, loose notes that don't justify a full ADR.

- **PySide6/Qt over Tkinter/pystray** — the UI was migrated to PySide6 for a modern look, tray, and the animated overlay. (See git history "Revamp UI".) A proper ADR can be back-filled if the choice is revisited.
- **Fully local transcription** — faster-whisper (CTranslate2), no cloud, no account; only the optional assistant + updater touch the network.
- **The updater is carved out of `insecure_ssl`** — see ADR-0002. (#20, 2026-07-27)
- **The agent never merges or releases on its own** — an explicit interactive user command is required; the allowlist-gated routine exception of ADR-0003 (and its allowlist file) was dropped as dead weight, see ADR-0004. Don't reintroduce a routine, schedule or prompt-declared bypass. (#21, 2026-08-02)

## Gotchas & Pitfalls

- **Never touch Qt from a worker thread.** Background threads (hotkey listener, `process`/`live-preview`/`update` workers) must call `App.post(...)` / `App.notify(...)`; the main-thread `QTimer` drains the queue. Direct tray/overlay/widget access off the main thread crashes Qt. (2026-07-19)
- **CUDA errors surface at inference, not just at load.** The cuBLAS/cuDNN failure can appear during `model.transcribe`, so both the load path and the decode path handle the CPU fallback. Transient OOM is deliberately excluded from "GPU unavailable" so one bad run doesn't downgrade the whole session. (2026-07-19)
- **Keep heavy imports lazy.** Qt, `sounddevice`, `pynput`, `faster_whisper`, `numpy` are imported inside functions so `--version`/`--selftest` stay fast and headless. Hoisting them to module scope breaks the CI smoke test and CLI speed. (2026-07-19)
- **Qt-free modules must stay Qt-free.** `icons.py`, `keymap.py`, `help_content.py` import no `QtWidgets`/`QtGui` so they're testable headless and usable by `make_icon.py`/self-test. (2026-07-19)
- **requirements.txt ↔ pyproject.toml ↔ PyInstaller.** Runtime deps are listed in both files; a new dep with C extensions/data may also need a `--collect-all` in `.github/workflows/release.yml`, verified by the built exe's `--selftest`. (2026-07-19)
- **Qt routes wheel events to hovered combos/spin boxes even while a page scrolls**, silently changing values. Every value widget on a scrollable page needs `qtutil.guard_wheel(...)` (ignore wheel until focused + StrongFocus). `SettingsWindow.__init__` sweeps with `findChildren`, but widgets created *later* (e.g. `MuteTargetRow`) must guard themselves. (2026-07-23)
- **Everything about autostart fails silently by nature.** Nobody watches a logon: a `Run` value that wasn't written, an entry Windows blocked, or a command that starts nothing all look identical to a working setup until the machine is rebooted. So `enable()` reads its own write back (`AutostartError`), `sync()` returns a user-facing problem string instead of swallowing it, `App._sync_autostart` notifies (forced), and Settings → General shows the command the OS really has on file. Keep any new autostart path verifiable the same way. (2026-07-30)
- **`--windowed` builds have `sys.stdout`/`sys.stderr` = None.** Any library that writes to them crashes — huggingface_hub's tqdm progress bar killed the OpenVINO model download with `'NoneType' object has no attribute 'write'`. `app._ensure_std_streams()` stubs them with devnull right after logging setup; keep that call early in `main()`. (2026-07-20)

> Qt/Windows UI traps that are already locked in by a `gui_smoke` check (QSS `:disabled` specificity, ghost widgets, combo/label minimum width, theme-switch repaint, untrusted history values, overlay watchdog) and the autostart / single-instance history live in `agent_docs/memory_archive/2026-07.md`. Grep there before re-deriving one.

## Failed Approaches

_(none recorded yet — superseded designs live in the archive: the TCP-port single-instance lock, the editable model combo, `is_enabled()`-only autostart.)_

## External Dependencies

- **faster-whisper / CTranslate2** — models download from Hugging Face on first use into the HF hub cache (or `model_dir`); later loads are offline (`local_files_only`). GPU needs the NVIDIA CUDA 12 libraries or it falls back to CPU. (2026-07-19)
- **pynput** — global hotkey + synthetic keypress behavior differs per OS (X11 auto-repeat, macOS/Windows send no release on hold). Imported lazily; needs an X display on Linux only when actually used. (2026-07-19)
- **pynput >= 1.8 changed `HotKey.parse` semantics** — non-modifier special keys (`<f9>`, `<space>`, arrows) now parse to `KeyCode.from_vk(...)` instead of `Key` members; only Ctrl/Alt/Shift/Cmd stay `Key` instances. `Listener.canonical` converts the same way, so press-matching still works — but `isinstance(key, KeyCode)` no longer means "character key". `combo_flags` detects typability via `char`/space-vk/known-special-vks; keep any new key-classification logic compatible with both 1.7.x and 1.8.x (requirement is `>=1.7.7`, CI/exe builds pick latest). (2026-07-21)
- **sounddevice / PortAudio** — mono float32 @ 16 kHz (what Whisper expects); device index from settings, `None` = system default. (2026-07-19)

> onnx-asr / Parakeet model-resolution quirks and the huggingface_hub v0.x↔v1.x SSL split are in `agent_docs/memory_archive/2026-07.md` — read them before touching `transcriber_parakeet.py` or `netutil.py`.

## User Preferences

- **No new tooling without approval** — there is intentionally no linter/formatter/type-checker/test-framework. Don't add ruff/black/mypy/pytest to make a check pass; match style by hand. (2026-07-19)
- **Windows-first**, Linux/macOS paths kept coherent. (2026-07-19)

## Archive

- `agent_docs/memory_archive/2026-07.md` — Qt/Windows UI gotchas locked in by gui_smoke checks, autostart + single-instance design history, Parakeet/huggingface_hub dependency quirks (archived 2026-07-30)
