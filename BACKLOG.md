# Backlog

Review findings not immediately fixed. **Only work on these upon explicit request.** Process: `agent_docs/backlog_process.md`.

## Open

| # | Date | Category | Sev | Location | Finding | Status | Source |
|---|------|----------|-----|----------|---------|--------|--------|
| 1 | 2026-07-19 | Code Smells | P2 | settings_ui.py → SettingsWindow | ~1750-line file (grew with the diagnostics buttons 2026-07-20), well over the ~500-line guideline; candidate to split into per-page modules (General/Whisper/Audio/Overlay/Integrations/Assistant/History/Help) | Deferred | Optimizer setup |
| 2 | 2026-07-20 | Edge Cases | P2 | transcriber_openvino.py → openvino_model_repo | A custom CTranslate2 HF model id typed while the OpenVINO backend is selected passes through verbatim, downloads the wrong-format model and fails only at pipeline load with a cryptic error. Documented in tooltips/hint; a format pre-check (probe for `openvino_model.xml` in the repo) would fail earlier and clearer | Accepted | OpenVINO backend #18 / PR #20 |
| 3 | 2026-07-20 | Security | P1 | updater.py → download_asset / netutil.py | With `insecure_ssl` on, the updater's exe download is unauthenticated (HTTPS host pinning doesn't help without cert verification) — a MITM proxy could serve a malicious binary that the app then swaps in. Hardening: verify the release asset's SHA256 `digest` from the GitHub Releases API after download, and/or keep `verify=True` specifically for the exe download even when `insecure_ssl` is on | Deferred (documented opt-in trade-off — owner decision) | Security audit 2026-07-20 |
| 4 | 2026-07-20 | Security | P1 | CLAUDE.md → Deployment "Routine exception" | Authorization is self-declared: any session whose kickoff prompt *claims* to be an owner-authorized routine gets pre-approved merge+deploy. A prompt-injection or malicious trigger text can claim this — there is no verifiable signal. Hardening: tie the exception to something checkable (e.g. a specific trigger id list) instead of self-declaration | Deferred (owner policy — needs owner review) | Security audit 2026-07-20 |
| 5 | 2026-07-20 | Security | P2 | .github/workflows/*.yml | Third-party actions pinned by major tag (`actions/checkout@v4`, `softprops/action-gh-release@v2`), not by commit SHA — a compromised tag would run in the release pipeline with `contents: write`. Hardening: pin by full SHA | Deferred | Security audit 2026-07-20 |
| 6 | 2026-07-20 | Edge Cases | P2 | settings_ui.py → _test_microphone/_test_transcription | The global hotkey stays active during a mic/transcription test — pressing it mid-test opens a second PortAudio input stream on the same device (both keep working in shared mode, but statuses interleave). The reverse is guarded (tests refuse to start while recording). Polish: pause the hotkey listener for the test duration, mirroring the hotkey test | Deferred | Settings self-test buttons (claude/settings-test-buttons) |

## Done

| # | Date | Done | Category | Location | Finding |
|---|------|------|----------|----------|---------|
