# Research: Faster/More Accurate STT Models & Near-Realtime Translation (July 2026)

Goal: the user dictates mostly **German**, wants **near-realtime latency with maximum accuracy**, and asked
for "near-realtime translation". Today the app transcribes only — there is **no translation feature**
(the default assistant prompt even forbids translating). So this research covers both readings:

1. faster **transcription** (better models on the existing backends, or new engines), and
2. actual **speech translation** (speak German → English text at the cursor, or vice versa).

All claims below were verified against the linked model cards / repos in July 2026 by three parallel
research agents. Licenses are flagged because the app ships in a released Windows exe.

---

## 1. Quick wins inside faster-whisper (no new engine)

### 1.1 German fine-tune of large-v3-turbo — best accuracy-per-cost move

[`primeline/whisper-large-v3-turbo-german`](https://huggingface.co/primeline/whisper-large-v3-turbo-german)
(Apache-2.0, 809 M params, ~115k downloads/month) is the **same turbo architecture** the app already
runs — identical speed — but fine-tuned on 980k German samples (paper: arXiv:2409.03137).

German WER (primeline benchmark mix: Tuda-De + CommonVoice 19 + MLS):

| Model | Tuda-De | CV 19 | MLS | All |
|---|---|---|---|---|
| openai/whisper-large-v3-turbo (current preset) | 8.30 | 3.85 | 3.20 | **3.65** |
| openai/whisper-large-v3 | 7.88 | 3.48 | 2.83 | 3.28 |
| **primeline/whisper-large-v3-turbo-german** | 6.44 | 3.20 | 2.07 | **2.63** |

≈ **28 % relative WER reduction vs the current turbo preset at the same speed** — even beats full
large-v3. Trade-off: German-only (loses multilingual + auto-detect usefulness).

Integration: faster-whisper accepts any CT2 repo id, so this is a **string-only preset addition** in
`choices.py`. No official primeline CT2 conversion exists; options:
- most-used community conversion: [`jimmymeister/whisper-large-v3-turbo-german-ct2`](https://huggingface.co/jimmymeister/whisper-large-v3-turbo-german-ct2) (Apache-2.0), or
- self-convert once via `ct2-transformers-converter --model primeline/whisper-large-v3-turbo-german`
  and publish/point to our own copy (safer supply chain).
- Avoid `TheChola/...-faster-whisper` (relabeled CC-BY-NC on an Apache model — dubious).

For Intel: no pre-converted OpenVINO IR exists; `optimum-cli export openvino` works (standard Whisper
arch), but that is a build/hosting task, not a string change.

### 1.2 distil-large-v3.5 — upgrade for the English presets

[`distil-whisper/distil-large-v3.5`](https://huggingface.co/distil-whisper/distil-large-v3.5) (MIT,
March 2025, **English-only**) has an **official CT2 repo**
[`distil-whisper/distil-large-v3.5-ct2`](https://huggingface.co/distil-whisper/distil-large-v3.5-ct2):
~1.5× faster than turbo, better short-form English WER than distil-large-v3 (7.08 vs 7.53).
Preset addition via full repo-id string (works on faster-whisper ≥ 1.1.0); the short alias
`distil-large-v3.5` needs faster-whisper ≥ 1.2.0.

### 1.3 faster-whisper version bump

Current requirement `>=1.1.0`; latest is **1.2.1** (Oct 2025): distil-v3.5 alias (1.2.0), Silero-VAD v6
(1.2.1). Low-risk bump, mild VAD quality/speed gains. No Whisper large-v4 exists (SEO-blog myth);
no new OpenAI open ASR release; no multilingual distil-whisper shipped yet.

### 1.4 OpenVINO backend facts (verified)

`OpenVINO/whisper-large-v3-turbo-{fp16,int8,int4}-ov` **exists** and our generic
`openvino_model_repo()` mapping already covers it — nothing to do.
`OpenVINO/distil-whisper-large-v3-*-ov` also exists. Still missing upstream: distil-v3.5 and all
`.en` distils (our `_UNAVAILABLE_PRESETS` stays correct).

### 1.5 Decode-side speed levers (model-independent)

`transcribe()` hardcodes `beam_size=5`. Greedy/`beam_size=1–2` is roughly 1.5–2× faster at a small
accuracy cost — worth a config key (`beam_size`) defaulting to current behavior.

---

## 2. Non-Whisper engines (bigger jump, new backend)

The app's `create_transcriber()` backend abstraction makes a third engine feasible. German-capable
finalists (Open ASR Leaderboard context: Whisper large-v3 ≈ RTFx 145):

| Model | German WER (FLEURS) | RTFx | Size | License | Windows path |
|---|---|---|---|---|---|
| [NVIDIA parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | 5.04 | **3,333** | 640 MB int8 ONNX | CC-BY-4.0 | [`onnx-asr`](https://github.com/istupakov/onnx-asr) pip pkg (numpy+onnxruntime only, no torch/NeMo); CUDA/DirectML |
| [Qwen/Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) (Jan 2026) | **3.92** — best open German number | GPU-fast | ~2–4 GB | Apache-2.0 | `qwen-asr` (torch) — sherpa-onnx port only for 0.6B so far ([1.7B requested](https://github.com/k2-fsa/sherpa-onnx/issues/3535)) |
| [Qwen/Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) | 6.48 | ~2000 (batch) | ~700 MB int8 | Apache-2.0 | sherpa-onnx int8 port available now |
| [nvidia/canary-1b-v2](https://huggingface.co/nvidia/canary-1b-v2) | ~4.4 (card) / 8.4 FLEURS-25 avg | 749 | 978 M | CC-BY-4.0 | `onnx-asr` supports Canary v2 |

**Parakeet-TDT-0.6B-v3 is the standout speed pick**: ~20× faster than turbo-class, German accuracy at
or above vanilla turbo, punctuation/caps/timestamps built in, and `onnx-asr` mirrors our existing
offline decode-per-take + snapshot live-preview model (chunked, not true streaming — fine for us).
onnxruntime is already in the PyInstaller `--collect-all` list.

Disqualified for German (hard): Kyutai STT (en/fr only), Moonshine (en + 7 non-German flavors),
canary-qwen-2.5b (en), Parakeet v2 / realtime-eou / unified / nemotron-streaming (en), FireRedASR
(zh/en), Samba-ASR (no public weights). Too heavy per point of German accuracy: Voxtral Mini 3B
(llama.cpp, ~9.5 GB bf16), Voxtral Mini 4B Realtime (true streaming, 480 ms, German 6.19 — but
needs ≥16 GB GPU + vLLM, no native Windows), IBM Granite Speech 4.1 2B, Cohere Transcribe,
Phi-4-multimodal, Meta Omnilingual ASR (fairseq2 on Windows).

---

## 3. Translation ("speak German → English text")

### 3.1 Whisper's built-in `task="translate"` — cheapest entry, with a trap

Any-language → **English only**. Supported by faster-whisper (`task="translate"`) and OpenVINO
GenAI (`WhisperGenerationConfig`). **Trap:** `large-v3-turbo` was *not trained* for translation —
it silently returns source-language text ([openai/whisper #2363](https://github.com/openai/whisper/discussions/2363),
[faster-whisper #1237](https://github.com/SYSTRAN/faster-whisper/issues/1237)); distil models are
English-only anyway. A translate toggle must gate out turbo/distil presets (and the German fine-tune,
same turbo lineage) in the UI. Quality on large-v3 is decent gist-level; decode is ~2–4× slower than turbo.

### 3.2 Cascade: Whisper ASR + local MT on CTranslate2 — best architecture fit

CTranslate2 (already shipped!) natively runs MarianMT/Opus-MT, NLLB, M2M-100, T5/MADLAD, and newer
Gemma/Qwen decoders. Only new dep: `sentencepiece` (small). Added latency per 1–2-sentence chunk:

| MT model | DE↔EN quality | CPU added | Size | License |
|---|---|---|---|---|
| [Helsinki-NLP/opus-mt-de-en](https://huggingface.co/Helsinki-NLP/opus-mt-de-en) / en-de | good | **<0.15 s** (CT2 int8) | ~100 MB ×2 | Apache-2.0 ✅ |
| [google/madlad400-3b-mt](https://huggingface.co/google/madlad400-3b-mt) | very good, any↔any 400 langs | 1–3 s | 1.65 GB int8 | Apache-2.0 ✅ |
| [utter-project/EuroLLM-1.7B-Instruct](https://huggingface.co/utter-project/EuroLLM-1.7B-Instruct) | very good (COMET 86.9 FLORES avg) | 1–4 s | ~1–2 GB | Apache-2.0 ✅ |
| [google/translategemma-4b-it](https://huggingface.co/google/translategemma-4b-it) (Jan 2026) | excellent (COMET 81.6 WMT24++) | 5–20 s ⚠️ (GPU: <1.5 s) | ~2.5 GB Q4 | Gemma ToU (commercial OK, gated) |
| NLLB-200-distilled (any size) | good+ | 0.5–1.5 s | 0.6+ GB | **CC-BY-NC 🚫 do not ship** |

**Opus-MT de-en/en-de is the sweet spot**: sub-150 ms on CPU — effectively free next to the Whisper
decode, both directions, permissive. MADLAD/EuroLLM as an optional "high quality" tier.

### 3.3 Direct speech translation: Canary-1b-v2

[nvidia/canary-1b-v2](https://huggingface.co/nvidia/canary-1b-v2) (CC-BY-4.0) does ASR **and**
speech translation En↔24 languages in one model: De→En BLEU 36.0 / COMET 83.1, En→De BLEU 33.7 —
better than Whisper large-v3's built-in translation, and it covers En→De, which Whisper cannot.
Runs without NeMo via `onnx-asr` ([istupakov/canary-1b-v2-onnx](https://huggingface.co/istupakov/canary-1b-v2-onnx),
`recognize(wav, language="de", target_language="en")`). Would double as a third ASR backend.

### 3.4 LLM translation over the existing assistant hook

`assistant.py` already speaks OpenAI-compatible HTTP → a "translate" mode is mostly prompt + target
language setting. With a local server (Ollama/LM Studio) and **TranslateGemma-4B GGUF** (or Qwen3-4B,
Gemma-3-4B): <1 s/sentence on 8 GB+ GPUs, 3–20 s CPU-only. Handles register instructions ("Sie-Form",
"keep technical terms") that no classic MT model can. Avoid recommending Unbabel Tower+ (CC-BY-NC).

### 3.5 Streaming / simultaneous translation

Production research exists — [SimulStreaming](https://github.com/ufal/SimulStreaming) (MIT, IWSLT 2025
winner), [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) (Apache-2.0 code, but its NLLW
translation weights are NLLB-derived → CC-BY-NC) — but these are server/WebSocket architectures
(High effort). The pragmatic path: our existing `livetype.py` LocalAgreement loop, fed with translated
output (translate-task preview or per-confirmed-segment Opus-MT) gives ~1–3 s-lag simultaneous
translation at Low–Med effort.

**Skip entirely:** SeamlessM4T v2 / SeamlessStreaming (CC-BY-NC + dormant since Nov 2024), NLLB/NLLW
weights (CC-BY-NC), Tower+ (CC-BY-NC), CrisperWhisper as a dictation preset (CC-BY-NC + verbatim
`[UH]`/`[UM]` fillers — wrong for voice typing despite best-in-class German WER on 2 of 3 benchmarks).

---

## 4. Recommended roadmap (ranked by value/effort)

| # | Action | Effort | Win |
|---|---|---|---|
| 1 | Preset `large-v3-turbo-german` (primeline CT2) in `choices.py` | string-only | −28 % German WER at same speed |
| 2 | Preset `distil-large-v3.5` (official CT2 repo id) for English mode; bump faster-whisper to ≥1.2.1 | string + req bump | 1.5× faster than turbo for EN |
| 3 | `beam_size` config key (default 5) | tiny | up to ~2× decode speed opt-in |
| 4 | Translate toggle: Whisper `task="translate"` (→EN only), UI-gated against turbo/distil/german presets | small | first real translation feature |
| 5 | Cascade MT: Opus-MT de↔en on CT2 int8 (+`sentencepiece`), wired after transcribe + optional per-segment in live preview | medium | both directions, <150 ms added, fully local |
| 6 | New backend: Parakeet-TDT-0.6B-v3 via `onnx-asr` | medium | ~20× faster processing phase, German ≥ turbo accuracy |
| 7 | Optional: Canary-1b-v2 backend (ASR+AST) / assistant translate mode / MADLAD high-quality tier | medium | premium translation quality |
| — | Watch: Qwen3-ASR-1.7B sherpa-onnx port (best open German WER 3.92), multilingual distil-whisper, Voxtral Realtime on llama.cpp | — | future backends |

License red flags to keep in mind when shipping: CC-BY-NC (CrisperWhisper, NLLB/NLLW, SeamlessM4T,
Tower+) is incompatible with a released exe for commercial users; CC-BY-4.0 (NVIDIA models) needs
attribution in the About/README.
