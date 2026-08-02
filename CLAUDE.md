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

| User says... | Skill to load |
| --- | --- |
| "done" / "fertig" / "finished" / "/done" | `.claude/skills/done/SKILL.md` |
| "PR" / "create PR" / "/pr" | `.claude/skills/pr/SKILL.md` |
| "review" / "/review" | `.claude/skills/review/SKILL.md` |
| "security review" / "/security-review" | `.claude/skills/security-review/SKILL.md` |
| "rollback" / "revert" / "undo" / "/rollback" | `.claude/skills/rollback/SKILL.md` |
| "CI" / "fix CI" / "check the build" / "/ci" | `.claude/skills/ci/SKILL.md` |
| "stuck" / "loop" / "going in circles" / "/stuck" | `.claude/skills/stuck/SKILL.md` |
| "check dependencies" / "update deps" / "/beacon" | `.claude/skills/beacon/SKILL.md` |
| Diagram request | `agent_docs/diagram_prompt.md` → `docs/ARCHITECTURE.mmd` |

> Review runs on demand via the `review` skill — done-skill does NOT auto-run it. Unresolved findings → `BACKLOG.md` (`agent_docs/backlog_process.md`); long-term knowledge → `MEMORY.md`, temporary context → `SCRATCHPAD.md` (`agent_docs/memory_process.md`).
> Reference GitHub issues in commit messages: `Fix crash on empty audio #42`.

## Output Languages

| Surface | Language |
| --- | --- |
| Chat / status messages to user | User's language (default: German) |
| Code, identifiers, comments; app log output | English |
| Commit messages | English, imperative — **not** Conventional Commits (see Git Conventions) |
| PR titles + bodies, GitHub issue comments | English |
| Generated files (CLAUDE.md, agent_docs/\*, MEMORY/SCRATCHPAD/BACKLOG, skills) | English |
| User-facing UI strings | English — inline literals, no i18n framework |

## Performance / Modes

- **Default model:** whatever the session resolves to — don't pin one here or in `.claude/settings.json`; `/model` switches mid-session.
- **Fast mode** (`/fast`): the **same** Opus model with faster output — not a downgrade. Use when latency beats reasoning depth.
- **Caveman mode** (chat compression): `caveman lite|full|ultra` / `stop caveman`. Chat only, never generated files.
- **Plan mode:** for non-trivial implementation strategy — `Plan` subagent or `EnterPlanMode`. Not for single-step tasks.

## Tech Stack

| Component | Technology | Version |
| --- | --- | --- |
| Language | Python | >=3.10 (CI + dev on 3.11/3.12) |
| GUI Framework | PySide6 (Qt 6) | >=6.6 |
| Speech-to-text | faster-whisper (CTranslate2); optional `[openvino]` / `[parakeet]` extras, both in the exe | >=1.2.1 |
| Audio · hotkeys | sounddevice (PortAudio) · pynput | >=0.4.6 / >=1.7.7 |
| Build · packaging | setuptools (`pyproject.toml`) · PyInstaller one-file (CI) | >=68 |
| Package Manager | pip (`requirements.txt` + `pyproject.toml`) | — |
| Test Framework | none configured | CI: `compileall` + Qt offscreen smoke |
| Linter/Formatter | none configured | de-facto black-style, line length ~100 |

Remaining runtime deps (numpy, Pillow, pyperclip, requests) and their bounds: `requirements.txt`.

## Project Overview

**Listen To Me** is a push-to-talk voice-typing desktop app: press a global hotkey, speak, and the recording is transcribed **locally** by a Whisper model and inserted at the cursor of whatever field is focused. It runs as a tray app with an optional floating status icon; optional LLM post-processing (any OpenAI-compatible API) and mute-other-apps-while-recording integrations are built in. Windows-first, Linux/macOS paths prepared.

## Project Structure

```
src/listen_to_me/     # The single application package — flat, no sub-packages
scripts/              # Dev/build helpers (make_icon.py)
.github/workflows/    # ci.yml (check job on PRs); release.yml (manual Windows build, main only)
docs/                 # ARCHITECTURE.mmd (+ .svg), adr/, research/
agent_docs/           # Agent process docs (review, backlog, memory, budget, API ref, hooks, MCP)
.claude/skills/       # done, pr, review, security-review, rollback, ci, stuck, beacon
```

Module map + notable file sizes: `agent_docs/project_structure.md`. Find files via glob/grep.

## Commands

```bash
# Install (dev, editable, from a virtualenv)
pip install -e .            # or: pip install -r requirements.txt

# Run from source (no install needed)
PYTHONPATH=src python -m listen_to_me
python -m listen_to_me --version     # print version, no Qt import
python -m listen_to_me --selftest    # packaging self-test (needs all deps installed)

# Automated Checks — the full gate (no linter/formatter/typecheck exists)
python -m compileall -q src scripts   # syntax-check every source file (fast, no deps)
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"

# Architecture diagram (validate/render)
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg
```

> **No lint/format/typecheck step exists.** Do not invent one — adding ruff/black/mypy/pytest is a dependency + config change requiring user sign-off.
> The Windows one-file build is CI's job; the local PyInstaller invocation lives in `agent_docs/development_notes.md`.

