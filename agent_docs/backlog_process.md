# Backlog Process

Review findings that were not immediately fixed are tracked in `BACKLOG.md` in the project root.

## Rules

1. **Backlog is memory, not a task queue** — items are ONLY worked on upon explicit user request. Never work through the backlog independently.
2. New entries go under `## Open`.
3. No duplicates — check if finding already exists before adding.
4. Done items move from `## Open` to `## Done` with completion date.
5. Stale entries — if the referenced function/component changed through other work, check if the finding is still relevant. Update or remove if obsolete.
6. Source traceability — every entry links back to the task/feature where it was found.
7. Escalation — P2 findings that block 3+ different features get escalated to P1.

## BACKLOG.md Format

```markdown
# Backlog

Review findings not immediately fixed. **Only work on these upon explicit request.**

## Open

| # | Date | Category | Sev | Location | Finding | Status | Source |
|---|------|----------|-----|----------|---------|--------|--------|
| 1 | 2026-07-19 | Code Smells | P2 | settings_ui.py → SettingsWindow | 1300-line file, split into per-page modules | Deferred | Optimizer setup |

## Done

| # | Date | Done | Category | Location | Finding |
|---|------|------|----------|----------|---------|
| 1 | 2026-07-01 | 2026-07-10 | Bugs & Logic | transcriber.py → _maybe_force_cpu | CPU fallback fired on transient OOM |
```

### Location Format
Use `File → Function/Component` instead of line numbers. Line numbers go stale after every commit.

### Status Values
- **Deferred** — Recognized as valid, postponed intentionally (reasoning in Finding or Source)
- **Accepted** — Known limitation, accepted as-is for now
- **Escalated** — Upgraded from P2 to P1 due to repeated impact
