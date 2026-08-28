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

Skills live at `.claude/skills/<name>/SKILL.md` — load the one whose trigger fires.

| User says...                                     | Skill             |
| ------------------------------------------------ | ----------------- |
| "done" / "fertig" / "finished" / "/done"         | `done`            |
| "PR" / "create PR" / "/pr"                       | `pr`              |
| "review" / "/review"                             | `review`          |
| "security review" / "/security-review"           | `security-review` |
| "rollback" / "revert" / "undo" / "/rollback"     | `rollback`        |
| "CI" / "fix CI" / "check the build" / "/ci"      | `ci`              |
| "stuck" / "loop" / "going in circles" / "/stuck" | `stuck`           |
| "check dependencies" / "update deps" / "/beacon" | `beacon`          |
| "schedule" / "nightly" / "later" / "/scheduler"  | `scheduler`       |
| "orca" / "orchestrator mode" / "/orca"           | `orca`            |

> Diagram request → `agent_docs/diagram_prompt.md` → `docs/ARCHITECTURE.mmd`. Review runs on demand via the `review` skill — done-skill never auto-runs it. Findings → `BACKLOG.md` (`agent_docs/backlog_process.md`); knowledge → `MEMORY.md` / `SCRATCHPAD.md` (`agent_docs/memory_process.md`). Reference issues in commits: `Fix crash on empty audio #42`.

## Output Languages

- **Chat / status messages to the user:** the user's language (default: German).
- **Everything else is English** — code, identifiers, comments, app log output; commit messages (imperative, **not** Conventional Commits — see Git Conventions); PR titles + bodies; issue comments; every generated file (CLAUDE.md, `agent_docs/*`, MEMORY/SCRATCHPAD/BACKLOG, skills); user-facing UI strings (inline literals, no i18n framework).
- **Technical terms — every surface, chat included: English, never translated.**

**Technical terms are never translated** — not even inside a German sentence. Keep the English word verbatim and inflect around it: „2 Bugs gefixt", „Code Smell in `app.py`", „PR gemerged", „Build ist rot" — never „Programmfehler", „Code-Geruch", „Zusammenführungsantrag". Test: English in code, a commit or a PR → English in chat. Full vocabulary (and the paths / commands / error strings it also covers): `agent_docs/coding_conventions.md → Never-translate term list`.

## Caveman Mode — chat compression (default `full`)

In force from the first reply of every session — no activation step. Chat, status messages and confirmations only; **never** files (`CLAUDE.md`, `agent_docs/*`, MEMORY/SCRATCHPAD/BACKLOG, skills), code, commits, PR bodies or issue comments.

- **Shorten by selection, not by compression.** Cut what would not change the reader's next move — never squeeze prose into abbreviations, arrow chains (`A → B → fails`) or invented shorthand. Drop articles, filler, hedging; fragments are fine for a status line. Terms exact, code blocks unchanged, errors quoted verbatim.
- **The closing summary is never compressed** — outcome first, then what it rests on, in complete sentences, each file/commit/flag in its own clause. Normal prose too for security warnings, irreversible-action confirmations, and wherever fragment order risks a misread.

`caveman lite|full|ultra` switches mode mid-session; **`stop caveman` turns it off** for the rest of it. Neither carries forward — the next session starts at `full`.

## Autonomy & Modes

Which session you are in is resolvable, so it is a rule and not a guess: `$CLAUDE_CODE_REMOTE` is `"true"` in Claude Code web/cloud sessions — routine runs included — and unset in the local CLI.

- **Unattended:** never end a turn with a question. Decide under a stated assumption, finish everything unblocked, carry the open point into the report or `BACKLOG.md`. **Interactive:** ask only when two readings produce materially different work.
- **Both:** destructive _and_ not ordered _and_ not standard practice → skip it, recommend it in the report, finish the rest. Gates keep one source of truth each: merges → `.claude/skills/pr/SKILL.md → /pr merge`, reversals → `.claude/skills/rollback/SKILL.md`, release dispatch → _Deployment_, secrets → `agent_docs/env-vars.md`.

Full wording and the mode reference (`/model`, `/fast`, caveman, `/orca`, plan mode): `agent_docs/autonomy.md`.

## Handoff Prompt — when a turn ends on a decision

A turn that hands the decision back — a plan up for approval, options, an open question, an ambiguity you could not resolve — ends with **one** ready-to-send prompt: the one you would send yourself if your recommendation were taken. It goes last, _after_ the question, never instead of it.