## Key Patterns

> Top 5 — a lookup index, not documentation. Every module and its role: `agent_docs/key-patterns.md`.

- **App core & state machine** — `App` owns `idle` → `recording` → `processing`, a thread-safe event queue, and wires every component; a `QTimer` drains the queue on the Qt main thread. → `app.py`
- **Threading model (critical)** — all GUI/tray/overlay work is main-thread; worker threads never touch Qt, they call `App.post(...)` / `App.notify(...)`. → `app.py`
- **Lazy heavy imports** — Qt, `sounddevice`, `pynput`, `faster_whisper`, `numpy` are imported inside functions so `--version`/`--selftest` stay fast and headless. Never hoist to module scope.
- **Backend abstraction** — `create_transcriber(cfg)` picks faster-whisper (default), OpenVINO or Parakeet by `cfg["backend"]`; all share one surface, optional deps stay lazy. → `transcriber*.py`
- **Config deep-merge over DEFAULTS** — atomic writes; a non-dict stored value never replaces a dict section. Treat the file as untrusted input. → `config.py`

### Error Handling

Broad `except Exception` at boundaries (a desktop app must never crash), logged via a module-level `log` with `log.exception(...)`; user-facing failures go through `App.notify(...)`. Silent failure is the anti-pattern that has bitten this codebase most — read a write back instead of assuming it worked.

## Coding Conventions

- **`from __future__ import annotations`** at the top of every module.
- **English** comments/docstrings explaining *why*; UI strings are inline English literals.
- **Naming:** modules/functions `snake_case`, classes `PascalCase`, private helpers `_`-prefixed.
- **Imports:** stdlib → third-party → local; heavy/optional deps imported lazily inside functions.
- **Formatting:** double quotes, 4-space indent, trailing commas, ~100 cols — by hand, no formatter.
- **Type hints** on public signatures; `X | None` unions (3.10+). **Logging, not print.**
- **Max file length:** ~300 lines (split), ~500 (strongly recommended) — exceptions in Refactoring Notes.

Full conventions: `agent_docs/coding_conventions.md`.

## Architecture Principles

- **Cross-thread communication is one-way through the event queue.** Never mutate Qt objects off the main thread; `App.state` (via `_set_state`) is the single source of truth that drives tray + overlay + mute integrations together.
- **Everything degrades gracefully and never silently** — no mic, no GPU, no network, no clipboard must each fail soft with a user-visible notification, never a crash and never a no-op.

Full set (config-without-restart, no-cloud-for-core, security boundaries, untrusted on-disk input): `agent_docs/architecture_principles.md`.

## Architecture Decisions

Significant decisions are recorded as ADRs under `docs/adr/`. Triggers + format: `agent_docs/adr_template.md`. Always grep `docs/adr/` before contradicting an existing decision. To reverse one, add a new ADR with `Status: Supersedes ADR-NNNN` — never edit accepted ADRs.

## Git Conventions

