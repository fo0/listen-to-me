# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **`claude/portaudio-loopback-dll` (2026-09-10) — #194 + #195, four commits (`bc75435`), no PR yet.** **#194:** `release.yml` builds `portaudio.dll` from PortAudio master pinned at `a4dbf68c…`, **refuses the release** unless the fresh DLL loads and exports `PaWasapi_IsLoopback`, and bundles it with `--add-binary`; the new `portaudio.py` prepends the bundle dir to `PATH` from `main()`'s first statement, so `sounddevice`'s `find_library("portaudio")` step wins over its own wheel copy. **No device code changed** — upstream marks every render endpoint's loopback twin `[Loopback]`, which `LOOPBACK_HINTS` already scored highest. New **ADR-0010** (supersedes only ADR-0009's rejected "ship a newer DLL" alternative; the maintainer approved that option in #192, so that decision is closed). **#195:** the system-audio picker is now two labelled groups with loopback rows named after the **output** they record, an empty first group keeping its heading, and a hint naming the outputs no loopback device covers (`audio.list_output_devices()` is back as its data source). Docs pass done in this session: ADR-0010, `README.md`, `README.de.md`, `CHANGELOG.md`, `CLAUDE.md`, `MEMORY.md`, `agent_docs/key-patterns.md`, `agent_docs/refactoring_guidelines.md` (line counts re-measured), `docs/ARCHITECTURE.mmd` + `.svg`. **Open:** the whole PortAudio build is unverifiable until a release is dispatched — `release.yml` is `workflow_dispatch`-only and guarded to `main`, so no PR can exercise it (BACKLOG #49–#52).

> Finished work does not belong here. What a merged branch produced is recorded in `BACKLOG.md → Done`, `agent_docs/key-patterns.md`, `MEMORY.md` and the git history — don't re-add closed branches to this section.

## Open Questions

_(none)_

## Research Notes

- **STT engine delta (2026-09-06):** `docs/research/2026-09-stt-engine-delta.md`. Headline: no new model beats a shipped preset (turbo-german / distil-3.5 / Parakeet v3 all still current); the wins are runtime — CT2 wheels ≥ 4.6.3 need cuBLAS only (no cuDNN), onnxruntime-gpu ≥ 1.27 is CUDA 13, OpenVINO `CACHE_DIR` cuts GPU/NPU load from minutes to seconds. Optional small German model: `canary-180m-flash` via onnx-asr (BACKLOG).
- **Faster STT models + near-realtime translation** (2026-07-23): full report in `docs/research/2026-07-faster-stt-and-translation.md` (branch `claude/faster-translation-models-y5nn6p`). Headlines: `primeline/whisper-large-v3-turbo-german` = −28 % German WER at identical speed (string-only preset add); official `distil-whisper/distil-large-v3.5-ct2` upgrades the EN distil preset; Parakeet-TDT-0.6b-v3 via `onnx-asr` ≈ 20× faster with German ≥ turbo (candidate 3rd backend); the app has NO translation feature yet — cheapest real one is Whisper `task="translate"` (→EN only; **broken on turbo/distil** — silently returns source language) then Opus-MT de↔en on the already-shipped CTranslate2 (<150 ms CPU). License traps: CrisperWhisper/NLLB/SeamlessM4T/Tower+ are CC-BY-NC — never ship. No Whisper large-v4 exists.
- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1) — since shipped as the `openvino` backend. Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope.

## Temporary Notes

- **Overlay icon drop (2026-08-19, `claude/overlay-icon-visibility-bug-po78p4`):** the exact drop mode on the user's Windows machine is still unconfirmed. Leading candidate is the user's own reading — the icon is only buried, not gone — so the watchdog now logs `the floating icon lost its always-on-top state` for that case and `the floating icon was dropped (<probe>)` for a real drop. Whichever line shows up in the log names the cause; until then this stays open. The release build (run 32394925267) then caught a Windows-only bug in the probe itself — fixed on the same branch, see the MEMORY entry.