```
<objective in one sentence> — <the recommended path>.
In scope: <...>. Out of scope: <...>.
Steps: <1 … n>. /review after every step, one overall review over the combined diff at the end by an agent that wrote none of it, then /done.
Done when: <observable condition>.
```

- **Your recommendation, not a menu.** One path, spelled out completely enough that pasting it is the whole instruction — no "as discussed above", no second option folded in. The user may still edit or pick differently; that is their move, not a reason to hedge yours.
- **Only commands that already exist:** this project's `/review` and `/done`, plus Claude Code's `/loop <interval> <prompt>` for a recurring pass or one waiting on external state, and `/goal <done-condition>` sent first where the run must not stop before that condition holds. Never invent one.
- **Never compressed**, whatever the caveman mode — same carve-out as the closing summary.

**Not on:** a finished turn; a yes/no confirmation of something just ordered (`/pr merge`, a `rollback` phase); and never in an unattended run, where nobody pastes it and _Autonomy_ rules out the question anyway.

## Scheduled Work

Three schedulers, three lifetimes: **Routines** (cloud, durable, ≥1 h), **`/loop` + `Cron*`** (this session, 7-day expiry), **Desktop tasks** (local machine). Selection, job management and the cleanup contract for agent-created jobs: `.claude/skills/scheduler/SKILL.md`. Default prompt for a bare `/loop`: `.claude/loop.md`.

## Tech Stack

Python >=3.10 (CI 3.12) · PySide6 (Qt 6) >=6.6 · faster-whisper >=1.2.1 (+ optional OpenVINO / Parakeet backends) · sounddevice · pynput · pip + setuptools, PyInstaller one-file in CI. **No linter, formatter, type-checker or test framework for Python** — Prettier (via `npx`) formats Markdown only.

Full table, version reasoning, packaging asymmetry: `agent_docs/tech_stack.md`. Dep bounds: `requirements.txt`.

## Project Overview

**Listen To Me** is a push-to-talk voice-typing tray app: press a global hotkey, speak, and the recording is transcribed **locally** by a Whisper model and inserted at the cursor of whatever field is focused. Windows-first, Linux/macOS paths prepared. Feature list: `README.md`.

## Project Structure

```
src/listen_to_me/     # The single application package — flat, no sub-packages
scripts/              # Dev/build helpers
.github/workflows/    # ci.yml, docs-format.yml, release.yml
docs/                 # ARCHITECTURE.mmd (+ .svg), adr/, research/
agent_docs/           # Agent process docs
.claude/              # settings.json, loop.md, skills/
```

Full tree, module map, file sizes: `agent_docs/project_structure.md`. Setup hints, platform quirks, single-instance mechanics, frozen-build specifics: `agent_docs/development_notes.md`. Find files via glob/grep.

## Commands

```bash
# Install (dev, editable, from a virtualenv)
pip install -e .            # or: pip install -r requirements.txt

# Run from source (no install needed)
PYTHONPATH=src python -m listen_to_me
python -m listen_to_me --version     # print version, no Qt import
python -m listen_to_me --selftest    # packaging self-test (needs all deps installed)
python -m listen_to_me --help        # flag list + config location, no Qt import

# Automated Checks — the full gate (no Python linter/formatter/typecheck exists)
python -m compileall -q src scripts   # syntax-check every source file (fast, no deps)
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"

# Markdown formatting — the only formatter; version pinned in docs-format.yml
npx --yes prettier@3.9.6 --write "**/*.md"   # --check is the read-only CI variant

# Architecture diagram (validate/render)
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg
```

> **No lint/format/typecheck step exists for Python.** Do not invent one — adding ruff/black/mypy/pytest is a dependency + config change requiring user sign-off.
> The Windows one-file build is CI's job; the local PyInstaller invocation lives in `agent_docs/development_notes.md`.

## Key Patterns

> Top 5 — a lookup index, not documentation. Every module and its role: `agent_docs/key-patterns.md`.

- **App core & state machine** — `idle` → `recording` → `processing` + a thread-safe event queue a `QTimer` drains on the Qt main thread. → `app.py`
- **Threading model (critical)** — GUI/tray/overlay work is main-thread only; workers never touch Qt, they call `App.post(...)` / `App.notify(...)`. → `app.py`
- **Lazy heavy imports** — Qt, `sounddevice`, `pynput`, `faster_whisper`, `numpy` imported inside functions so `--version`/`--selftest` stay headless. Never hoist.
- **Backend abstraction** — `create_transcriber(cfg)` picks faster-whisper / OpenVINO / Parakeet by `cfg["backend"]`. → `transcriber*.py`
- **Config deep-merge over DEFAULTS** — atomic writes; a non-dict stored value never replaces a dict section. Untrusted input. → `config.py`

