# Memory Process

Project knowledge is split into two files with different lifespans:

| File            | Purpose                                                                | Lifespan                  | Max Size                                       |
| --------------- | ---------------------------------------------------------------------- | ------------------------- | ---------------------------------------------- |
| `MEMORY.md`     | Long-term memory — stable knowledge that persists across many sessions | Long-lived (weeks/months) | target **~8,000 chars**, archive at **16,000** |
| `SCRATCHPAD.md` | Short-term memory — temporary context for current work                 | Ephemeral (hours/days)    | target **~4,000 chars**, archive at **8,000**  |

> **Unit:** chars, measured with `wc -c` — both files load at session start, so their size is a per-session cost. Full budget table, archive procedure and format: `agent_docs/context_budget.md`. The Tier-1 budget guard in `.claude/settings.json` checks them (and `CLAUDE.md`) after every Edit/Write.

## When to use which file

### → MEMORY.md (long-term)

- **Architecture decisions & reasoning** — Why was X chosen over Y? **For non-trivial structured decisions, prefer writing an ADR in `docs/adr/` (see `agent_docs/adr_template.md`).** Use MEMORY.md only for short, loose decision notes that don't justify a full ADR.
- **Gotchas & pitfalls** — e.g. cross-thread Qt access, missed hotkey releases, PyInstaller hidden-import surprises, CUDA library failures surfacing at inference not load.
- **Failed approaches** — What was tried and why it didn't work.
- **External dependencies** — faster-whisper/CTranslate2 quirks, pynput per-OS behavior, sounddevice/PortAudio gotchas, Qt platform differences.
- **User preferences** — How the user wants things solved (style, priorities, what to avoid).
- **Non-obvious couplings** — e.g. `requirements.txt` ↔ `pyproject.toml` ↔ PyInstaller `--collect-all` must stay in sync.

### → docs/adr/ (structured architecture decisions)

Use ADRs (not MEMORY.md) when ALL of these apply:

- Decision affects more than one module / file area.
- Reverting later would cost > 1 hour.
- A reasonable engineer might disagree with the choice.
- The decision is non-obvious from the code.

See `agent_docs/adr_template.md` for format and lifecycle (Proposed / Accepted / Deprecated / Superseded). ADRs are immutable once Accepted.

### → SCRATCHPAD.md (short-term)

- **Current working context** — What you're doing right now, next steps.
- **Open questions** — Things to ask or verify.
- **Quick research notes** — Findings from web searches, version checks, etc.
- **Multi-session task state** — Progress on tasks spanning 2–3 sessions.
- **Temporary workarounds** — Things that need to be revisited soon.
- **Debug notes** — Observations from troubleshooting (discard once resolved).

### → Neither (don't store)

- What's already in CLAUDE.md (technical reference)
- What's already in README.md (user docs)
- What's already in BACKLOG.md (open findings)

## Rules

### Both files

1. **Write without being asked** — Store knowledge as it emerges. No user prompt needed.
2. **Read both at session start** — Restore context from previous sessions.
3. **No duplication** — Between files or with CLAUDE.md/README.md/BACKLOG.md.

### MEMORY.md specific

4. **Keep compact** — Each entry is a short, concise paragraph. Target ~8,000 chars; at 16,000 run the archive procedure in `agent_docs/context_budget.md`.
5. **Archive, never delete** — Obsolete entries move to `agent_docs/memory_archive/`, real decisions get promoted to `docs/adr/`. Deleting knowledge to hit a budget is the one thing this file must not do.
6. **Failed Approaches remain** as long as the alternative exists.

### SCRATCHPAD.md specific

7. **Aggressively clean up** — Delete entries as soon as they're resolved or no longer relevant.
8. **Target ~4,000 chars** — Past 8,000, completed items haven't been cleaned: delete resolved entries, promote 3+-session survivors to MEMORY.md, archive the stale remainder (`agent_docs/context_budget.md`).
9. **Promote if long-lived** — If a SCRATCHPAD entry survives 3+ sessions, consider moving it to MEMORY.md (it's probably stable knowledge, not temporary context).

## MEMORY.md Format

```markdown
# Memory — Long-Term

Stable project knowledge. **Read at session start.**

## Architecture Decisions

### {Decision}

- **Date:** YYYY-MM-DD
- **Context:** {Why the decision came up}
- **Decision:** {What was decided}
- **Reason:** {Why this option}

## Gotchas & Pitfalls

- **{Short title}** — {Description, what happens and how to avoid it} ({date})

## Failed Approaches

- **{What was tried}** — {Why it didn't work, what was done instead} ({date})

## External Dependencies

- **{Library/API/Service}** — {Quirk, bug, workaround} ({date})

## User Preferences

- **{Preference}** — {How the user wants things solved} ({date})
```

## SCRATCHPAD.md Format

```markdown
# Scratchpad — Short-Term

Temporary working context. **Clean up aggressively — delete when resolved.**

## Current Work

- **{Task/Topic}** — {What's being done, current state, next steps} ({date})

## Open Questions

- **{Question}** — {Context, who/what to check} ({date})

## Research Notes

- **{Topic}** — {Findings, version info, links} ({date})

## Temporary Notes

- **{Note}** — {Observation, debug finding, etc.} ({date})
```

## Size monitoring

Both files are budgeted (target 8,000 / 4,000 chars; act at 16,000 / 8,000) because both load at session start. Over budget is fixed by **archiving, not deleting** — real decisions become ADRs, the rest moves to `agent_docs/memory_archive/` with an index line left behind in `MEMORY.md → ## Archive`. Procedure + archive format: `agent_docs/context_budget.md`.

<!-- Generated by claude-code-optimizer v1.37.0 -->
