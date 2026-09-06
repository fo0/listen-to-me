# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **App quality pass (`claude/app-quality-model-optimization-7eel5p`, 2026-09-06):** Settings UX review + backend bug hunt + STT model/driver research. Landed so far: `transcriber.resolve_runtime()` — the app's `compute_type = "auto"` used to map to CTranslate2's `"default"`, which runs the float16 Systran presets as **float32 on the CPU**; it now resolves to int8 on the CPU / float16 on a CUDA GPU against what CTranslate2 reports as supported (selftest `compute type resolution`). Every backend exposes `runtime -> (device, precision) | None` for the status card. Settings page "Whisper" → "Engine" (model chooser moves there). Open: fold in the reviewer findings, BACKLOG the deferred P2s, model-preset changes from the research.

> Finished work does not belong here. What a merged branch produced is recorded in `BACKLOG.md → Done`, `agent_docs/key-patterns.md`, `MEMORY.md` and the git history — don't re-add closed branches to this section.

## Open Questions

_(none)_

## Research Notes

- **STT engine delta (2026-09-06):** `docs/research/2026-09-stt-engine-delta.md`. Headline: no new model beats a shipped preset (turbo-german / distil-3.5 / Parakeet v3 all still current); the wins are runtime — CT2 wheels ≥ 4.6.3 need cuBLAS only (no cuDNN), onnxruntime-gpu ≥ 1.27 is CUDA 13, OpenVINO `CACHE_DIR` cuts GPU/NPU load from minutes to seconds. Optional small German model: `canary-180m-flash` via onnx-asr (BACKLOG).
- **Faster STT models + near-realtime translation** (2026-07-23): full report in `docs/research/2026-07-faster-stt-and-translation.md` (branch `claude/faster-translation-models-y5nn6p`). Headlines: `primeline/whisper-large-v3-turbo-german` = −28 % German WER at identical speed (string-only preset add); official `distil-whisper/distil-large-v3.5-ct2` upgrades the EN distil preset; Parakeet-TDT-0.6b-v3 via `onnx-asr` ≈ 20× faster with German ≥ turbo (candidate 3rd backend); the app has NO translation feature yet — cheapest real one is Whisper `task="translate"` (→EN only; **broken on turbo/distil** — silently returns source language) then Opus-MT de↔en on the already-shipped CTranslate2 (<150 ms CPU). License traps: CrisperWhisper/NLLB/SeamlessM4T/Tower+ are CC-BY-NC — never ship. No Whisper large-v4 exists.
- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1) — since shipped as the `openvino` backend. Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope.

## Temporary Notes

- **Overlay icon drop (2026-08-19, `claude/overlay-icon-visibility-bug-po78p4`):** the exact drop mode on the user's Windows machine is still unconfirmed. Leading candidate is the user's own reading — the icon is only buried, not gone — so the watchdog now logs `the floating icon lost its always-on-top state` for that case and `the floating icon was dropped (<probe>)` for a real drop. Whichever line shows up in the log names the cause; until then this stays open. The release build (run 32394925267) then caught a Windows-only bug in the probe itself — fixed on the same branch, see the MEMORY entry.
