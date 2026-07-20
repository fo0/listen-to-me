---
name: review
description: "Use when the user wants a code review of the current diff or recent changes. Triggered by /review, 'review this', 'review the diff', 'do a review', 'review my changes'. Wraps the workflow in agent_docs/review_process.md — runs automated checks, evaluates all P0/P1/P2 categories, fixes findings inline, writes deferred items to BACKLOG.md."
---

# Review — Diff / Recent-Changes Code Review

## When to Use

- User says "/review", "review this", "review the diff", "review my changes", "do a review"
- After implementing a feature — done-skill does NOT run review automatically (it stays predictable). User invokes review skill explicitly when they want it.

## Source of Truth

The full review workflow lives in `agent_docs/review_process.md`. **Do not duplicate it here.** This skill is a thin invocation wrapper:

1. Read `agent_docs/review_process.md` to load the current rules (severity definitions, categories, fixing rules, commit gate).
2. Determine review scope: diff vs full-read vs large-scale (>30 changed files).
3. Execute the workflow as defined in the process file.
4. Produce the standard `### Code Review Results` table.
5. Write deferred findings to `BACKLOG.md` per `agent_docs/backlog_process.md`.

## Workflow

```
1. git status + git diff                           → identify changed files
2. Read agent_docs/review_process.md               → load rules
3. Run automated checks (compileall + Qt smoke) per CLAUDE.md
4. Re-read every changed file completely
5. Evaluate against P0/P1/P2 categories (esp. cross-thread Qt, lazy imports, fail-soft)
6. Fix P0/P1 inline; defer P2 only if non-trivial
7. Regression & complexity QA pass
8. UI review (only if UI changed)
9. Output standard Code Review Results table
10. Write deferred findings to BACKLOG.md
```

## Rules

- **Do not run automatically.** This skill is on-demand only. Done-skill must NOT trigger it.
- **No security-deep-dive here** — for OWASP / injection / secrets / auth focus, use the separate `security-review` skill. Generic review still covers Security at the P0 level per `review_process.md`.
- **Output format is fixed** — must produce the table defined in `review_process.md`.
- **Re-read files**, never review from memory.

## Report

Use the exact format from `review_process.md`:

```
### Code Review Results

| # | Category | Sev | Status | Finding | Action |
|---|----------|-----|--------|---------|--------|
| ... |

Summary: X categories checked | Y fixed | Z deferred → Backlog
```

Append a one-line skill footer:
```
🔍 review skill — full process: agent_docs/review_process.md
```
