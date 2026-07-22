# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Settings UX polish** (branch `claude/settings-ux-polish`) — sidebar gets section headers (SETTINGS: General…Assistant / MORE: History, Updates, Help; nav rows carry the stack index in UserRole since headers break the 1:1 row↔page mapping — use `_show_page(title)`/`_nav_row`). General's "Options" box split into Behavior / Startup / Network cards (insecure-SSL now under Network with a warning hint). New **Apply** button (save + apply without closing, footer feedback label) and an **unsaved-changes guard**: `_collect()` snapshots every widget value, `reject()` prompts Save/Discard/Cancel when dirty. `_save` refactored into `_collect`/`_validate`/`_apply_values`; validation failures now jump to the offending page + field. Live-typing checkbox greys out while the OpenVINO backend is selected. gui_smoke covers nav mapping + dirty tracking. Needs on-Windows visual check. (2026-07-22)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
