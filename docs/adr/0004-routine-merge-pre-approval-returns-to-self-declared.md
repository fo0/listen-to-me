# ADR-0004: Routine merge pre-approval returns to self-declared

- **Status:** Supersedes ADR-0003
- **Date:** 2026-07-31
- **Decider(s):** user
- **Tags:** security, process, deployment

## Context

ADR-0003 gated the routine merge exception on an allowlist committed to `main`
(`agent_docs/authorized_routines.md`): pre-approval applied only when the
session's Claude Code Remote trigger id matched a row in that file. The
allowlist shipped empty, so the exception was off by default.

Two things became clear in practice:

1. **The gate never opens on its own.** The 2026-07-30 optimizer routine ran
   here and in 18 sibling repositories. It completed the work everywhere; only
   this repo stopped short of the merge, which the owner then performed by hand
   13 minutes later. Every future routine run would repeat that.
2. **The check has no input to work with.** Step 1 of the procedure is "resolve
   the session's trigger id from session/trigger metadata". The Claude Code
   Remote environment exposes `CLAUDE_CODE_SESSION_ID` and
   `CLAUDE_CODE_REMOTE_SESSION_ID`, both new on every run, and no trigger id at
   all. Registering a row would therefore not have changed the outcome — the
   check would still fail closed for want of an id to match.

So the mechanism does not currently distinguish an authorized routine from an
unauthorized one; it declines both. The owner has decided the manual merge is
not worth that, and that this repository should behave like the other 18.

## Decision

Remove the allowlist gate. The routine exception returns to the wording used
across the sibling repositories: a session running an owner-authorized routine
counts as an explicit user command, and its merges are pre-approved — including
any pipeline they trigger — provided the change set is non-destructive
(additive; no data migration, no history rewrite, no repo-settings change) and
verification passed.

`agent_docs/authorized_routines.md` is deleted; it was the trust anchor for a
check that no longer exists, and keeping it would read as an active control.
Its content remains in git history.

Destructive change sets stay gated, unchanged. Release dispatch
(`workflow_dispatch` on `release.yml`) still requires an explicit user command
and is **not** covered by the routine exception.

## Consequences

### Positive
- Routine runs complete unattended here, as they already do in the other 18 repositories.
- One consistent rule across the fleet; no per-repo special case to remember.

### Negative / Trade-offs
- **This re-opens what ADR-0003 and Issue #21 closed.** The trust anchor moves
  back into prompt text, which reaches a session from outside the repository —
  an edited trigger, an instruction injected through an issue or PR body, or a
  pasted task description can again assert routine status and inherit merge
  rights.
- The blast radius is what made this repo special in the first place:
  `release.yml` runs with `contents: write` and publishes the exe that the
  in-app updater hands to users. A merge obtained under a false routine claim
  can reach end-user machines through that path.
- Mitigation is now limited to what the sibling repos rely on: release dispatch
  stays manual, destructive changes stay gated, and CI must be green.

### Neutral
- Nothing in the release pipeline, the SHA pinning rule (#22) or the updater's
  TLS enforcement (ADR-0002) changes.

## Alternatives Considered

- **Keep ADR-0003 as is** — rejected by the owner: it costs a manual merge per
  routine run for a check that cannot currently resolve an id.
- **Register a trigger id and keep the gate** — not available: the environment
  exposes no trigger id, so no row could be matched at runtime.
- **Re-anchor the gate on some other stable value** — considered and dropped:
  the session ids rotate per run, and nothing else on offer identifies a
  trigger rather than a session.
- **Roll ADR-0003 out to the other 18 repositories instead** — the consistent
  alternative in the other direction; not chosen now, and still open should the
  owner revisit it.

## References

- Supersedes ADR-0003, which remains on file unedited.
- Issue #21 (original threat model), `agent_docs/deployment.md`,
  `.claude/skills/pr/SKILL.md → /pr merge`.