## Coding Conventions

- **`from __future__ import annotations`** at the top of every module.
- **English** comments/docstrings explaining _why_; UI strings are inline English literals.
- **Naming:** modules/functions `snake_case`, classes `PascalCase`, private helpers `_`-prefixed.
- **Imports:** stdlib → third-party → local; heavy/optional deps imported lazily inside functions.
- **Type hints** on public signatures; `X | None` unions (3.10+). **Logging, not print.**
- **Max file length:** ~300 lines (split), ~500 (strongly recommended) — exceptions in Refactoring Notes.

Formatting (hand-kept: double quotes, 4-space indent, trailing commas, ~100 cols), the never-translate term list and **error handling** (broad `except` at boundaries, `log.exception`, never a silent no-op): `agent_docs/coding_conventions.md`.

## Architecture Principles

The two an agent violates by accident: **`App.state` (via `_set_state`) is the single source of truth** driving tray + overlay + mute integrations together, with cross-thread traffic one-way through the event queue; and **everything degrades gracefully, never silently** — no mic, no GPU, no network, no clipboard each fail soft with a user-visible notification, never a crash and never a no-op.

Full set (config-without-restart, no-cloud-for-core, security boundaries, untrusted on-disk input): `agent_docs/architecture_principles.md`.

## Architecture Decisions

Recorded as ADRs under `docs/adr/`; triggers + format: `agent_docs/adr_template.md`. Grep `docs/adr/` before contradicting one. To reverse a decision, add a new ADR with `Status: Supersedes ADR-NNNN` — never edit accepted ADRs.

## Git Conventions

