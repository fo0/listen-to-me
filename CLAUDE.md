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

> Diagram request → `agent_docs/diagram_prompt.md` → `docs/ARCHITECTURE.mmd`.
> Review runs on demand via the `review` skill — done-skill does NOT auto-run it. Unresolved findings → `BACKLOG.md` (`agent_docs/backlog_process.md`); long-term knowledge → `MEMORY.md`, temporary context → `SCRATCHPAD.md` (`agent_docs/memory_process.md`).
> Reference GitHub issues in commit messages: `Fix crash on empty audio #42`.

## Output Languages

- **Chat / status messages to the user:** the user's language (default: German).
- **Everything else is English** — code, identifiers, comments, app log output; commit messages (imperative, **not** Conventional Commits — see Git Conventions); PR titles + bodies; GitHub issue comments; every generated file (CLAUDE.md, `agent_docs/*`, MEMORY/SCRATCHPAD/BACKLOG, skills); and user-facing UI strings (inline literals, no i18n framework).
- **Technical terms — every surface, chat included: English, never translated.**

**Technical terms are never translated** — not even inside a German sentence. Keep the English word verbatim and inflect around it: „2 Bugs gefixt", „Code Smell in `app.py`", „PR gemerged", „Build ist rot" — never „Programmfehler", „Code-Geruch", „Zusammenführungsantrag". Covers bug · smell · lint · build · commit · merge · rebase · branch · PR · review · refactoring · deployment · rollback · issue · breaking change · hotfix · flaky test · regression · edge case · stack trace · dependency · tech debt, plus everything that names something real: file paths, commands, tool / skill / hook names, status labels, error strings (quoted verbatim). Test: English in code, a commit or a PR → English in chat.

## Performance / Modes

- **Default model:** whatever the session resolves to — don't pin one here or in `.claude/settings.json`; `/model` switches mid-session.
- **Fast mode** (`/fast`): the **same** Opus model with faster output — not a downgrade. Use when latency beats reasoning depth.
- **Caveman mode** (chat compression): `caveman lite|full|ultra` / `stop caveman`. Chat only, never generated files.
- **Orca mode** (orchestrator-only): `/orca` toggles it, `/orca <N>` sets the parallel width (default 5). While on, the agent itself does no task work — every unit goes to a subagent at the session's model and effort. Off by default; contract in `.claude/skills/orca/SKILL.md`.
- **Plan mode:** for non-trivial implementation strategy — `Plan` subagent or `EnterPlanMode`. Not for single-step tasks.

## Autonomy

Which session you are in is resolvable, so it is a rule and not a guess: `$CLAUDE_CODE_REMOTE` is `"true"` in Claude Code web/cloud sessions — routine runs included — and unset in the local CLI.

