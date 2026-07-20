# Memory Process

Project knowledge is split into two files with different lifespans:

| File          | Purpose                                                                | Lifespan                  | Max Size       |
|---------------|------------------------------------------------------------------------|---------------------------|----------------|
| `MEMORY.md`   | Long-term memory — stable knowledge that persists across many sessions | Long-lived (weeks/months) | **~16,000 chars** (~200 lines, ~4k tokens) |
| `SCRATCHPAD.md` | Short-term memory — temporary context for current work               | Ephemeral (hours/days)    | **~8,000 chars** (~100 lines, ~2k tokens)  |

> **Unit:** primary limit is **chars** (matches CLAUDE.md's 40,000 char limit for consistency with Claude's context-window cost model). Line + token estimates are illustrative — the hook in `agent_docs/hooks_catalog.md` checks chars.

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
4. **Keep compact** — Each entry is a short, concise paragraph. Max ~16,000 chars.
5. **Remove only when fundamentally obsolete** — Architecture decisions stay unless the code changes fundamentally.
6. **Failed Approaches remain** as long as the alternative exists.

### SCRATCHPAD.md specific
7. **Aggressively clean up** — Delete entries as soon as they're resolved or no longer relevant.
8. **Max ~8,000 chars** — If it grows beyond this, completed items haven't been cleaned.
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
- **MEMORY.md > 16,000 chars** → Remove oldest entries that are no longer relevant. Architecture decisions and active gotchas should stay.
- **SCRATCHPAD.md > 8,000 chars** → Completed items haven't been cleaned. Delete resolved entries first, then promote long-lived entries to MEMORY.md.