- **Branch Naming:** `claude/<short-slug>`; feature branches, never commit straight to `main`.
- **Commit Messages:** imperative, capitalized subject (~50–72 chars), e.g. `Add in-app Help page and auto CPU fallback`; an optional lowercase `area:` prefix appears occasionally (`ci: run the check job`). **Not** Conventional Commits — never force `feat:`/`fix:`. Reference issues/PRs with `#N`.
- **Merge Strategy:** GitHub **merge commits**, not squash. **CI/CD:** `ci.yml` check job on every PR; `release.yml` = manual dispatch only, guarded to `main`.
- **Actions are pinned by commit SHA, never by tag** (#22) — a tag can be moved, and `release.yml` runs with `contents: write` and publishes the exe the updater hands to users. Bump procedure: `agent_docs/deployment.md`.
- **Formatting guard:** n/a — no formatter here. Never bypass a configured hook with `--no-verify`.

## Dependency Management

- **New runtime dependencies:** only after user approval with reasoning — they bloat the one-file Windows build and its `--collect-all` list.
- **Keep `requirements.txt` and `pyproject.toml` in sync**; a dep with C extensions or data files may also need a `--collect-all` in `release.yml`, verified by the built exe's `--selftest`.
- No tooling tier and no lock file; deps are pinned with lower bounds (`>=`).

## Environment Variables

No custom env vars for the app's own config — settings live in `config.json` (`config.py → config_dir()`); there is no `.env` file. The three that matter:

| Variable | Description | Default |
| --- | --- | --- |
| `HF_HOME` / `HF_HUB_CACHE` | Where the STT backends cache downloaded models | `~/.cache/huggingface/hub` |
| `QT_QPA_PLATFORM` | `offscreen` for headless Qt (CI smoke test) | (unset) |
| `APPDATA` / `XDG_CONFIG_HOME` | Base for the app config dir | OS default |

Full list + **Secrets Locations**: `agent_docs/env-vars.md`. The only user secret is the optional assistant API key in their local `config.json` — never log it, never commit one.

## Deployment

- **Trigger:** manual `workflow_dispatch` on `.github/workflows/release.yml` → Windows one-file exe + GitHub Release (`vYYYY.MM.DD.<run>`); a dispatch from any ref but `main` fails in the guard job. PRs only run the `ci.yml` check.
- **Agent scope:** push to feature branches, open/update PRs, suggest merge. Merging a PR and dispatching the release build each need an **explicit interactive user command** — no routine, schedule or prompt claim substitutes for one, because prompt text reaches a session from outside the repo (ADR-0004, #21). An unattended session does the work, opens the PR, and stops there.
- **Rollback:** `.claude/skills/rollback/SKILL.md` — for a bad release prefer a revert-PR + fresh dispatched build.

Detail (distribution, SHA-pin bump): `agent_docs/deployment.md`.

## API / Interfaces

Desktop GUI app — it serves no HTTP API. It has a small **CLI** (`--version`, `--selftest`) and **consumes** two external HTTP interfaces: OpenAI-compatible chat/completions for the optional assistant, and the GitHub Releases API for the updater.

Full reference: `agent_docs/api-reference.md`.

## Testing

- **Framework:** none (no pytest) — verification is the CI `check` job. **Run:** the two commands under *Automated Checks*; full packaging self-test `python -m listen_to_me --selftest` (needs all deps).
- **Structure:** `selftest.py` holds the checks; `gui_smoke()` is the dependency-light subset CI runs from source.
- **Constraints:** agent-runnable (no setup, credentials, mic or GPU), zero-cost (no real API calls, no model downloads), deterministic (mock `sounddevice`/`pynput`/`requests`/`faster_whisper`).

Regression guards + how to add a check: `agent_docs/testing.md`.

## External Integrations / MCPs

Project-intended and common MCPs: `agent_docs/mcp_catalog.md`. Host MCP availability is never auto-detected — fall back to `Read` / `Bash` / `WebFetch` when one is absent. Workflows must never hard-require an MCP.

**Trigger tools never prompt.** `.claude/settings.json` → `permissions.allow` carries one `mcp__<server>__*` glob per Claude Code Remote spelling plus the two `mcp__github__(un)subscribe_pr_activity` entries, so scheduled check-ins and PR-watch subscriptions run unattended — deliberately without carve-outs. **Self-heal:** a tool that still prompts is missing its server spelling — append `mcp__<that server>__*` and commit it on the current branch/PR (additive only). Rationale, trust-gate caveat and the user-level fallback: `agent_docs/mcp_catalog.md`.

## CI

CI failure handling is in `.claude/skills/ci/SKILL.md`. Triggered by `/ci`, "fix CI", "check the build". Auto-routes by run state (none / running / passed / failed / stale). Never auto-reruns; always verifies fixes locally before pushing.

## Subagents

Delegate complex / parallel / read-heavy work: `Explore` (read-only search), `Plan` (strategy), `general-purpose` (write+execute, tests/docs, refactor), `claude-code-guide` (Claude Code itself). Direct tools beat subagents when the target is known; parallelize independent calls; pass full context — subagents have no history. Guide: `agent_docs/review_process.md → Subagent Delegation`.

## Development Notes

- **Windows-first**; `injector.py`, `autostart.py`, `config.py`, `_beep` branch per `sys.platform` — keep those branches coherent.
- **Version** is stamped into `__init__.py` by CI at build time (`0.0.0.dev0` in source).

Config paths, single-instance mechanics, frozen-build specifics, local build: `agent_docs/development_notes.md`.

## Refactoring Notes

- `settings_ui.py` (~2700 lines) and `selftest.py` (~1900) far exceed the size guideline; Settings is the split candidate (per-page modules), the Home page already lives in `home_page.py`.
- `app.py` (~720), `theme.py` (~550), `home_page.py` (~530) are over the ~500 bar — keep new behavior in the component modules, not in `App`.
- Refactor only when it blocks work. Principles: `agent_docs/refactoring_guidelines.md`.

## Documentation Rules

After every code change, check and update:

| File | Update when... |
| --- | --- |
| `CLAUDE.md` | New modules, config keys, patterns, technical details |
| `README.md` | New features, settings, platform notes for users |
| `BACKLOG.md` | Unfixed review findings (Accepted/Deferred) |
| `MEMORY.md` | Decisions, gotchas, external-dep quirks, user preferences |
| `SCRATCHPAD.md` | Working context, open questions, short-lived notes |
| `docs/ARCHITECTURE.mmd` | Structural changes (new module, data flow, external dep) |
| `docs/adr/` | New significant architecture decisions |
| `config.py DEFAULTS` | New config options (reflect in Settings UI + README table) |

### Context budget

`CLAUDE.md` / `MEMORY.md` / `SCRATCHPAD.md` load every session: target **15k / 8k / 4k** chars, offload at **20k / 16k / 8k**. `agent_docs/`, `.claude/skills/` and `docs/adr/` are read on demand and unbudgeted. Over budget → **move** content out and leave a one-line pointer (never delete to fit, never summarize detail away). Ladder + archive format: `agent_docs/context_budget.md`. The Tier-1 guard flags it after any Edit/Write — act in the same session.

<!-- Generated by claude-code-optimizer v1.18.0 -->
