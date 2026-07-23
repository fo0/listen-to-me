# CLAUDE.md — Project Guide

## Session Start — Read Order

When a session begins, read in this order. Stop early if a file is missing.

1. `MEMORY.md` — long-term project knowledge
2. `SCRATCHPAD.md` — short-term working context
3. `BACKLOG.md` — only if user references prior findings or asks "what's open"
4. `agent_docs/review_process.md`, `agent_docs/memory_process.md` — only when needed
5. `agent_docs/mcp_catalog.md` — only when MCPs come up
6. `.claude/skills/*/SKILL.md` — only when its trigger fires

> Don't pre-load everything. The Tier-1 SessionStart hook already prints a reminder.

## Workflow Triggers

| User says...                                           | Skill to load                                     |
|--------------------------------------------------------|---------------------------------------------------|
| "done" / "fertig" / "finished" / "/done"               | `.claude/skills/done/SKILL.md`                    |
| "PR" / "create PR" / "/pr"                             | `.claude/skills/pr/SKILL.md`                      |
| "review" / "/review"                                   | `.claude/skills/review/SKILL.md`                  |
| "security review" / "/security-review"                 | `.claude/skills/security-review/SKILL.md`         |
| "rollback" / "revert" / "undo" / "/rollback"           | `.claude/skills/rollback/SKILL.md`                |
| "CI" / "fix CI" / "check the build" / "/ci"            | `.claude/skills/ci/SKILL.md`                      |
| "stuck" / "loop" / "going in circles" / "/stuck"       | `.claude/skills/stuck/SKILL.md`                   |
| Diagram request                                        | `agent_docs/diagram_prompt.md` → `docs/ARCHITECTURE.mmd` |

> After every implementation, the review process in `agent_docs/review_process.md` is available via the `review` skill — done-skill does NOT auto-run reviews.
> Unresolved findings go to `BACKLOG.md` per `agent_docs/backlog_process.md`.
> Long-term knowledge → `MEMORY.md`. Temporary working context → `SCRATCHPAD.md`. Rules: `agent_docs/memory_process.md`.
> Reference GitHub issues in commit messages: `Fix crash on empty audio #42`.

## Output Languages

