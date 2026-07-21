# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Settings status card + cancellable tests/downloads** (branch `claude/settings-status-ux`) — Whisper page gets a "Detected hardware & model status" card (CUDA device count via ctranslate2, OpenVINO install + device list incl. FULL_DEVICE_NAME, selected-model cache state; auto-probed on first page open, debounced re-probe on model/backend/precision/model_dir change). Cancel buttons for model download / transcription test (Whisper), microphone test (Audio) and the update download (Updates, via `updater.DownloadCancelled`). Diag signals now carry a generation int so cancelled/detached workers can't emit stale results; a model download can't be truly aborted (hf blocking call) — Cancel detaches the worker and swaps in a fresh `DiagnosticsEngine`. Closing the window now also aborts a running update download. Needs on-Windows manual check of the status card values. (2026-07-21)

- **Live typing (experimental)** — new `livetype.py`: per-take worker types stable transcript segments at the cursor *while* recording (LocalAgreement-2: two consecutive greedy passes must agree AND the segment must end ≥1 s before the snapshot end). Append-only, `sanitize_typed_text` (printable chars only, no Enter/Tab), `type_plain` pauses word-by-word while Ctrl/Alt/Shift/Win is physically held (Win32 `GetAsyncKeyState`; other platforms rely on the hold-mode gate). Final `_process` pass transcribes only the audio after `committed_frames` and types the remainder (`type_plain_blocking` waits for chord release). Config `live_typing` (default off), checkbox in Settings → General. Gates: faster-whisper only (OpenVINO has no segment timestamps), hold mode only with modifier-free non-typable hotkey (`Hotkeys.combo_flags` — injected chars would fake a hotkey release). Assistant skipped for live takes (typed text can't be rewritten). Not yet committed; needs on-Windows manual test. (2026-07-21)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