- **Branch Naming:** `claude/<short-slug>`; feature branches, never commit straight to `main`.
- **Commit Messages:** imperative, capitalized subject (~50–72 chars), e.g. `Add in-app Help page and auto CPU fallback`; an optional lowercase `area:` prefix appears occasionally (`ci: run the check job`). **Not** Conventional Commits — never force `feat:`/`fix:`. Reference issues/PRs with `#N`.
- **Merge Strategy:** GitHub **merge commits**, not squash. **CI/CD:** `ci.yml` check job on every PR; `release.yml` = manual dispatch only, guarded to `main`.
- **Cloud / routine runs:** a `claude/`-prefixed branch is always accepted; a push to any other branch is rejected when the branch is protected, carries someone else's open PR, or holds commits authored by someone else. Unattended work therefore starts on `claude/<slug>` unless the task names a branch.
- **Actions are pinned by commit SHA, never by tag** (#22) — rationale + bump procedure: `agent_docs/deployment.md`.
- **Never bypass a git hook with `--no-verify`** — unconditional, whatever is or isn't configured.

## Dependency Management

- **New runtime dependencies:** only after user approval with reasoning — they bloat the one-file Windows build.
- **Keep `requirements.txt` and `pyproject.toml` in sync**; a dep with C extensions or data files also needs a `--collect-all` in `release.yml`, verified by the built exe's `--selftest`.
- No tooling tier, no lock file; deps pinned with lower bounds (`>=`).

## Environment Variables

No custom env vars for the app's own config — settings live in `config.json` (`config.py → config_dir()`), there is no `.env`. The three that matter:

- `HF_HOME` / `HF_HUB_CACHE` — STT model cache (default `~/.cache/huggingface/hub`)
- `QT_QPA_PLATFORM` — `offscreen` for headless Qt (the CI smoke test); unset otherwise
- `APPDATA` / `XDG_CONFIG_HOME` — base for the app config dir (OS default)

Full list + **Secrets Locations**: `agent_docs/env-vars.md`. The only user secret is the optional assistant API key in their local `config.json` — never log it, never commit one.

## Deployment

- **Trigger:** manual `workflow_dispatch` on `.github/workflows/release.yml` → Windows one-file exe + GitHub Release (`vYYYY.MM.DD.<run>`); a dispatch from any ref but `main` fails in the guard job. PRs only run the `ci.yml` check.
- **Agent scope:** push to feature branches, open/update PRs, suggest merge. Merging a PR and dispatching a release each need an explicit user command; an owner-authorized routine's merge counts as one, a release dispatch never does (gate: `.claude/skills/pr/SKILL.md → /pr merge`, reasoning: ADR-0005).
- **Rollback:** `.claude/skills/rollback/SKILL.md` — for a bad release prefer a revert-PR + fresh dispatched build.

Pipeline, distribution, routine wording, SHA-pin bump: `agent_docs/deployment.md`.

## API / Interfaces

Desktop GUI app — serves no HTTP API. It has a small **CLI** (`--version`, `--selftest`, `-h`/`--help`; anything else exits `2`) and **consumes** two external HTTP interfaces: OpenAI-compatible chat/completions for the optional assistant, and the GitHub Releases API for the updater. Full reference: `agent_docs/api-reference.md`.

## Testing

No framework (no pytest) — verification is the CI `check` job: the two commands under _Automated Checks_, plus `python -m listen_to_me --selftest` when all deps are installed. `selftest.py` holds the checks, `gui_smoke()` the dependency-light subset CI runs from source. Constraints (agent-runnable, zero-cost, deterministic): `agent_docs/review_process.md → Test execution constraints`. Regression guards + how to add a check: `agent_docs/testing.md`.

## External Integrations / MCPs

Host MCP availability is never auto-detected — fall back to `Read` / `Bash` / `WebFetch`, and never hard-require an MCP. One canonical file covers the rest: `agent_docs/mcp_catalog.md` — the MCP tables, the `gh` → `mcp__github__*` equivalence the PR/CI/rollback skills rely on, the allowlist rationale, and cloud/routine reachability (this repo has no `.mcp.json`, so unattended runs use the standard tools).

**Trigger-tool self-heal — local sessions only.** A tool that still prompts is a missing server spelling: append `mcp__<that server>__*` (the glob, never a single tool name) to `.claude/settings.json` → `permissions.allow` and commit it. **Never write `deny`/`ask`**, never remove a glob. Under `$CLAUDE_CODE_REMOTE=true` append nothing — it cannot take effect there; name the one-time user-scope fix once and carry on (`agent_docs/mcp_catalog.md → Prompt-free triggers everywhere`).

## CI

Failure handling: `.claude/skills/ci/SKILL.md` (`/ci`, "fix CI", "check the build"). Auto-routes by run state; never auto-reruns; always verifies fixes locally before pushing.

## Subagents — orchestrator mode is the default

**Every session starts in orchestrator mode, width 5.** The main agent decides and delegates; subagents do the task work — not a mode to switch on, but how work happens here. `/orca <N>` changes the width, `/orca off` drops to plain behavior for that session only. Contract (what the orchestrator keeps, quality parity by omission, disjoint write scopes, verify-the-diff): `.claude/skills/orca/SKILL.md`.

**The type carries tool access** (`Explore`, `Plan`, `general-purpose`, `claude-code-guide`); **the role carries the lens**, named in the wave report — seat the ones the change calls for, never two the same:

| Role          | Earns a seat when                                       |
| ------------- | ------------------------------------------------------- |
| `implementer` | always, for any code change                             |
| `reviewer`    | any code change — **never the agent that wrote it**     |
| `architect`   | the change adds, moves or crosses a boundary            |
| `domain`      | it encodes a domain or business rule                    |
| `product`     | the request is ambiguous or scope could drift           |
| `docs`        | a documented interface or contract changes              |
| `security`    | it touches trust boundaries, untrusted input or secrets |

A `model:` pinned in a repo-local `.claude/agents/*.md` overrides model inheritance. Full guide: `agent_docs/review_process.md → Subagent Delegation`.

## Refactoring Notes

**Refactor only when it blocks work.** Several files are over the size guideline (`settings_ui.py`, `selftest.py` far over), so keep new behavior in the component modules rather than growing `App` or the settings window. Files, split plans, invariants a refactor must preserve, current line counts (they drift — re-measure, never copy a number): `agent_docs/refactoring_guidelines.md`.

## Documentation Rules

After every code change, check and update:

- `CLAUDE.md` (modules, config keys, patterns) · `README.md` (features, settings, platform notes for users)
- `BACKLOG.md` (unfixed review findings) · `MEMORY.md` (decisions, gotchas, dep quirks, preferences) · `SCRATCHPAD.md` (working context, open questions)
- `docs/ARCHITECTURE.mmd` (new module, data flow, external dep) · `docs/adr/` (new significant decisions)
- `config.py DEFAULTS` — new config options, reflected in the Settings UI + README table

### Context budget

`CLAUDE.md` / `MEMORY.md` / `SCRATCHPAD.md` load every session: target **15k / 8k / 4k** chars, offload at **20k / 16k / 8k**. `agent_docs/`, `.claude/skills/` and `docs/adr/` are read on demand and unbudgeted. Over budget → **move** content out and leave a one-line pointer (never delete to fit, never summarize detail away). Ladder + archive format: `agent_docs/context_budget.md`. The Tier-1 guard flags it after any Edit/Write — act in the same session.

<!-- Generated by claude-code-optimizer v1.30.0 -->