- **Unattended** (`CLAUDE_CODE_REMOTE=true`, or the session's initial instructions are a routine): nobody is there to answer. Never end a turn with a question — decide under an assumption you state, finish every part that isn't blocked, and carry the open point into the final report or `BACKLOG.md`. A routine run has no permission prompts at all, so an unattended session that "waits for approval" waits forever.
- **Interactive** (local CLI): asking is cheap. Ask when two readings of the task produce materially different work; otherwise decide and mention the call.
- **Both:** an action that is destructive _and_ not ordered _and_ not standard practice gets the same answer in either mode — skip it, put it in the report with the recommendation, and finish everything it does not block. Never guess at it. The instances keep their own gates: merges → `.claude/skills/pr/SKILL.md → /pr merge`, reversals and force operations → `.claude/skills/rollback/SKILL.md`, release dispatch → _Deployment_, secrets → `agent_docs/env-vars.md`.

## Scheduled Work

Three schedulers with different lifetimes: **Routines** (cloud, durable, ≥1 h, survive the session), **`/loop` + `CronCreate`/`CronList`/`CronDelete`** (this session only, 7-day expiry), **Desktop scheduled tasks** (local machine). Choosing one, creating/listing/deleting jobs, and the cleanup contract for agent-created jobs: `.claude/skills/scheduler/SKILL.md`. This repo's default prompt for a bare `/loop`: `.claude/loop.md`.

## Tech Stack

Python >=3.10 (CI 3.12) · PySide6 (Qt 6) >=6.6 · faster-whisper >=1.2.1 (+ optional OpenVINO / Parakeet backends) · sounddevice · pynput · pip + setuptools, PyInstaller one-file in CI. **No linter, formatter, type-checker or test framework for Python** — Prettier (via `npx`) formats Markdown only.

Full table, version reasoning and the packaging asymmetry: `agent_docs/tech_stack.md`. Runtime dep bounds: `requirements.txt`.

## Project Overview

**Listen To Me** is a push-to-talk voice-typing desktop app: press a global hotkey, speak, and the recording is transcribed **locally** by a Whisper model and inserted at the cursor of whatever field is focused. It runs as a tray app with an optional floating status icon; optional LLM post-processing (any OpenAI-compatible API) and mute-other-apps-while-recording integrations are built in. Windows-first, Linux/macOS paths prepared.

## Project Structure

```
src/listen_to_me/     # The single application package — flat, no sub-packages
scripts/              # Dev/build helpers (make_icon.py)
.github/workflows/    # ci.yml (PR check); docs-format.yml (Prettier on **.md);
                      # release.yml (manual Windows build, main only)
docs/                 # ARCHITECTURE.mmd (+ .svg), adr/, research/
agent_docs/           # Agent process docs (review, backlog, memory, budget, API ref, MCP)
.claude/              # settings.json + loop.md; skills/: done, pr, review, security-review,
                      # rollback, ci, stuck, beacon, scheduler, orca
```

Module map + file sizes: `agent_docs/project_structure.md`. Setup hints, platform quirks, single-instance mechanics, frozen-build specifics: `agent_docs/development_notes.md`. Find files via glob/grep.

## Commands

```bash
# Install (dev, editable, from a virtualenv)
pip install -e .            # or: pip install -r requirements.txt

# Run from source (no install needed)
PYTHONPATH=src python -m listen_to_me
python -m listen_to_me --version     # print version, no Qt import
python -m listen_to_me --selftest    # packaging self-test (needs all deps installed)
python -m listen_to_me --help        # flag list + config location, no Qt import
# Any other argument is refused with exit code 2 instead of starting the tray app.

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

- **App core & state machine** — `App` owns `idle` → `recording` → `processing`, a thread-safe event queue, and wires every component; a `QTimer` drains the queue on the Qt main thread. → `app.py`
- **Threading model (critical)** — all GUI/tray/overlay work is main-thread; workers never touch Qt, they call `App.post(...)` / `App.notify(...)`. → `app.py`
- **Lazy heavy imports** — Qt, `sounddevice`, `pynput`, `faster_whisper`, `numpy` are imported inside functions so `--version`/`--selftest` stay headless. Never hoist to module scope.
- **Backend abstraction** — `create_transcriber(cfg)` picks faster-whisper (default), OpenVINO or Parakeet by `cfg["backend"]`; one surface, optional deps stay lazy. → `transcriber*.py`
- **Config deep-merge over DEFAULTS** — atomic writes; a non-dict stored value never replaces a dict section. Treat the file as untrusted input. → `config.py`

### Error Handling

Broad `except Exception` at boundaries (a desktop app must never crash), logged via a module-level `log` with `log.exception(...)`; user-facing failures go through `App.notify(...)`. Silent failure is the anti-pattern that has bitten this codebase most — read a write back instead of assuming it worked.

## Coding Conventions

- **`from __future__ import annotations`** at the top of every module.
- **English** comments/docstrings explaining _why_; UI strings are inline English literals.
- **Naming:** modules/functions `snake_case`, classes `PascalCase`, private helpers `_`-prefixed.
- **Imports:** stdlib → third-party → local; heavy/optional deps imported lazily inside functions.
- **Formatting:** double quotes, 4-space indent, trailing commas, ~100 cols — by hand, no formatter.
- **Type hints** on public signatures; `X | None` unions (3.10+). **Logging, not print.**
- **Max file length:** ~300 lines (split), ~500 (strongly recommended) — exceptions in Refactoring Notes.

Full conventions: `agent_docs/coding_conventions.md`.

## Architecture Principles

- **Cross-thread communication is one-way through the event queue.** Never mutate Qt objects off the main thread; `App.state` (via `_set_state`) is the single source of truth driving tray + overlay + mute integrations together.
- **Everything degrades gracefully and never silently** — no mic, no GPU, no network, no clipboard must each fail soft with a user-visible notification, never a crash and never a no-op.

Full set (config-without-restart, no-cloud-for-core, security boundaries, untrusted on-disk input): `agent_docs/architecture_principles.md`.

## Architecture Decisions

Significant decisions are recorded as ADRs under `docs/adr/`. Triggers + format: `agent_docs/adr_template.md`. Always grep `docs/adr/` before contradicting an existing decision. To reverse one, add a new ADR with `Status: Supersedes ADR-NNNN` — never edit accepted ADRs.

## Git Conventions

- **Branch Naming:** `claude/<short-slug>`; feature branches, never commit straight to `main`.
- **Commit Messages:** imperative, capitalized subject (~50–72 chars), e.g. `Add in-app Help page and auto CPU fallback`; an optional lowercase `area:` prefix appears occasionally (`ci: run the check job`). **Not** Conventional Commits — never force `feat:`/`fix:`. Reference issues/PRs with `#N`.
- **Merge Strategy:** GitHub **merge commits**, not squash. **CI/CD:** `ci.yml` check job on every PR; `release.yml` = manual dispatch only, guarded to `main`.
- **Cloud / routine runs:** a `claude/`-prefixed branch is always accepted; a push to any other branch is rejected when the branch is protected, carries someone else's open PR, or holds commits authored by someone else. Unattended work therefore starts on `claude/<slug>` unless the task names a branch.
- **Actions are pinned by commit SHA, never by tag** (#22) — rationale + bump procedure: `agent_docs/deployment.md`.
- **Never bypass a git hook with `--no-verify`** — unconditional, whatever is or isn't configured.

## Dependency Management

- **New runtime dependencies:** only after user approval with reasoning — they bloat the one-file Windows build and its `--collect-all` list.
- **Keep `requirements.txt` and `pyproject.toml` in sync**; a dep with C extensions or data files may also need a `--collect-all` in `release.yml`, verified by the built exe's `--selftest`.
- No tooling tier and no lock file; deps are pinned with lower bounds (`>=`).

## Environment Variables

No custom env vars for the app's own config — settings live in `config.json` (`config.py → config_dir()`); there is no `.env` file. The three that matter:

| Variable                      | Description                                    | Default                    |
| ----------------------------- | ---------------------------------------------- | -------------------------- |
| `HF_HOME` / `HF_HUB_CACHE`    | Where the STT backends cache downloaded models | `~/.cache/huggingface/hub` |
| `QT_QPA_PLATFORM`             | `offscreen` for headless Qt (CI smoke test)    | (unset)                    |
| `APPDATA` / `XDG_CONFIG_HOME` | Base for the app config dir                    | OS default                 |

Full list + **Secrets Locations**: `agent_docs/env-vars.md`. The only user secret is the optional assistant API key in their local `config.json` — never log it, never commit one.

## Deployment

- **Trigger:** manual `workflow_dispatch` on `.github/workflows/release.yml` → Windows one-file exe + GitHub Release (`vYYYY.MM.DD.<run>`); a dispatch from any ref but `main` fails in the guard job. PRs only run the `ci.yml` check.
- **Agent scope:** push to feature branches, open/update PRs, suggest merge. Merging a PR and dispatching the release build each need an explicit user command.
- **Routine exception:** merges ordered by an owner-authorized routine count as an explicit user command — conditions + full gate: `.claude/skills/pr/SKILL.md → /pr merge` (single source of truth). Release dispatch is never covered; reasoning + accepted risk: ADR-0005 (supersedes ADR-0004, #21).
- **Rollback:** `.claude/skills/rollback/SKILL.md` — for a bad release prefer a revert-PR + fresh dispatched build.

Pipeline, distribution, SHA-pin bump: `agent_docs/deployment.md`.

## API / Interfaces

Desktop GUI app — it serves no HTTP API. It has a small **CLI** (`--version`, `--selftest`, `-h`/`--help`; anything else exits `2`) and **consumes** two external HTTP interfaces: OpenAI-compatible chat/completions for the optional assistant, and the GitHub Releases API for the updater.

Full reference: `agent_docs/api-reference.md`.

## Testing

- **Framework:** none (no pytest) — verification is the CI `check` job. **Run:** the two commands under _Automated Checks_; full packaging self-test `python -m listen_to_me --selftest` (needs all deps).
- **Structure:** `selftest.py` holds the checks; `gui_smoke()` is the dependency-light subset CI runs from source.
- **Constraints:** agent-runnable, zero-cost, deterministic — binding wording in `agent_docs/review_process.md → Test execution constraints`.

Regression guards + how to add a check: `agent_docs/testing.md`.

## External Integrations / MCPs

Host MCP availability is never auto-detected — fall back to `Read` / `Bash` / `WebFetch`, and never hard-require an MCP. One canonical file covers the rest: `agent_docs/mcp_catalog.md` — the MCP tables, the `gh` → `mcp__github__*` equivalence the PR/CI/rollback skills rely on, the allowlist rationale, and what makes a server reachable in a cloud or routine run (this repo has no `.mcp.json`, so unattended runs use the standard tools).

**Trigger tools never prompt.** `.claude/settings.json` → `permissions.allow` carries one `mcp__<server>__*` glob per Claude Code Remote spelling, the two `mcp__github__(un)subscribe_pr_activity` entries, and one `Bash(...)` entry per verified check command. **Self-heal:** a tool that still prompts is a missing server spelling — append `mcp__<that server>__*` (the glob, never a single tool name) and commit it. Additive only: **never write `deny`/`ask`**, never remove a glob.

## CI

CI failure handling is in `.claude/skills/ci/SKILL.md`. Triggered by `/ci`, "fix CI", "check the build". Auto-routes by run state (none / running / passed / failed / stale). Never auto-reruns; always verifies fixes locally before pushing.

## Subagents

Delegate complex / parallel / read-heavy work: `Explore` (read-only search), `Plan` (strategy), `general-purpose` (write+execute), `claude-code-guide` (Claude Code itself). Direct tools beat subagents when the target is known; parallelize independent calls; pass full context — subagents have no history. **Orca mode** (`/orca`) makes delegation the only path — while it is on these thresholds do not apply (`.claude/skills/orca/SKILL.md`). Guide: `agent_docs/review_process.md → Subagent Delegation`.

## Refactoring Notes

- `settings_ui.py` and `selftest.py` far exceed the size guideline; Settings is the split candidate (per-page modules), the Home page already lives in `home_page.py`. `app.py` and `theme.py` are over the ~500 bar — keep new behavior in the component modules, not in `App`.
- Refactor only when it blocks work. Current line counts (they drift — re-measure, never trust a copied number), the invariants a refactor must preserve, and the principles: `agent_docs/refactoring_guidelines.md`.

## Documentation Rules

After every code change, check and update:

- `CLAUDE.md` — new modules, config keys, patterns, technical details
- `README.md` — new features, settings, platform notes for users
- `BACKLOG.md` — unfixed review findings (Accepted/Deferred)
- `MEMORY.md` — decisions, gotchas, external-dep quirks, user preferences
- `SCRATCHPAD.md` — working context, open questions, short-lived notes
- `docs/ARCHITECTURE.mmd` — structural changes (new module, data flow, external dep)
- `docs/adr/` — new significant architecture decisions
- `config.py DEFAULTS` — new config options (reflect in Settings UI + README table)

### Context budget

`CLAUDE.md` / `MEMORY.md` / `SCRATCHPAD.md` load every session: target **15k / 8k / 4k** chars, offload at **20k / 16k / 8k**. `agent_docs/`, `.claude/skills/` and `docs/adr/` are read on demand and unbudgeted. Over budget → **move** content out and leave a one-line pointer (never delete to fit, never summarize detail away). Ladder + archive format: `agent_docs/context_budget.md`. The Tier-1 guard flags it after any Edit/Write — act in the same session.

<!-- Generated by claude-code-optimizer v1.22.0 -->
