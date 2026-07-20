# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-07-19
- **Decider(s):** project setup
- **Tags:** process

## Context

This project is built and maintained primarily by AI agents across many sessions. Agents lose conversation context between sessions, and `MEMORY.md` is intentionally compact (~16k chars) — it can't hold every architecture decision in detail. Without a structured decision log, rationale gets lost: future agents end up either re-deriving the same conclusions or, worse, reversing past decisions because the reasoning is no longer visible.

## Decision

We will record significant architecture decisions as ADRs in `docs/adr/`, using the template at `agent_docs/adr_template.md`. Triggers for writing an ADR are listed in the template. ADRs are immutable once Accepted; they may be Deprecated or Superseded but never deleted.

## Consequences

### Positive
- Decisions outlive sessions and memory trims.
- New agents (and humans) can grep `docs/adr/` to understand "why is it built this way".
- Reversing a past decision becomes a deliberate act (writing a superseding ADR), not an accidental drift.

### Negative / Trade-offs
- Slight overhead per non-trivial decision (~5–10 minutes to write a focused ADR).
- Risk of ADR rot if the practice isn't followed — mitigated by including ADR adherence as a review consideration when relevant.

### Neutral
- ADRs and `MEMORY.md` overlap on architecture decisions. Rule: structured architecture decisions go to ADRs; loose user preferences and gotchas stay in `MEMORY.md`.

## Alternatives Considered

- **Keep everything in MEMORY.md** — rejected: doesn't scale, gets trimmed, no per-decision granularity.
- **GitHub Discussions / Wiki** — rejected: lives outside the repo, agents won't reliably read it, harder to grep.
- **Inline code comments** — rejected: code-local, won't capture cross-module decisions.

## References

- Template: `agent_docs/adr_template.md`
- Memory rules: `agent_docs/memory_process.md`
