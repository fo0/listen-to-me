# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **First-run onboarding wizard** — Branch `claude/onboarding-wizard`: new `onboarding.py` (QWizard: hotkey / language / model / backend + device / microphone / autostart + tray), triggered via new `Config.first_run` (config file absent before load). Shared dropdown lists extracted from `settings_ui.py` into Qt-free `choices.py` (incl. label↔value mapping + `input_device_choices`). `integrations.mute_while_recording` default flipped to `False` (opt-in). Verified: compileall + headless non-Qt smoke checks pass locally; Qt construction covered by CI `gui_smoke` (new wizard-accept assertions in `selftest.py`). (2026-07-21)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
