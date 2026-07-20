# ADR Template

Copy this template to `docs/adr/000X-<short-kebab-title>.md` when recording a new decision. Numbering is monotonic — pick the next free integer.

---

```markdown
# ADR-NNNN: Short title in title case

- **Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNNN
- **Date:** YYYY-MM-DD
- **Decider(s):** user / agent / both
- **Tags:** area, e.g. auth, storage, build, deploy

## Context

What's the situation? What forces are at play? What constraints? Keep it 1–3 short paragraphs. No solution yet.

## Decision

One paragraph stating the chosen path, in active voice. "We will X."

## Consequences

### Positive
- Benefit 1
- Benefit 2

### Negative / Trade-offs
- Cost 1
- Cost 2

### Neutral
- Side effect that's neither good nor bad but worth noting

## Alternatives Considered

- **Alternative A** — rejected because reason.
- **Alternative B** — rejected because reason.

## References

- Link to relevant code / PR / issue / external doc, if any.
```

---

## When to write an ADR

Write one when **any** of these is true:

- The decision affects more than one module / file area.
- Reverting the decision later would cost more than 1 hour of work.
- A reasonable engineer might disagree with the choice.
- The decision is non-obvious from the code (would surprise a reader).

Don't write one for trivial choices (variable naming, single-function refactors, formatting).

## Numbering

`docs/adr/0001-...md` through `0999-...md`. Zero-padded to 4 digits. Pick the next free number — never reuse.

## Lifecycle

- **Proposed** → ADR drafted, decision pending.
- **Accepted** → in force.
- **Deprecated** → no longer in force, but kept for history.
- **Superseded by ADR-NNNN** → replaced; both ADRs stay in the repo, linked.

Never delete an ADR. History matters. Use `Status: Superseded` instead.
