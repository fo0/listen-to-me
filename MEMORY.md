# Memory — Long-Term

Stable project knowledge. **Read at session start.** Rules: `agent_docs/memory_process.md`.

## Architecture Decisions

Structured decisions live in `docs/adr/`. Grep there before contradicting one. This section holds only short, loose notes that don't justify a full ADR.

- **PySide6/Qt over Tkinter/pystray** — the UI was migrated to PySide6 for a modern look, tray, and the animated overlay. (See git history "Revamp UI".) A proper ADR can be back-filled if the choice is revisited.
- **Fully local transcription** — faster-whisper (CTranslate2), no cloud, no account; only the optional assistant + updater touch the network.

## Gotchas & Pitfalls

- **Never touch Qt from a worker thread.** Background threads (hotkey listener, `process`/`live-preview`/`update` workers) must call `App.post(...)` / `App.notify(...)`; the main-thread `QTimer` drains the queue. Direct tray/overlay/widget access off the main thread crashes Qt. (2026-07-19)
- **CUDA errors surface at inference, not just at load.** The cuBLAS/cuDNN failure can appear during `model.transcribe`, so both the load path and the decode path handle the CPU fallback. Transient OOM is deliberately excluded from "GPU unavailable" so one bad run doesn't downgrade the whole session. (2026-07-19)
- **Keep heavy imports lazy.** Qt, `sounddevice`, `pynput`, `faster_whisper`, `numpy` are imported inside functions so `--version`/`--selftest` stay fast and headless. Hoisting them to module scope breaks the CI smoke test and CLI speed. (2026-07-19)
- **Qt-free modules must stay Qt-free.** `icons.py`, `keymap.py`, `help_content.py` import no `QtWidgets`/`QtGui` so they're testable headless and usable by `make_icon.py`/self-test. (2026-07-19)
- **requirements.txt ↔ pyproject.toml ↔ PyInstaller.** Runtime deps are listed in both files; a new dep with C extensions/data may also need a `--collect-all` in `.github/workflows/release.yml`, verified by the built exe's `--selftest`. (2026-07-19)
- **Hold-mode hotkeys can miss the release** (WM/IME grabs, focus change); recording still stops via the overlay/tray Stop entry or the max-length auto-stop. X11 auto-repeat needs the release debounce in `hotkeys.py`. (2026-07-19)
- **Relaunching the frozen exe needs a reset environment.** Since PyInstaller 6.9 a spawned copy of the one-file exe is treated as a worker subprocess that reuses the parent's `_MEI` unpack dir — which is deleted when the old process exits. The updater's restart chain (cmd → batch → new exe) inherited those variables, so the freshly updated app died on startup with a Python-DLL/module error while a manual start of the same exe worked. Any in-app (re)launch of the exe must go through `updater._swap_env()`: strips `_MEIPASS2`/`_PYI_*`, sets `PYINSTALLER_RESET_ENVIRONMENT=1`. (2026-07-21)
- **Qt routes wheel events to hovered combos/spin boxes even while a page scrolls**, silently changing values. Every value widget on a scrollable page needs `qtutil.guard_wheel(...)` (ignore wheel until focused + StrongFocus). `SettingsWindow.__init__` sweeps with `findChildren`, but widgets created *later* (e.g. `MuteTargetRow`) must guard themselves. (2026-07-23)
- **A TCP-port bind is not a reliable single-instance lock on Windows.** Hyper-V/WSL "administered port exclusions" (`netsh int ipv4 show excludedportrange`) can make `bind()` on a fixed port fail although nothing is running (the app then silently refused to start) or *succeed in several processes at once* (multiple instances ran side by side). `singleinstance.py` therefore claims a named kernel mutex on Windows / an `flock`-ed file on POSIX; port 52697 only carries the "show yourself" ping from a second launch. (2026-07-23)
- **Windows drops the overlay window without Qt noticing.** Display sleep / DWM restarts hide layered (`WA_TranslucentBackground`) windows, explorer restarts and fullscreen apps eat `WindowStaysOnTopHint`, monitor changes can strand the position off-screen — while `isVisible()` stays `True`, so a plain `show()` no-ops. The Overlay watchdog re-asserts every 30 s (`raise_()`, `show()` if Qt-hidden) and hard-reshows (`hide()`/`show()`) after a suspend (timer-gap heuristic) or screen add/remove/primary-change signals. (2026-07-23)
- **`--windowed` builds have `sys.stdout`/`sys.stderr` = None.** Any library that writes to them crashes — huggingface_hub's tqdm progress bar killed the OpenVINO model download with `'NoneType' object has no attribute 'write'`. `app._ensure_std_streams()` stubs them with devnull right after logging setup; keep that call early in `main()`. (2026-07-20)

## Failed Approaches

_(none recorded yet)_

## External Dependencies

- **faster-whisper / CTranslate2** — models download from Hugging Face on first use into the HF hub cache (or `model_dir`); later loads are offline (`local_files_only`). GPU needs the NVIDIA CUDA 12 libraries or it falls back to CPU. (2026-07-19)
- **pynput** — global hotkey + synthetic keypress behavior differs per OS (X11 auto-repeat, macOS/Windows send no release on hold). Imported lazily; needs an X display on Linux only when actually used. (2026-07-19)
- **pynput >= 1.8 changed `HotKey.parse` semantics** — non-modifier special keys (`<f9>`, `<space>`, arrows) now parse to `KeyCode.from_vk(...)` instead of `Key` members; only Ctrl/Alt/Shift/Cmd stay `Key` instances. `Listener.canonical` converts the same way, so press-matching still works — but `isinstance(key, KeyCode)` no longer means "character key". `combo_flags` detects typability via `char`/space-vk/known-special-vks; keep any new key-classification logic compatible with both 1.7.x and 1.8.x (requirement is `>=1.7.7`, CI/exe builds pick latest). (2026-07-21)
- **sounddevice / PortAudio** — mono float32 @ 16 kHz (what Whisper expects); device index from settings, `None` = system default. (2026-07-19)
- **onnx-asr (Parakeet backend) resolves models offline-first** — `load_model()` tries the HF cache with `local_files_only=True`, then downloads; but a custom `path`/local_dir that *exists* flips it to hard-offline, so an interrupted first download into `model_dir` leaves a permanently broken folder (backend raises an actionable "delete the folder" error). Parakeet TDT takes **no language/prompt/beam options** (`language`/`target_language` kwargs exist only for Whisper/Canary models); quantization maps `"fp32" → None`. ONNX Runtime providers: always append `CPUExecutionProvider` — a GPU provider that is listed but broken then degrades instead of erroring. Model files follow the `encoder-model[.int8].onnx` pattern in `istupakov/parakeet-tdt-0.6b-v3-onnx`. (2026-07-23)
- **huggingface_hub SSL opt-out is version-split** — hub **>= 1.0 is httpx-based**: `set_client_factory(...)` returning an `httpx.Client(verify=False)` (the default factory lives in `huggingface_hub.utils._http.default_client_factory`; `configure_http_backend` was **removed**). Hub < 1.0 is requests-based: `configure_http_backend(backend_factory=...)` with `Session.verify=False`. Env-var tricks (`CURL_CA_BUNDLE=""`) work with neither. `netutil.py` handles both for the `insecure_ssl` option — the v0.x-only code silently did nothing on the shipped v1.x exe. (2026-07-20)

## User Preferences

- **No new tooling without approval** — there is intentionally no linter/formatter/type-checker/test-framework. Don't add ruff/black/mypy/pytest to make a check pass; match style by hand. (2026-07-19)
- **Windows-first**, Linux/macOS paths kept coherent. (2026-07-19)
