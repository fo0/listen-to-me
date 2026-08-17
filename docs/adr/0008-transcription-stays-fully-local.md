# ADR-0008: Transcription stays fully local

- **Status:** Accepted
- **Date:** 2026-08-17 (back-filled; true since the first version of the app)
- **Decider(s):** user
- **Tags:** privacy, transcription, dependencies, offline

## Context

Speech-to-text is available as a hosted API from every large vendor, usually more accurate than a model that fits on a laptop and with no model download to wait for. Building on one would have made this app a few hundred lines of HTTP client.

What the app is for rules that out. It is a **global** dictation tool: the hotkey fires from whatever window has focus, so the audio it captures is whatever the user happens to be saying at their desk — into a password field, a patient record, a customer's ticket, a private message. Sending that stream to a third party is a decision the user would have to make once and then live with for every recording, including the ones they did not mean to start.

Two further forces point the same way: a hosted API needs an account and a key before the app does anything at all, and it stops working on a plane, in a locked-down corporate network, or when the vendor has an outage.

## Decision

We will do **all** speech recognition on the user's machine. The shipped backends — faster-whisper (CTranslate2), OpenVINO GenAI and Parakeet via onnx-asr — run locally on the CPU, an NVIDIA GPU, or Intel graphics/NPU. No transcription request ever leaves the machine, and the app works with no account and no key.

The network is touched in exactly three places, all of them optional or one-time, and each named in the UI:

1. **Model download** — once per model, from Hugging Face; every later load is offline (`local_files_only`).
2. **The assistant post-processing** — off by default, opt-in, and pointed at a local Ollama by default.
3. **The updater** — checks GitHub Releases, and only when the user leaves that on.

A feature that would require sending audio or transcripts to a third party by default is not accepted into this app.

## Consequences

### Positive

- Dictation works with no account, no key, no subscription and no outage.
- After the first model download the app is fully offline — usable on a plane and in networks that allow nothing outbound.
- Nothing the user says is transmitted, so the app can be used in contexts where a cloud recorder could not be (regulated environments, customer data, credentials spoken aloud by mistake).
- The privacy claim is verifiable from the code rather than from a policy document.

### Negative / Trade-offs

- A one-time model download of 75 MB to 3 GB before the first recording — the cost this project pays most visibly, which is why the download has its own progress display (#110).
- Transcription costs the user's own CPU/GPU, and a large model on a CPU is slow; the app carries a whole backend abstraction plus per-vendor acceleration paths (CUDA, OpenVINO, ONNX Runtime) that a hosted API would not need.
- Accuracy tracks whatever open-weight model is current rather than a vendor's best hosted system.
- The optional assistant is the one path where transcript text can leave the machine. It stays off by default, and its key lives only in the user's local `config.json`.

### Neutral

- Model licences become the project's concern: only permissively licensed models are shipped as presets (a CC-BY-NC model can never become one — see the research notes).

## Alternatives Considered

- **A hosted STT API as the default backend** — rejected: it makes an irreversible privacy decision on the user's behalf for every future recording, and requires an account before the app does anything.
- **A hosted API as an optional fourth backend** — not rejected on principle, but it would have to be opt-in, named as such at the point of choice, and never the default. Nobody has asked for it.
- **Local by default with a cloud fallback on failure** — rejected outright: a silent fallback that uploads audio because the local model failed to load is the worst possible failure mode for this app.

## References

- Backend abstraction: `transcriber.create_transcriber` and `agent_docs/key-patterns.md`.
- The three network paths and the app-wide TLS switch: `netutil.py`, ADR-0006.
- Model licence constraints: `docs/research/2026-07-faster-stt-and-translation.md`.
