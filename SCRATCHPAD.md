# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **Insecure-SSL option (corporate proxies)** — Branch `claude/insecure-ssl-option`: new `insecure_ssl` config key + `netutil.py` (requests `verify=` switch + huggingface_hub client factory for both hub >= 1.0/httpx and < 1.0/requests), checkbox in Settings → General, README/help/diagram updated. Second commit fixes the windowed-build model-download crash (`'NoneType' object has no attribute 'write'`, user report from exe 2026.07.20.44): tqdm wrote to `sys.stderr=None` → `app._ensure_std_streams()` devnull stub. `docs/ARCHITECTURE.svg` NOT re-rendered (headless Chrome unavailable in this sandbox) — regenerate with `npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg`. (2026-07-20)

## Open Questions

_(none)_

## Research Notes

- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1). Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope. Integration idea: `backend` config key (`faster-whisper` | `openvino`) + optional dependency, lazy import, separate model cache (OpenVINO IR format ≠ CT2 format).

## Temporary Notes

_(none)_
