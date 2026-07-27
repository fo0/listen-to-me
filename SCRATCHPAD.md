# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Autostart entry survives an exe replacement** (branch `claude/systemstart-entries-update-9pqgsn`) — question was whether an update invalidates the OS autostart entry. In-app update: no, the swap keeps the running exe's path/name. Manual update (dated release exe, rename, move): yes, it broke silently — `is_enabled()` only checked that the entry exists. `autostart.sync()` now repairs a stale command via `stored_command()` + `_refresh_reason` (target gone / another frozen build registered), without letting a source-checkout run hijack an installed build's entry. New `autostart entry refresh` light selftest check. (2026-07-27)

- **Bug + UI/UX review sweep** (branch `claude/bugs-ui-ux-review-mt6elq`) — full-codebase review (not diff-based) for bugs and UI/UX, then fixed everything found. 6 functional fixes: `config._merge` no longer lets a non-dict stored value wipe a whole section (that made the app fail to start), `Recorder.start` no longer wedges the recorder when `stream.start()` fails, History rows are detached before `deleteLater` (ghost rows), `history._load` normalizes `text` to a non-empty string, the onboarding key picker pauses the live global hotkey, and paste falls back to typing instead of surfacing as "Transcription failed". 7 UI/UX fixes: theme-switch repaint of the code-drawn icons + Help sheet, replaced settings windows are destroyed (leak), minimize/maximize on the main window, footer "Cancel" → "Close", Parakeet greys out the settings it ignores, tooltips on the model-folder buttons, hero hint contrast. 4 new light selftest checks + extended `_gui_construction`. Closes BACKLOG #8/#13/#14. (2026-07-26)

- **UI revamp + Home hub** (branch `claude/ui-design-revamp-hnvrw2`, merged as PR #18) — full UI refresh plus a "home / entry area with all important functions". New `home_page.py`, new `glyphs.py` (QPainter line icons), branded sidebar, refreshed theme (indigo accent `#4f6ef7`, tinted nav selection, per-state hero gradient — red while recording). SettingsWindow is now the app's main window (title = app name, Home preselected); `App._set_state` mirrors state via `set_app_state`. (2026-07-25)

## Open Questions

_(none)_

## Research Notes

- **Faster STT models + near-realtime translation** (2026-07-23): full report in `docs/research/2026-07-faster-stt-and-translation.md` (branch `claude/faster-translation-models-y5nn6p`). Headlines: `primeline/whisper-large-v3-turbo-german` = −28 % German WER at identical speed (string-only preset add); official `distil-whisper/distil-large-v3.5-ct2` upgrades the EN distil preset; Parakeet-TDT-0.6b-v3 via `onnx-asr` ≈ 20× faster with German ≥ turbo (candidate 3rd backend); the app has NO translation feature yet — cheapest real one is Whisper `task="translate"` (→EN only; **broken on turbo/distil** — silently returns source language) then Opus-MT de↔en on the already-shipped CTranslate2 (<150 ms CPU). License traps: CrisperWhisper/NLLB/SeamlessM4T/Tower+ are CC-BY-NC — never ship. No Whisper large-v4 exists.
- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
