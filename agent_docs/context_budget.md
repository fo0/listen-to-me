# Context Budget

Three files load into context every session: `CLAUDE.md` on every turn, `MEMORY.md` and `SCRATCHPAD.md` at session start. Their size is paid by every task in this repo, forever. Everything under `agent_docs/`, `.claude/skills/` and `docs/adr/` is read on demand and has **no budget** — which is what makes offloading into them free.

| File            | Target         | Offload at | Hard limit |
| --------------- | -------------- | ---------- | ---------- |
| `CLAUDE.md`     | ≤ 15,000 chars | 20,000     | 40,000     |
| `MEMORY.md`     | ≤ 8,000 chars  | 16,000     | 24,000     |
| `SCRATCHPAD.md` | ≤ 4,000 chars  | 8,000      | 12,000     |

Measure: `wc -c CLAUDE.md MEMORY.md SCRATCHPAD.md`. The `PostToolUse` budget guard in `.claude/settings.json` checks all three after every Edit/Write and reports which one is over.

## The one rule: offload, never delete

Over budget is **never** solved by deleting content or summarizing detail away. It is solved by moving content to an on-demand file and leaving a one-line pointer. A deleted gotcha costs a future session a debugging round; a moved gotcha costs it one `grep`. When in doubt, move it.

The exception: content that duplicates what the code already states. That is deleted, not moved — the code is the source of truth.

## The other half: files that never get measured

A budget over three files says nothing about the fourth, fifth and twentieth. The `SUMMARY.md` / `NOTES.md` / `IMPLEMENTATION_PLAN.md` layer an agent leaves behind is individually tiny and permanently under every threshold, so no guard ever fires — and a later session greps a root full of half-true snapshots that no rule keeps current. Each of those has a documented home already: an architecture decision → `docs/adr/`, a repo gotcha → `MEMORY.md`, working notes → `SCRATCHPAD.md`, an unfixed finding → `BACKLOG.md`, a process → `agent_docs/`, a research write-up → `docs/research/`.

To have that enforced at write time instead of remembered, activate the **stray doc-file warning** from `agent_docs/hooks_catalog.md` (Tier 2) — it names the right home at the moment the agent is about to write past it, without blocking a file the project genuinely asked for.

## CLAUDE.md — offload ladder

Work down this list, re-measuring after each step. Stop as soon as the file is back under target.

| #   | Move out of CLAUDE.md                                               | To                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Pointer left behind                                                                    |
| --- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 1   | API/endpoint/event/protocol tables beyond a one-line style summary  | `agent_docs/api-reference.md`                                                                                                                                                                                                                                                                                                                                                                                                                                           | `Full API reference: agent_docs/api-reference.md`                                      |
| 2   | Env vars beyond the 3–5 the agent must know; secret-location tables | `agent_docs/env-vars.md`                                                                                                                                                                                                                                                                                                                                                                                                                                                | `Full list: agent_docs/env-vars.md`                                                    |
| 3   | Key Patterns beyond the top 5                                       | `agent_docs/key-patterns.md`                                                                                                                                                                                                                                                                                                                                                                                                                                            | `More patterns: agent_docs/key-patterns.md`                                            |
| 4   | Deployment detail beyond trigger + pipeline path + agent scope      | `agent_docs/deployment.md`                                                                                                                                                                                                                                                                                                                                                                                                                                              | `Deployment detail: agent_docs/deployment.md`                                          |
| 5   | Project structure below the second directory level                  | `agent_docs/project_structure.md`                                                                                                                                                                                                                                                                                                                                                                                                                                       | `Full tree: agent_docs/project_structure.md`                                           |
| 6   | Testing detail beyond framework + run command + layout              | `agent_docs/testing.md` (constraints already live in `review_process.md`)                                                                                                                                                                                                                                                                                                                                                                                               | `Testing detail: agent_docs/testing.md`                                                |
| 7   | Architecture rationale / "why we chose X" prose                     | a new ADR in `docs/adr/`                                                                                                                                                                                                                                                                                                                                                                                                                                                | `See ADR-NNNN`                                                                         |
| 8   | Development Notes: setup hints, quirks, history                     | `MEMORY.md` (stable) or `SCRATCHPAD.md` (temporary)                                                                                                                                                                                                                                                                                                                                                                                                                     | drop the section if it empties                                                         |
| 9   | Coding conventions beyond ~8 bullets                                | repo-wide ones → `agent_docs/coding_conventions.md`. Conventions that hold for **one subtree only** → `.claude/rules/{topic}.md` with `paths:` frontmatter naming that subtree's globs: Claude Code loads such a rule only while a matching file is being read, so it costs no context anywhere else and does not depend on an agent remembering to open a doc. A rule file **without** `paths:` loads every session like CLAUDE.md itself — never write one to offload | `Full conventions: agent_docs/coding_conventions.md` · `Subtree rules: .claude/rules/` |
| 10  | Still over → the largest remaining non-spine section                | `agent_docs/{section-slug}.md`                                                                                                                                                                                                                                                                                                                                                                                                                                          | one-line pointer                                                                       |

