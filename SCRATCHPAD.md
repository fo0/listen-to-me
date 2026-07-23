# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Single-instance guard + overlay watchdog** (branch `claude/app-instances-overlay-icon-nnv62z`) — user saw multiple ListenToMe processes and the floating icon vanishing after idle. New `singleinstance.py`: named mutex (Windows) / flock file (POSIX) as the guard, port 52697 demoted to an activation channel — a second launch pings the running instance, which notifies + re-asserts the overlay + opens Settings. `overlay.py`: 30 s watchdog (`_reassert`) with hard hide/show after suspend (timer-gap) or screen changes. Selftest: `_single_instance_guard` + watchdog asserts in `_gui_construction`. Note: one-file PyInstaller always shows 2 processes per instance (bootloader parent + app child) in Task Manager — expected, not a bug. (2026-07-23)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
