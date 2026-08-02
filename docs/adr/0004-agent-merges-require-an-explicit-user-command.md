# ADR-0004: Agent merges and releases require an explicit interactive user command

- **Status:** Accepted — supersedes ADR-0003
- **Date:** 2026-08-02
- **Decider(s):** user
- **Tags:** security, process, deployment

## Context

ADR-0003 kept the "routine" merge exception alive but gated it: pre-approval applied only when the session's Claude Code Remote trigger id matched a row in `agent_docs/authorized_routines.md`, a file committed to `main` so prompt text could not add an entry to itself.

The gate worked, but the feature behind it never did anything. The allowlist never left its empty default state, so the exception was never once in force, and the trigger id it hinges on is not reliably resolvable from session metadata — the one path that would activate it is unverifiable in practice. What the construct did produce was cost: four documents (`CLAUDE.md`, `agent_docs/deployment.md`, `agent_docs/authorized_routines.md`, `.claude/skills/pr/SKILL.md`) restated the same fail-closed rule in four slightly different wordings, they drifted apart as each was edited on its own, and every session paid context for a branch that always resolved to "not authorized".

## Decision

We will drop the exception entirely. Merging a pull request and dispatching the release workflow each require an **explicit interactive user command**; nothing else grants them — not a schedule, not a trigger, not a prompt however confidently it asserts authorization. `agent_docs/authorized_routines.md` is deleted, and every doc that referenced it now states the single unconditional rule.

An unattended or scheduled session does the work, opens the PR, and stops there.

## Consequences

### Positive
- One unconditional sentence replaces a four-file conditional; there is no longer a variant of the rule that can drift out of sync with the others.
- The security property of ADR-0003 is preserved and strengthened — the safe outcome is now the only outcome, not the default branch of a check.
- Less context spent per session on a rule that never fired.

### Negative / Trade-offs
- Genuinely useful unattended maintenance (e.g. a dependency routine that could merge its own green patch bump) now always waits for a human. Accepted: the release workflow runs with `contents: write` and publishes the exe the in-app updater hands to users.
- Re-enabling pre-approval later means designing it again from scratch rather than adding a row to a file.

### Neutral
- Nothing else about agent scope changes: pushing to feature branches and opening/updating PRs stay unattended-friendly, as do the pre-approved Claude Code Remote trigger tools in `.claude/settings.json`.
- ADR-0003 stays in the repo as history; its references to the deleted allowlist file are historical, not current.

## Alternatives Considered

- **Keep the allowlist and just fix the wording drift** — rejected: it keeps four restatements of a rule that has never applied, and the trigger-id lookup it depends on stays unverifiable.
- **Keep the file but empty and undocumented** — rejected: a trust anchor nobody explains is worse than none; the next reader would either wire it back up or trip over it.
- **Narrow pre-approval to non-release merges** — rejected: every merge to `main` is one dispatch away from a published build, so "non-release merge" is not a boundary worth defending in prose.

## References

- Supersedes `docs/adr/0003-routine-merge-pre-approval-is-allowlist-gated.md`
- `CLAUDE.md → Deployment`, `agent_docs/deployment.md`
- `.claude/skills/pr/SKILL.md → /pr merge`
- Issue #21
