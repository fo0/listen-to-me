# Architecture Principles

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps the two rules that are easiest to violate accidentally; this file is the full set.

- **`App.state` is the single source of truth.** Transitions go through `_set_state`, which drives tray icon, overlay and mute integrations together. Never flip one of those three on its own — they are meant to be observably in sync.
- **Cross-thread communication is one-way through the event queue.** Worker threads (hotkey listener, process / live-preview / update workers) never mutate Qt objects; they call `App.post(kind, payload)` or `App.notify(...)`, and the main-thread `QTimer` drains the queue. Direct Qt access from a worker crashes the process.
- **Everything degrades gracefully.** No microphone, no GPU, no network, no clipboard access must each fail soft with a user-visible notification — never a crash, never a silent no-op. The CUDA→CPU fallback, the paste→type fallback and the tray-icon retry are the reference implementations.
- **Config changes apply without a restart** where feasible. `App.apply_settings` re-wires live components, the transcriber re-keys itself on the config (and is re-created on a backend switch), and integrations read their mute targets fresh at the start of every recording.
- **No telemetry, no cloud dependency for core function.** Transcription is fully local. Only two paths reach the network: the optional assistant post-processing and the updater. Neither may become required for dictation to work.
- **Security boundaries stay explicit.** The updater forces TLS verification regardless of the `insecure_ssl` switch (ADR-0002), and merging or releasing needs an explicit interactive user command that no prompt can grant itself (ADR-0004). Both are deliberately narrower than the surrounding convenience feature.
- **Untrusted input is anything on disk that the user or an older build wrote** — `config.json`, `history.json`, an OS autostart entry. Validate at read time; a malformed value must never be able to stop the app from starting.
