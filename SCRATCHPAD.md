# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Updater restart crash fix** — Branch `claude/den-updater-python-error-862o53`: user hit a Python error dialog right after the in-app update restarted the app (manual start of the same exe worked). Cause: PyInstaller ≥ 6.9 bootloader env inherited through the swap chain (see MEMORY.md gotcha). Fix: `updater._swap_env()` on the swapper `Popen`, `start /D` for a sane cwd, plus `verify_download()` (size + sha256 digest from the releases API) before the swap so a truncated download can no longer brick the install. **Note:** the fix lives in the *running* app — updating FROM a pre-fix build will show the error once more; the first update FROM a fixed build restarts cleanly. (2026-07-21)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
