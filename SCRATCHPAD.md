# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Wheel-guard fix + settings facelift** (branch `claude/whisper-dropdown-scroll-fix-lxf9kd`, issue #12) — `qtutil.guard_wheel()`: event filter ignores wheel on unfocused combos/spin boxes (event propagates → page scrolls) + StrongFocus; swept over SettingsWindow/OnboardingWizard via `findChildren`, `MuteTargetRow` guards its own combo (created after the sweep). Theme polish: themed QToolTip, horizontal scrollbar styling, disabled-input background, dropdown item padding, red `destructive` button property (Clear history / Remove). gui_smoke verifies focus policy + that a synthetic QWheelEvent leaves values unchanged. Predecessor UX-polish PR #11 is merged. (2026-07-23)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
