# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.** Rules: `agent_docs/memory_process.md`.

## Current Work

- **`claude/overlay-cursor-anchor` (2026-09-10) — #196, `2fc4942` + a merge of `main`, no PR yet.** `overlay.preview_anchor` (`"icon"` default / `"cursor"`) moves **both** transcript previews to the mouse pointer: placed by the pure `cursor_bubble_position()` (edge flip, clamped to the screen the _pointer_ is on, never over the pointer), followed via `tick_cursor_preview()` on `App._poll`'s 100 ms drain — no second timer. The two questions #196 left open are answered in code and in the Settings hint: it works with the icon **off**, and it obeys `overlay.always_on_top` in both anchors. Found on the way: the bubble never carried `WindowTransparentForInput`, so it swallowed every click — latent beside the icon, not under the cursor. Docs pass done here (`README*.md`, `CHANGELOG.md`, `key-patterns.md`, BACKLOG #56–#58); `ARCHITECTURE.mmd` and `CLAUDE.md` need nothing. **Open:** real pointer behaviour, click-through and mixed-scaling multi-monitor are all unverifiable offscreen (#56–#58) — a manual pass on a two-monitor Windows box is what is left before this is done.

> Finished work does not belong here. What a merged branch produced is recorded in `BACKLOG.md → Done`, `agent_docs/key-patterns.md`, `MEMORY.md` and the git history — don't re-add closed branches to this section.

## Open Questions

_(none)_

## Research Notes

- **STT engine delta (2026-09-06):** `docs/research/2026-09-stt-engine-delta.md`. Headline: no new model beats a shipped preset (turbo-german / distil-3.5 / Parakeet v3 all still current); the wins are runtime — CT2 wheels ≥ 4.6.3 need cuBLAS only (no cuDNN), onnxruntime-gpu ≥ 1.27 is CUDA 13, OpenVINO `CACHE_DIR` cuts GPU/NPU load from minutes to seconds. Optional small German model: `canary-180m-flash` via onnx-asr (BACKLOG).
- **Faster STT models + near-realtime translation** (2026-07-23): full report in `docs/research/2026-07-faster-stt-and-translation.md` (branch `claude/faster-translation-models-y5nn6p`). Headlines: `primeline/whisper-large-v3-turbo-german` = −28 % German WER at identical speed (string-only preset add); official `distil-whisper/distil-large-v3.5-ct2` upgrades the EN distil preset; Parakeet-TDT-0.6b-v3 via `onnx-asr` ≈ 20× faster with German ≥ turbo (candidate 3rd backend); the app has NO translation feature yet — cheapest real one is Whisper `task="translate"` (→EN only; **broken on turbo/distil** — silently returns source language) then Opus-MT de↔en on the already-shipped CTranslate2 (<150 ms CPU). License traps: CrisperWhisper/NLLB/SeamlessM4T/Tower+ are CC-BY-NC — never ship. No Whisper large-v4 exists.
- **Hardware acceleration beyond CUDA** (2026-07-20): CTranslate2/faster-whisper supports NVIDIA CUDA + CPU only — no Intel GPU, no NPU, no ROCm planned. Best path for Intel iGPU/Arc/NPU: **OpenVINO GenAI `WhisperPipeline`** (`pip install openvino-genai`, device `"CPU"|"GPU"|"NPU"`, pre-converted models on HF under `OpenVINO/whisper-*-ov`, NPU works out of the box since 2025.1) — since shipped as the `openvino` backend. Alternative for vendor-neutral GPU (incl. AMD): whisper.cpp via `pywhispercpp` with Vulkan — but PyPI wheels are CPU-only, would need own CI wheel build; no NPU. ONNX Runtime DirectML is in maintenance mode (successor: Windows ML) — not worth adopting. AMD Ryzen AI NPU needs its own heavyweight SW stack; Qualcomm NPU needs an ARM64 build — both out of scope.

## Temporary Notes

- **Overlay icon drop (2026-08-19, `claude/overlay-icon-visibility-bug-po78p4`):** the exact drop mode on the user's Windows machine is still unconfirmed. Leading candidate is the user's own reading — the icon is only buried, not gone — so the watchdog now logs `the floating icon lost its always-on-top state` for that case and `the floating icon was dropped (<probe>)` for a real drop. Whichever line shows up in the log names the cause; until then this stays open. The release build (run 32394925267) then caught a Windows-only bug in the probe itself — fixed on the same branch, see the MEMORY entry.