| Surface                                | Language                          |
|----------------------------------------|-----------------------------------|
| Chat / status messages to user         | User's language (default: German) |
| Code, identifiers, comments            | English                           |
| Commit messages                        | English, imperative mood (see Git Conventions — not strict Conventional Commits) |
| PR titles + bodies                     | English                           |
| GitHub issue comments                  | English                           |
| Generated files (CLAUDE.md, agent_docs/*, MEMORY.md, SCRATCHPAD.md, BACKLOG.md, skills) | English |
| App log output                         | English                           |
| User-facing UI strings                 | English (no i18n framework — strings are inline) |

## Performance / Modes

- **Default model:** the latest available Opus model (1M context) — Claude Code's default tier for coding work. Don't pin an older version unless the project explicitly requires it.
- **Fast mode** (`/fast` in Claude Code): the **same** Opus model with faster output — not a downgrade to a smaller model. Use when latency matters more than maximum reasoning depth.
- **Caveman mode** (chat compression): toggle per session — `caveman lite|full|ultra` to switch, `stop caveman` / `normal mode` to disable. Affects chat only, never generated files.
- **Plan mode**: enter for non-trivial implementation strategy. Use the `Plan` subagent (`subagent_type: "Plan"`) for delegating, or invoke `EnterPlanMode` directly to plan in main thread before acting. Don't use plan mode for trivial single-step tasks.

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | >=3.10 (CI + dev on 3.11/3.12) |
| GUI Framework | PySide6 (Qt 6) | >=6.6 |
| Speech-to-text | faster-whisper (CTranslate2) | >=1.2.1 |
| Speech-to-text on Intel GPU/NPU (optional) | openvino-genai (`[openvino]` extra; bundled in the Windows exe) | >=2025.2 |
| Speech-to-text via NVIDIA Parakeet (optional) | onnx-asr (`[parakeet]` extra; bundled in the Windows exe) | >=0.12 |
| Audio capture | sounddevice (PortAudio) | >=0.4.6 |
| Global hotkeys / input | pynput | >=1.7.7 |
| Numerics | numpy | >=1.24,<3 |
| Icon rendering | Pillow | >=10.0 |
| Clipboard | pyperclip | >=1.8.2 |
| HTTP (updater/assistant) | requests | >=2.31 |
| Build backend | setuptools | >=68 (`pyproject.toml`) |
| Packaging (Windows) | PyInstaller | one-file, via CI |
| Package Manager | pip | `requirements.txt` + `pyproject.toml` |
| Test Framework | none configured | CI: `compileall` + Qt offscreen smoke test (`selftest.gui_smoke`) |
| Linter/Formatter | none configured | code is de-facto black-style, line length ~100 |

## Project Overview

**Listen To Me** is a push-to-talk voice-typing desktop app: press a global hotkey, speak, and the recording is transcribed **locally** by a Whisper model (faster-whisper) and inserted at the cursor of whatever field is focused. It runs as a system-tray app with an optional floating always-on-top status icon; optional LLM post-processing (any OpenAI-compatible API) and mute-other-apps-while-recording integrations are built in. Windows-first, with Linux/macOS paths prepared.

## Project Structure

```
src/listen_to_me/     # The single application package (see Key Patterns for module roles)
scripts/              # Dev/build helpers (make_icon.py — generates the .ico for PyInstaller)
.github/workflows/    # ci.yml (syntax check + Qt smoke on PRs); release.yml (manual Windows build/release, main only)
docs/                 # ARCHITECTURE.mmd (+ .svg), adr/ (Architecture Decision Records)
agent_docs/           # Agent process docs (review, backlog, memory, api-reference, hooks, MCP, ADR)
.claude/skills/       # Skill workflows (done, pr, review, security-review, rollback, ci, stuck)
```

The app is a **flat single package** — there are no sub-packages under `src/listen_to_me/`. Modules are found via glob/grep; roles are summarized in Key Patterns.

## Commands

```bash
# Install (dev, editable, from a virtualenv)
pip install -e .            # or: pip install -r requirements.txt

# Run from source (no install needed)
PYTHONPATH=src python -m listen_to_me
# Installed entry points: `listen-to-me` / `listen-to-me-gui`
python -m listen_to_me --version     # print version, no Qt import
python -m listen_to_me --selftest    # packaging self-test (needs all deps installed)

# Automated Checks (no linter/formatter/typecheck configured — these are the CI checks)
python -m compileall -q src scripts   # syntax check every source file (fast, no deps)
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"   # headless Qt UI smoke test

# Build (Windows one-file executable — normally run in CI, not locally)
pyinstaller --noconfirm --clean --onefile --windowed --name ListenToMe \
  --collect-all faster_whisper --collect-all ctranslate2 \
  --collect-all onnxruntime --collect-all av src/listen_to_me/__main__.py

# Architecture diagram (validate/render)
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg
```

> **No lint/format/typecheck step exists.** Do not invent one or add tooling without user approval. Match the surrounding style by hand (see Coding Conventions). If asked to add ruff/black/mypy, that is a dependency + config change requiring user sign-off.

## Key Patterns

Module roles (all in `src/listen_to_me/`):

### App core & state machine
`app.py` — `App` owns the state machine (`idle` → `recording` → `processing`), a thread-safe event `queue`, and wires every component. A `QTimer` drains the queue on the Qt main thread.

### Threading model (critical)
Main thread = Qt event loop + the 100 ms poll `QTimer`; **all** GUI/tray/overlay work happens here. Background threads (pynput hotkey listener, the `process`/`live-preview`/`update` workers) never touch Qt directly — they call `App.post(kind, payload)` (or `App.notify(...)`, which posts a `"notify"` event). Violating this from a worker thread crashes Qt.

### Lazy heavy imports
Qt, `sounddevice`, `pynput`, `faster_whisper`, `numpy` are imported **inside** functions/methods, not at module top, so `--version`/`--selftest` stay fast and headless. Preserve this — do not hoist heavy imports to module scope.

### Config
`config.py` — `Config` loads/merges a JSON file under the platform config dir over a `DEFAULTS` dict (deep-merge, so new keys appear on upgrade). `atomic_write_json` writes via temp-file + `os.replace`. Access with `cfg["key"]`. `Config.first_run` is `True` only when no config file existed before load — it drives the one-time onboarding wizard.

### Qt-free modules (headless-testable)
`icons.py` (Pillow), `keymap.py` (QtCore only), `help_content.py`, `diagnostics.py`, `choices.py`, and the low-level parts of `qtutil.py`/`selftest.py` avoid `QtWidgets`/`QtGui` so they import and test on a headless machine. Keep new pure logic Qt-free when practical.

### Transcription + CUDA→CPU fallback
`transcriber.py` — wraps faster-whisper; on a missing/unloadable CUDA library it forces CPU **for the session** (not for transient OOM) and retries. `_lock` guards model load, `_use_lock` serializes decodes. `audio.py` `Recorder` captures via sounddevice; `snapshot()` feeds the live preview cheaply.

### Backend abstraction (Intel via OpenVINO, NVIDIA Parakeet via onnx-asr)
`create_transcriber(cfg)` in `transcriber.py` picks the backend from `cfg["backend"]`: the default `Transcriber` (faster-whisper), `transcriber_openvino.py` `OpenVinoTranscriber` (OpenVINO GenAI `WhisperPipeline`, Intel CPU/GPU/NPU, config keys `openvino_device`/`openvino_precision`) or `transcriber_parakeet.py` `ParakeetTranscriber` (NVIDIA Parakeet TDT 0.6b v3 via onnx-asr/ONNX Runtime — not a Whisper model: one fixed model, 25 languages auto-detected, so model preset/language/initial prompt/VAD/beam size don't apply; config key `parakeet_quantization`, device shared with faster-whisper's `device`). All expose the same surface (`ensure_loaded`/`transcribe`/`preview`/`loaded`/`backend`); `App.apply_settings` re-creates the instance on a backend switch, and live typing gates itself via `hasattr(transcriber, "preview_segments")` (faster-whisper only). The OpenVINO backend downloads pre-converted `OpenVINO/whisper-*-ov` models from Hugging Face (`openvino_model_repo()` maps preset+precision; `distil-*.en`/`distil-large-v3.5` and the German CT2 preset have no conversion → ValueError); the Parakeet backend downloads `istupakov/parakeet-tdt-0.6b-v3-onnx` and keeps ONNX Runtime's CPU provider as last resort instead of an error-string CPU fallback. `openvino`/`openvino_genai`/`onnx_asr` are optional deps — imported lazily, never at module top; the app must run without them. faster-whisper's decode reads `cfg["beam_size"]` (default 5, clamped ≥1; previews stay greedy).

### Component modules (one responsibility each)
`singleinstance.py` (Qt-free single-instance guard: named kernel mutex on Windows / `flock` file in the config dir on POSIX — a TCP-port lock was unreliable on Windows port-exclusion ranges; port 52697 remains only as the activation channel through which a second launch pings the running instance, which then notifies, re-asserts the overlay and opens Settings), `hotkeys.py` (global hotkey, toggle/hold), `injector.py` (paste/type at cursor + `sanitize_typed_text`/`type_plain` — modifier-guarded plain-text typing), `livetype.py` (experimental live typing: a per-take worker types transcript segments at the cursor *while* recording once two consecutive preview passes agree on them — append-only, sanitized plain text only, pauses while Ctrl/Alt/Shift/Win is held; config key `live_typing`, faster-whisper backend only, gated in hold mode via `Hotkeys.combo_flags`), `integrations.py` (mute Discord/Teams/… while recording), `assistant.py` (optional OpenAI-compatible post-processing), `history.py` (transcript JSON), `autostart.py` (start-with-OS), `updater.py` (GitHub Releases), `netutil.py` (app-wide `insecure_ssl` switch — disables TLS verification for corporate proxies: requests `verify=` + the huggingface_hub client factory, httpx-based `set_client_factory` on hub >= 1.0 / `configure_http_backend` on < 1.0), `tray.py` (`QSystemTrayIcon`), `overlay.py` + `voice_mic_widget.py` (floating animated icon; a 30 s watchdog re-asserts visibility/topmost and hard-reshows after suspend or monitor changes — Windows drops layered always-on-top windows while Qt still reports them visible), `settings_ui.py` (settings window — **largest file, ~2100 lines**), `onboarding.py` (first-run setup wizard — hotkey/language/model/backend + device/microphone/startup; shown once when `Config.first_run`, i.e. no config file existed), `choices.py` (Qt-free shared dropdown lists + label↔value mapping used by settings_ui and onboarding), `theme.py` (Qt Fusion light/dark), `widgets.py` (hotkey capture dialog), `diagnostics.py` (Qt-free engine behind the Settings self-test buttons — model download/load, mic level check, end-to-end transcription test, plus the hardware/status probes `probe_cuda`/`probe_openvino`/`model_cache_status` feeding the Whisper-page status card; runs on worker threads, results marshaled to the UI via `_DiagSignals` carrying a generation int so a diagnostic cancelled via the Cancel buttons can't emit stale results into the UI), `qtutil.py` (Qt helpers: Pillow→QPixmap bridge, `tray_icon`, `guard_wheel` — combo/spin boxes ignore mouse-wheel events until explicitly focused so page scrolling can't change values; apply it to every new value widget on a scrollable page — and `elastic_combo` — caps a combo's minimum width so one long item (model id, audio device name) can't force a settings page wider than its scroll viewport, which clips every card at the right edge; apply it to every combo whose item texts are unbounded).

### Error Handling
Desktop app that must never crash: broad `except Exception` at boundaries, logged via module-level `log = logging.getLogger(__name__)` with `log.exception(...)`; user-facing failures surface through `App.notify(...)`. Logs go to a rotating file in the config dir + stderr (absent in `--windowed` builds). Best-effort cleanup (`_quit`, `integrations.reset()`) must never leave a target app stuck muted.

## Coding Conventions

- **`from __future__ import annotations`** at the top of every module.
- **Comments/docstrings in English**; docstrings explain *why*, not just *what* (this codebase leans heavily on them).
- **Naming:** modules/functions `snake_case`, classes `PascalCase`, "private" helpers prefixed `_`.
- **Imports:** stdlib → third-party → local (`from .x import y`); heavy/optional deps imported lazily inside functions (see Key Patterns).
- **Formatting:** double quotes, 4-space indent, trailing commas in multi-line literals, line length ~100. No formatter enforces this — match by hand.
- **Type hints** on public function signatures; `X | None` unions (3.10+).
- **Logging, not print** (except CLI output in `main()`); one logger per module.
- **UI strings** are inline English literals — there is no i18n framework.
- **Max file length:** ~300 lines (split), ~500 lines (strongly recommended). `settings_ui.py` already exceeds this — see Refactoring Notes.

## Architecture Principles

- **Single source of truth for state is `App.state`**; transitions go through `_set_state`, which drives tray + overlay + mute integrations together.
- **Cross-thread communication is one-way through the event queue.** Never mutate Qt objects off the main thread.
- **Everything degrades gracefully** — no microphone, no GPU, no network, no clipboard access must each fail soft with a notification, never a crash.
- **Config changes take effect without a restart** where feasible (`apply_settings`, transcriber re-keys on the config, integrations read targets fresh per recording).
- **No telemetry, no cloud dependency for core function** — transcription is fully local; only the optional assistant + updater reach the network.

## Architecture Decisions

Significant decisions are recorded as ADRs under `docs/adr/`. Triggers + format: `agent_docs/adr_template.md`. Always grep `docs/adr/` before contradicting an existing decision. To reverse a past decision, add a new ADR with `Status: Supersedes ADR-NNNN` — never edit accepted ADRs.

## Git Conventions

- **Branch Naming:** `claude/<short-slug>` (e.g. `claude/discord-voice-dictation-fmue98`); feature branches, never commit straight to `main`.
- **Commit Messages:** imperative, capitalized subject (~50–72 chars), e.g. `Add in-app Help page and auto CPU fallback`. An optional lowercase `area:` prefix is used occasionally (`ci: run the check job`). **Not** strict Conventional Commits — do not force `feat:`/`fix:` prefixes. Reference issues/PRs with `#N`. A short body explaining *why* is welcome for non-trivial changes.
- **Merge Strategy:** GitHub **merge commits** (`Merge pull request #N from …`), not squash.
- **CI/CD:** `.github/workflows/ci.yml` — the fast `check` job (compileall + offscreen Qt smoke) runs on every PR. `.github/workflows/release.yml` — Windows PyInstaller build + GitHub Release, manual `workflow_dispatch` only, and a guard job fails any dispatch from a ref other than `main`.

## Dependency Management

- **New runtime dependencies:** only after user approval with reasoning — they bloat the one-file Windows build and its `--collect-all` list.
- **Keep `requirements.txt` and `pyproject.toml` `dependencies` in sync** — both list the runtime deps; update both when a dep changes.
- **PyInstaller hidden imports:** a new dep with C extensions or data files may need a `--collect-all` in `release.yml` — verify the `--selftest` still passes on the built exe.
- No lock file; deps are pinned with lower bounds (`>=`).

## Environment Variables

The app reads no custom env vars for its own config (settings live in `config.json`). Relevant ones are third-party / platform:

| Variable | Description | Default |
|----------|-------------|---------|
| `HF_HOME` / `HF_HUB_CACHE` / `HUGGINGFACE_HUB_CACHE` | Where faster-whisper caches downloaded Whisper models | `~/.cache/huggingface/hub` |
| `QT_QPA_PLATFORM` | Set to `offscreen` for headless Qt (CI smoke test) | (unset) |
| `APPDATA` / `XDG_CONFIG_HOME` | Base for the app config dir (`ListenToMe` / `listen-to-me`) | OS default |

There is no `.env` file. Config path: `config.py → config_dir()`.

### Secrets Locations

| Secret class       | Where it lives                                        | Never commit |
|--------------------|-------------------------------------------------------|--------------|
| Assistant API key  | user's `config.json` → `assistant.api_key` (local, gitignored config dir) | ✅ Never |
| CI/CD secrets      | GitHub Actions `GITHUB_TOKEN` (auto-provided; release upload) | ✅ Never |
| Test fixtures      | Synthetic values only — never real credentials         | ✅ Never     |

Rules: the app stores no secrets in-repo; the only user secret (optional assistant API key) lives in their local config file. Never log it, never commit a real one. The `security-review` skill scans for committed secrets.

## Deployment

- **Trigger:** manual `workflow_dispatch` on `release.yml` builds the Windows exe and publishes a GitHub Release (tag `vYYYY.MM.DD.<run>`). Dispatching from any ref other than `main` fails in the guard job. PRs only run the `ci.yml` check job — never a build or release.
- **Pipeline:** `.github/workflows/release.yml` (reuses the `ci.yml` check via `workflow_call`).
- **Distribution:** portable single-file `ListenToMe-<date>-<hhmm>-win64.exe` (UTC timestamp) attached to the Release; in-app updater (`updater.py`) offers newer releases.
- **Agent scope:** Agent can push to feature branches, open/update PRs, suggest merge. **Agent does NOT dispatch the release build** without explicit user command.
- **Routine exception:** a session running an **owner-authorized routine** (its kickoff prompt declares itself an authorized Claude Code routine of the repo owner) counts as an explicit user command. Merges ordered by such a routine are pre-approved — including any deploy/publish the merge triggers — provided the change set is non-destructive (additive; no data migration, no history rewrite, no repo-settings change) and the routine's verification passed. Destructive changes stay gated.
- **Rollback:** see `.claude/skills/rollback/SKILL.md`. For a bad release, prefer a revert-PR + a fresh dispatched build over hand-editing a published asset.

## API / Interfaces

This is a desktop GUI app — it exposes no served HTTP API. It has a small **CLI** (`--version`, `--selftest`) and **consumes** two external HTTP interfaces (OpenAI-compatible chat/completions for the optional assistant; the GitHub Releases API for the updater).

Details: `agent_docs/api-reference.md`.

## Testing

- **Framework:** none (no pytest). Verification is the CI `check` job.
- **Run:** `python -m compileall -q src scripts` (syntax) and the headless Qt smoke (`selftest.gui_smoke`, see Commands). Full packaging self-test: `python -m listen_to_me --selftest` (needs all deps).
- **Structure:** `selftest.py` holds the checks; `gui_smoke()` is the dependency-light subset CI runs from source.
- **Patterns:** keep new pure logic Qt-free so it's exercisable by `gui_smoke`/headless. Prefer extending `selftest.py` over adding a heavy test framework unless the user asks.

### Constraints (autonomy + zero-cost)

This codebase is built and verified by AI agents. Any tests added must be:

- **Agent-runnable** with the standard checks above — no manual setup, no credentials, no interactive login, no real microphone/GPU.
- **Zero-cost** — no real API calls (paid LLMs, GitHub), no model downloads in the default check path, no audio hardware.
- **Deterministic** — fake clocks/random, mock `sounddevice`/`pynput`/`requests`/`faster_whisper` at the boundary.

Real-service smoke/E2E tests only on explicit user request — never part of the default check pipeline.

## External Integrations / MCPs

Project-intended and common MCPs are documented in `agent_docs/mcp_catalog.md`. The optimizer never auto-detects host MCP availability — fall back to standard tools (`Read`, `Bash`, `WebFetch`) when an MCP is not on the local host. Workflows must never hard-require an MCP.

Claude Code Remote trigger self-management (`send_later`, `create/update/delete/fire/list_triggers`, PR-activity subscribe/unsubscribe — the PR-activity pair also in its GitHub-server spelling `mcp__github__…`) is pre-approved in `.claude/settings.json` → `permissions.allow`, so scheduled check-ins and Routine cleanup run without manual permission prompts in web/remote sessions. Scope-widening tools (`add_repo`, `register_repo_root`) still prompt by design. **Allowlist self-heal:** if one of these trigger tools nevertheless raises a manual approval prompt (server-name spelling missing from the allowlist, or settings predate it), append the exact `mcp__<server>__<tool>` string that prompted — plus the sibling trigger tools in that same spelling — to `permissions.allow` and commit the change on the current branch/PR. Additive only: never remove or reorder existing entries, never write `deny`/`ask`, and never allowlist `add_repo`/`register_repo_root`.

## CI

CI failure handling is in `.claude/skills/ci/SKILL.md`. Triggered by `/ci`, "fix CI", "check the build". Auto-routes by run state (none / running / passed / failed / stale). Never auto-reruns; always verifies fixes locally before pushing.

## Subagents

For complex / parallel / read-heavy work, delegate to a Claude Code subagent rather than running everything in main context.

| `subagent_type`     | Use for                                              |
|---------------------|------------------------------------------------------|
| `Explore`           | Read-only search, locate symbols / files             |
| `Plan`              | Design implementation strategy for non-trivial tasks |
| `general-purpose`   | Multi-step write+execute, write tests/docs, refactor |
| `claude-code-guide` | Questions about Claude Code itself (hooks, MCP, SDK) |

Rules:
- Direct tools beat subagents when the target is known (`Read` for known path, `grep` for known symbol).
- Parallelize independent subagent calls in a single message.
- Pass full context — subagents have no conversation history.

Full guide: `agent_docs/review_process.md → Subagent Delegation`.

## Development Notes

- **Windows-first**; `injector.py`, `autostart.py`, `config.py`, `_beep` branch per `sys.platform`. Test that platform branches stay coherent when touching them.
- **Single instance** is guarded by `singleinstance.py` (named mutex on Windows, `flock` file on POSIX — not a port bind; see MEMORY.md). A second launch pings the running instance over localhost:52697 so it shows itself, then exits.
- **Version** is stamped into `__init__.py` by CI at build time (`0.0.0.dev0` in source).
- Stable knowledge → `MEMORY.md`; transient context → `SCRATCHPAD.md`.

## Refactoring Notes

- `settings_ui.py` (~2100 lines) far exceeds the size guideline — a candidate to split into per-page modules (General/Whisper/Audio/Overlay/Integrations/Assistant/History/Help) if it hinders a change. Refactor only when it blocks work (see `agent_docs/refactoring_guidelines.md`).
- `app.py` (~500 lines) is at the threshold; keep new behavior in the component modules, not in `App`.

Details: `agent_docs/refactoring_guidelines.md`.

## Documentation Rules

After every code change, check and update:

| File | Update when... |
|------|---------------|
| `CLAUDE.md` | New modules, config keys, patterns, technical details |
| `README.md` | New features, settings, platform notes for users |
| `BACKLOG.md` | Unfixed review findings (Accepted/Deferred) |
| `MEMORY.md` | Architecture decisions, gotchas, external-dep quirks, user preferences |
| `SCRATCHPAD.md` | Current working context, open questions, short-lived notes |
| `docs/ARCHITECTURE.mmd` | Structural changes (new module, changed data flow, new external dep) |
| `config.py DEFAULTS` | New configuration options (and reflect in Settings UI + README table) |

### Size monitoring
If `CLAUDE.md` exceeds ~40,000 characters: extract the largest section into `agent_docs/` and replace with a one-line reference. Do this proactively — don't wait for warnings.

<!-- Generated by claude-code-optimizer v1.16.0 -->
