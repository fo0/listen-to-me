# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Settings self-test buttons** — Branch `claude/settings-test-buttons`: new Qt-free `diagnostics.py` (DiagnosticsEngine: model download/load, mic test with clip_stats verdict, end-to-end transcription test against a *snapshot dict* of the unsaved UI values) + buttons in `settings_ui.py` (General: Test hotkey with paused app listener + 10 s timeout w/ generation guard; Whisper: Download/load model + Test transcription 5 s with status/level in one progress bar; Audio: Test microphone 3 s with live level bar). One diagnostic at a time (`_diag_busy`); dialog `done()` cancels running tests and re-registers the app hotkey. Selftest: `_diagnostics_engine` (light) + `_clip_stats_verdicts` (full). `docs/ARCHITECTURE.svg` NOT re-rendered (headless Chrome unavailable in this sandbox) — regenerate with `npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg`. Local env has no PySide6/Pillow — Qt UI construction verified by CI gui_smoke on the PR. (2026-07-20)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
