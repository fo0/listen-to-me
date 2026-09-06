# Local STT engines — delta since July 2026

Verified 2026-09-06 against the live Hugging Face / PyPI / GitHub sources (URLs inline). Baseline: `2026-07-faster-stt-and-translation.md`. Only what is **new or changed** is listed; everything else there still holds.

## Conclusion

The preset list in `choices.MODEL_CHOICES` is still state of the art for this app's two target languages: `jimmymeister/whisper-large-v3-turbo-german-ct2` remains the best German Whisper (primeline has published nothing since 2024-12; the non-turbo `whisper-large-v3-german` is both worse — 2.734 vs 2.628 All-WER on primeline's own table — and twice the size), `distil-large-v3.5` remains the newest distil model, and Parakeet-TDT-0.6b-v3 remains the fastest German-capable engine. **No new model beats a shipped preset within the engines the app already carries.** The wins found are in _how_ the presets run — compute type, compile cache, driver hygiene — and those landed in the `claude/app-quality-model-optimization-7eel5p` branch (#168).

## A. faster-whisper / CTranslate2 presets

| Item                                                 | Verified fact                                                                                                                                                                       | Action                      |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| faster-whisper                                       | Latest still **1.2.1** (2025-10-31); `_MODELS` on master identical to the tag ([utils.py](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.2.1/faster_whisper/utils.py)) | none                        |
| `large-v3-turbo` alias                               | → `mobiuslabsgmbh/faster-whisper-large-v3-turbo`, which now 307-redirects to `dropbox-dash/faster-whisper-large-v3-turbo` (MIT, 1622 MB). HF renames keep a permanent redirect.     | none — alias keeps working  |
| `Systran/faster-whisper-large-v3-turbo`              | does **not** exist                                                                                                                                                                  | never reference it          |
| Preset sizes                                         | tiny 78 · base 148 · **small 486** · medium 1531 · large-v3 3091 · distil-large-v3 1516 MB (HF API blob sums)                                                                       | `small` label → ~490 MB ✔   |
| German turbo                                         | `jimmymeister/…-ct2` = current conversion of unchanged primeline weights (Apache-2.0, 1624 MB)                                                                                      | keep                        |
| `cstr/whisper-large-v3-turbo-german-int8_float32`    | Apache-2.0, **818 MB** int8 CT2 of the same fine-tune, 84 downloads (2026-08)                                                                                                       | optional; too little uptake |
| CrisperWhisper (now `nyralabs/`), Swiss-German turbo | cc-by-nc-4.0                                                                                                                                                                        | never ship                  |

## B. onnx-asr (Parakeet backend)

| Item                               | Verified fact                                                                                                                                                                                                                           | Action                                           |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| onnx-asr                           | **0.12.0** (2026-07-15): GigaAM-multilingual, conv-based preprocessors; note _"current onnxruntime-gpu versions require CUDA 13"_ ([release](https://github.com/istupakov/onnx-asr/releases/tag/v0.12.0))                               | pin `>=0.12` fine                                |
| Newer Parakeet                     | none — `parakeet-tdt-0.6b-v3.1` does not exist; `parakeet-unified-en-0.6b` / `nemotron-speech-streaming-en-0.6b` are EN-only, license "other"                                                                                           | keep v3 as the model                             |
| **canary-180m-flash**              | CC-BY-4.0, 182 M params, **en/de/fr/es**, German MLS 4.81 / CV16.1 5.94 WER; ONNX int8 ≈ 215 MB via `istupakov/canary-180m-flash-onnx`; needs `recognize(wav, language="de")` ([card](https://huggingface.co/nvidia/canary-180m-flash)) | BACKLOG #28: low-footprint option, not a default |
| canary-1b-v2                       | 25 languages but slower and not more accurate than Parakeet v3 on German (FLEURS de 7.86)                                                                                                                                               | no                                               |
| Whisper via onnx-asr               | `onnx-community/whisper-large-v3-turbo` (int8/q4 ONNX) loads — DirectML-accelerated Whisper without new deps, greedy decode, unbenchmarked                                                                                              | experiment only                                  |
| Kyutai / Moonshine / GigaAM / Vosk | no German                                                                                                                                                                                                                               | reject                                           |

## C. OpenVINO GenAI

| Item           | Verified fact                                                                                                                                                                                                                                              | Action                              |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| Repo mapping   | all 33 repos `openvino_model_repo()` can produce return HTTP 200; the org has no distil-v3.5 / German / `.en`-distil IR → `OPENVINO_UNSUPPORTED_MODELS` still exact                                                                                        | none                                |
| openvino-genai | **2026.3.1.0** (2026-08-26). 2026.1: word timestamps, NPU Whisper stateful by default; `ASRPipeline` exported alongside `WhisperPipeline`, no deprecation                                                                                                  | keep `WhisperPipeline`              |
| NPU            | Whisper on NPU supported since 2024.5 (tiny/base/small/large); `--disable-stateful` export no longer needed since 2025.1; driver ≥ 32.0.100.3104 advised. **large-v3-turbo on NPU unverified** (issue #1965 closed, resolution unreadable)                 | test turbo+NPU before advertising   |
| Compile cache  | `WhisperPipeline(path, device, **props)` accepts OV properties; `CACHE_DIR` caches the compiled blob — [#1992](https://github.com/openvinotoolkit/openvino.genai/issues/1992): NPU re-init minutes → seconds. `GENERATE_HINT`/`PREFILL_HINT` are LLM-only. | **landed** (`_pipeline_properties`) |

## D. NVIDIA runtime

| Item                 | Verified fact                                                                                                                                                                                                                                     | Action                                            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| CTranslate2          | **4.8.2** (2026-08-31). Wheels since **4.6.3** are built with CUDA 12.8 and `WITH_CUDNN=OFF` (Conv1d in pure CUDA) — Windows GPU needs **cuBLAS 12 on PATH only**; cuDNN is optional. No CUDA 13 build (#1933 open).                              | README / Help: drop cuDNN as a requirement        |
| pip CUDA wheels      | `nvidia-cublas-cu12` / `nvidia-cudnn-cu12` ship win_amd64 wheels, but the `bin` dir must be on PATH; faster-whisper documents pip only for Linux                                                                                                  | keep README advice                                |
| onnxruntime-gpu      | **1.29.0**; **≥ 1.27 = CUDA 13 + cuDNN 9**, 1.21–1.26 = CUDA 12.8 + cuDNN 9. `onnxruntime.preload_dlls(cuda=, cudnn=)` (≥ 1.21) loads pip-installed DLLs torch-free. onnx-asr: CUDA 12 → `"onnxruntime-gpu[cuda,cudnn]<1.27"`, CUDA 13 → `>=1.27` | **landed** (`_preload_cuda_dlls`); document split |
| onnxruntime-directml | **1.24.4** (2026-03), py ≥ 3.11, no newer DML wheels; "sustained engineering… consider WinML"                                                                                                                                                     | keep path, frozen at ORT 1.24                     |
| CUDA-usable probe    | `ctranslate2.get_cuda_device_count()` counts devices via cudart only — does not prove cuBLAS loads; keep the error-marker fallback                                                                                                                | **landed**: count logged at load                  |

## E. Other engines

| Engine                          | Verdict                                                                                                                                                             |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| pywhispercpp 1.5.1              | PyPI wheels still CPU-only; GPU = source build → not viable                                                                                                         |
| transcribe.cpp (handy-computer) | MIT ggml runtime for 16 model families incl. Qwen3-ASR / Voxtral-Realtime, CUDA/Vulkan; no PyPI wheel → watch                                                       |
| Qwen3-ASR-1.7B                  | Apache; GGUF via `llama-server`; below realtime on CPU → reject as a bundled backend (an OpenAI-compatible _remote transcription_ backend would enable it dep-free) |
| Voxtral-Mini-4B-Realtime        | llama.cpp support still planned → reject                                                                                                                            |