**Never offload — the spine the agent needs every turn:** Session Start Read Order · Workflow Triggers · Output Languages · Commands · Git Conventions · Documentation Rules incl. this budget pointer · the `<!-- Generated by claude-code-optimizer -->` footer.

**Feature documentation is not an offload candidate — it is a mistake.** CLAUDE.md says _how to work here_, not _what each feature does_. If a section documents behavior, delete it and let the agent read the code.

## MEMORY.md — archive, don't trim

When `MEMORY.md` passes 16,000 chars:

1. **Promote first.** Entries that are real architecture decisions (affect more than one module, costly to reverse, debatable, non-obvious) → write an ADR in `docs/adr/` per `agent_docs/adr_template.md`, then replace the entry with a one-line `See ADR-NNNN`.
2. **Archive by relevance, not by age alone.** Move entries whose subject no longer exists — deleted module, replaced library, superseded decision, resolved-for-good gotcha — into `agent_docs/memory_archive/YYYY-MM.md` (`YYYY-MM` = the month you archive in; append if the file exists). Keep the original section headings and dates.
3. **Keep unconditionally:** everything under `## User Preferences`; gotchas about files that still exist; failed approaches whose alternative is still in use.
4. **Index what you moved.** Add/refresh the `## Archive` section in `MEMORY.md` — one line per archive file saying what is in it, so the next session greps instead of re-deriving.
5. **Never delete an entry to fit.** If it looks worthless, archive it.

## SCRATCHPAD.md — clean first, then archive

1. Delete resolved entries. Scratchpad is ephemeral by contract — this is the intended cleanup, not data loss.
2. Promote anything that has survived 3+ sessions to `MEMORY.md` (it is stable knowledge, not working context).
3. Only what is left — unresolved but stale — goes to `agent_docs/memory_archive/scratchpad-YYYY-MM.md`.

## Archive format

```markdown
# Memory Archive — {YYYY-MM}

Archived from MEMORY.md on {YYYY-MM-DD} because it exceeded its context budget.
Still valid knowledge — grep here before concluding something was never tried.

## Architecture Decisions

{moved entries, verbatim, original dates intact}

## Gotchas & Pitfalls

{...}
```

And in `MEMORY.md`:

```markdown
## Archive

- `agent_docs/memory_archive/2026-07.md` — Qt/Windows UI gotchas, autostart + single-instance history (archived 2026-07-30)
```

## When to run this

- The budget guard fires after an Edit/Write → offload in the same session, don't defer it.
- At session start, if a budgeted file is visibly over.
- On every optimizer run — its self-validation enforces the budgets and reports what moved.

<!-- Generated by claude-code-optimizer v1.37.0 -->
