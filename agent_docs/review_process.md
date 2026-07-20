# Review Process

This file defines the mandatory review process executed after every implementation.

## Core Rules

1. **Every implementation triggers a full review** — no exceptions, no user prompt needed.
2. **Never commit without completed review** — all P0/P1 findings must be fixed first.
3. **Deterministic checks run first** — the syntax check + Qt smoke test catch what they catch. The review covers what tools cannot (this project has no linter/typechecker).
4. **Fix, don't list** — when a finding is actionable, fix it immediately. Don't just document it.
5. **Re-review after fixes** — if fixes touched code, re-run automated checks and re-review affected categories only.

## Severity Definitions

Severity is based on impact, not category:

| Severity | Definition | Examples |
|----------|-----------|---------|
| **P0 — Critical** | Can cause data loss, security breach, or a hard crash of a must-never-crash tray app | Unhandled exception on the Qt main thread, cross-thread Qt access from a worker, clipboard/history data loss, secret leaked to logs |
| **P1 — Important** | Functionally incorrect, poor UX, or fast-growing tech debt | Wrong CUDA/CPU fallback logic, missing edge case (empty audio, no mic), race on shared recorder/transcriber state, deprecated Qt API |
| **P2 — Nice-to-have** | Code smells, minor perf, style | Duplicated code, magic numbers, an over-long method, a heavy import that could be lazier |

## Workflow

```
Implement → Run automated checks → Fix failures →
Code Review (all categories) → Fix P0/P1 → Re-check if needed →
Regression & Complexity QA →
Unresolved findings → BACKLOG.md →
Learnings/context → MEMORY.md / SCRATCHPAD.md →
UI Review (if UI changed) →
Commit
```

### Error Recovery
- **Automated checks fail and fix is unclear:** Document the failure, inform the user, do NOT commit. Suggest possible causes.
- **Review finds issue outside current scope:** Log to BACKLOG.md with context, do not fix unless trivial.
- **Circular fix loop (fix breaks something else):** After 2nd iteration → inform user. After 3rd → invoke `.claude/skills/stuck/SKILL.md` — the 4th attempt without user input is forbidden.

## Automated Checks

This project has **no linter, formatter, or type checker configured.** Run the same checks CI runs, in this order:

```bash
python -m compileall -q src scripts                 # syntax check every source file
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"   # headless Qt UI smoke
# Full packaging self-test (only when all runtime deps are installed):
python -m listen_to_me --selftest
```

Do NOT add ruff/black/mypy/pytest to make a check pass — that is a tooling change requiring user approval.

### Test execution constraints (autonomy + zero-cost)

Apps in this workspace are built and verified by AI agents end-to-end. Any tests must be:

