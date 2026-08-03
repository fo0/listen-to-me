# ADR-0003: Routine merge pre-approval is allowlist-gated, not self-declared

- **Status:** Superseded by ADR-0004
- **Date:** 2026-07-27
- **Decider(s):** user + agent
- **Tags:** security, process, deployment

> Superseded on 2026-08-02 by [ADR-0004](0004-agent-merges-require-an-explicit-user-command.md):
> the exception was dropped entirely and `agent_docs/authorized_routines.md` deleted. The text
> below is kept as history — its references to that file no longer resolve.

## Context

`CLAUDE.md → Deployment` grants an exception to the "agent does not merge without an explicit user command" rule: a session running an owner-authorized routine counts as such a command, so its merges — and any pipeline they trigger — are pre-approved.

As originally written the exception was **self-declared**: a session qualified because its own kickoff prompt said it was a routine. Prompt text arrives from outside the repository. A scheduled trigger someone else edited, an instruction injected through an issue or PR body, or a pasted task description can all assert routine status, and would thereby inherit merge rights on a repo whose release workflow runs with `contents: write`. A claim in the prompt is not evidence of authorization.

## Decision

We will gate the exception on an allowlist committed to `main`: `agent_docs/authorized_routines.md`. Pre-approval applies only when the session's Claude Code Remote trigger id — resolved from session/trigger metadata, never from the prompt — matches a row in that file **and** the change set is non-destructive **and** verification passed.

The behavior is **fail closed**: an unlisted id, an unknown id, or an unreadable file means the session is not authorized. It does the work, opens the PR, and leaves the merge to an explicit interactive user command. The allowlist ships empty, so the exception is off until the owner adds a row in a normal reviewed commit.

## Consequences

### Positive
- Prompt text alone can no longer mint merge rights; adding an authorization requires a reviewed change to `main`.
- Revocation is a one-line commit.
- The rule is written where an attacker-supplied prompt cannot reach it, and it is mirrored in `.claude/skills/pr/SKILL.md → /pr merge`.

### Negative / Trade-offs
- Genuine routines do not merge until the owner registers them — the default state is more manual than before.
- The check depends on the agent resolving a trigger id from session metadata; if that is unavailable the answer is "not authorized", which is the safe but occasionally inconvenient outcome.

### Neutral
- Destructive change sets (data migration, history rewrite, repo-settings change) stay gated regardless of what the allowlist says.

## Alternatives Considered

- **Keep the self-declared exception** — rejected: the trust anchor sits in attacker-reachable text.
- **Allow any routine but restrict what it may merge** — rejected: the blast radius of a release-publishing workflow makes "restricted merge" hard to define and easy to get wrong.
- **Drop the exception entirely** — rejected: unattended maintenance routines are useful; the owner should be able to opt specific ones in.

## References

- `agent_docs/authorized_routines.md`, `agent_docs/deployment.md`
- `.claude/skills/pr/SKILL.md → /pr merge`
- Issue #21