- **Agent-runnable without setup** — no real microphone, no GPU, no credentials, no interactive login.
- **Zero-cost** — no real API calls (paid LLMs, GitHub), no Whisper model downloads in the default check path.
- **Deterministic** — fake clocks/random; mock `sounddevice`, `pynput`, `requests`, `faster_whisper` at the boundary.
- **Self-contained** — runnable on every change as part of the standard checks (extend `selftest.py`'s Qt-free logic where possible).

Real-service smoke/E2E tests only on explicit user request, never as a default automated check.

## Review Scope

### Default: Diff-based review
- Review is based on changed files (diff).
- Only changed and directly affected files are read.

### Full-read review (when needed)
- New files are always read completely.
- Threading-sensitive changes (`app.py`, workers, `transcriber.py`, `hotkeys.py`, `integrations.py`): also check the callers/callees for main-thread vs worker-thread correctness.
- Security-relevant changes (`injector.py`, `assistant.py`, `updater.py`, `config.py`): also check adjacent files.
- On explicit user request.

### Large-scale changes (>30 changed files)
- Group by change type (refactoring, feature, config etc.).
- P0 categories for all files.
- P1/P2 only for feature-relevant files, rest by sampling.

## Review Categories

Ordered by priority.

### P0 — Critical (always fix immediately)

| # | Category | What to check |
|---|----------|---------------|
| 1 | **Security** | Command/shell injection, unsafe `subprocess`, secrets in logs/commits, unsafe deserialization, untrusted input to the injector, updater download/verify integrity |
| 2 | **Bugs & Logic Errors** | **Cross-thread Qt access from a worker thread** (must go through `App.post`), unhandled exception reaching the Qt main loop, null/None deref, race conditions on `Recorder`/`Transcriber`/`Hotkeys` shared state, wrong CUDA↔CPU fallback, unclosed audio stream, deadlock between `_lock`/`_use_lock` |

### P1 — Important (fix by default, defer only if disproportionate effort)

| # | Category | What to check |
|---|----------|---------------|
| 3 | **Edge Cases** | Empty/too-short audio, no microphone, no GPU, no network (assistant/updater), clipboard access denied, missed hotkey release (hold mode), multi-monitor overlay placement, non-ASCII paths |
| 4 | **Typing & Type Safety** | Correct type hints, `X | None` handled, no silent `Any`, config value types match `DEFAULTS` |
| 5 | **Modern Coding Standards** | Idiomatic PySide6/Qt, no deprecated Qt APIs, `from __future__ import annotations` present, lazy heavy imports preserved, Qt-free modules stay Qt-free, DRY/KISS/SRP |

### P2 — Contextual (review when relevant, defer freely)

| # | Category | What to check |
|---|----------|---------------|
| 6 | **Code Smells** | Duplicated code, dead code, god methods (watch `settings_ui.py`/`app.py`), long parameter lists, magic numbers |
| 7 | **Performance** | Redundant FFT/level work while overlay hidden, O(n²) buffer snapshots on long recordings, unnecessary model reloads, blocking work on the main thread |
| 8 | **Readability & Maintainability** | Clear naming, docstrings explaining *why*, consistent style, logical organization |

## Review Execution

1. **Re-read every changed file** with the Read tool — completely, not from memory. New files in full.
2. Evaluate each file against all categories (P0 first, then P1, then P2 where relevant).
3. Fix findings inline where possible.
4. Present results:

```
### Code Review Results

| # | Category | Sev | Status | Finding | Action |
|---|----------|-----|--------|---------|--------|
| 1 | Bugs & Logic | P0 | ⚠️ Fixed | Worker touched tray directly | Routed through App.post |
| 2 | Security | P0 | ✅ Pass | — | — |
| 3 | Edge Cases | P1 | ✅ Pass | — | — |

Summary: X categories checked | Y fixed | Z deferred → Backlog
```

**Status:** ✅ Pass | ⚠️ Fixed | ❌ Blocked (needs user input) | 💡 Deferred → Backlog

## Fixing Rules

| Severity | Action |
|----------|--------|
| P0 findings | Fix immediately, always |
| P1 findings | Fix by default. Defer only if effort is clearly disproportionate — document reasoning in Backlog |
| P2 findings | Fix if trivial (<5 min). Otherwise defer to Backlog |

## Regression & Complexity QA

After all review fixes are applied, re-read the full implementation one more time:

| Check | What to look for |
|-------|-----------------|
| **Regressions** | Did a fix break existing behavior? Changed return values, removed fallbacks, altered state transitions? |
| **Unnecessary complexity** | Did the implementation add indirection or branching that isn't needed? |
| **Consistency** | Do the changes fit the patterns in surrounding code (threading, lazy imports, config access)? |

Rules:
- Re-read every changed file again (not from memory).
- If this pass finds issues, fix them and re-run automated checks. Do NOT loop more than once.

## UI Review (only when UI code changed)

- **Threading:** any Qt object touched only on the main thread? Worker → `App.post`/`App.notify`?
- **Light/dark theme:** does it render in both palettes (`theme.py` follows the OS)?
- **Focus:** overlay/bubble windows must not steal keyboard focus (`WindowDoesNotAcceptFocus` / `WA_ShowWithoutActivating`).
- **Consistency:** matches the settings-window card/sidebar patterns; every new option has a tooltip.
- **Headless:** does `gui_smoke` still construct the UI without error?

## Subagent Delegation

For isolated, clearly bounded subtasks. Pick the matching `subagent_type` instead of always defaulting to `general-purpose`.

| Task                              | When to delegate                | Recommended `subagent_type` |
|-----------------------------------|--------------------------------|-----------------------------|
| **Locate code / find symbols**    | Search across >3 paths or unknown location | `Explore` (read-only, fast) |
| **Plan refactoring/feature**      | Non-trivial, >3 files affected, architectural choice | `Plan` |
| **Write tests / selftest checks** | >3 checks for a feature        | `general-purpose` |
| **Doc updates**                   | >2 documentation files         | `general-purpose` |
| **Refactoring chunks**            | Independent subtasks of larger refactoring | `general-purpose` |
| **Independent code review**       | Second-opinion on diff         | `general-purpose` |
| **Q about Claude Code/SDK/API**   | "Can Claude do X?", hooks, MCP, SDK questions | `claude-code-guide` |

## Subagent Selection Rules

- **Use `Explore` for read-only search.** Specify breadth: `quick`, `medium`, `very thorough`. Do NOT use for code review — it reads excerpts, will miss content past its window.
- **Use `Plan` before non-trivial implementation.** Then act on the plan in main thread, or hand it to `general-purpose`.
- **Use `general-purpose` for write+execute** tasks. Default for "do this work" delegations.
- **Use `claude-code-guide` for tooling questions** about Claude Code itself.
- **Parallelize independent work** — multiple Agent calls in one message when no dependencies exist.
- **Prefer direct tools when target is known** — `Read` for known path, `grep` for known symbol.
- **Pass full context** — subagents have no conversation history.
- **Trust but verify** — inspect diffs after write-capable subagents finish.

The main agent retains responsibility for the review process itself.

## Commit Gate

Only commit when:
- [ ] Automated checks pass (`compileall` + Qt smoke)
- [ ] All P0/P1 findings are fixed (or explicitly deferred with reasoning)
- [ ] Deferred findings are logged in BACKLOG.md
- [ ] Learnings/context captured in MEMORY.md or SCRATCHPAD.md (if applicable)
- [ ] Documentation updated if needed (CLAUDE.md / README.md / config table)
- [ ] Commit message follows project's Git Conventions (imperative subject)
- [ ] UI review done (if UI changed)
