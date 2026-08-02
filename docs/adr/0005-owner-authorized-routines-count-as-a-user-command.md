# ADR-0005: Owner-authorized routines count as an explicit user command

- **Status:** Accepted — supersedes ADR-0004
- **Date:** 2026-08-02
- **Decider(s):** user
- **Tags:** security, process, deployment

## Context

ADR-0004 removed the routine exception outright: merging a pull request and dispatching the release build each required an **explicit interactive user command**, and no routine, schedule or prompt claim substituted for one. It was written after ADR-0003's allowlist gate turned out to be dead weight — the allowlist never left its empty default state and the trigger id it hinged on was not reliably resolvable — so the simplest safe rule was to drop the exception entirely rather than keep four documents restating a branch that never fired.

That left this repository out of step with the rest of the fleet. The owner maintains fifteen sibling repositories (`ocean`, `clawstash`, `clawcademy`, `beacon`, `wisp`, `tubetrend`, `contract-manager`, `excel-agent`, `github-tools`, `competitive-analysis-app`, `simple-loop-agent`, `ai-hub-group-manager`, `sc-diver-react`, `owu-pptx-agent`, `owu-docx-agent`), and every one of them carries the same **routine exception**: a session running an owner-authorized routine counts as an explicit user command, for non-destructive change sets with green verification, with destructive changes still gated. One repo holding a stricter rule means the owner's maintenance routines stall here and nowhere else, and an agent that has internalised the fleet-wide wording has to remember a single exception to it — which is itself a source of error.

The owner has decided to accept the routine exception here too, with the residual risk recorded rather than argued away.

## Decision

We will reinstate the routine exception and align it with the sibling repositories. A session running an **owner-authorized routine** counts as an explicit user command for merging a PR and for dispatching the release build; its merges are pre-approved *including* any pipeline the merge triggers.

The exception applies only when **both** conditions hold:

- the change set is **non-destructive** — additive; no history rewrite, no force-push, no repo-settings change, no migration forced on existing users; and
- **verification passed** — the `ci.yml` `check` job, or its local equivalent (`python -m compileall -q src scripts` plus the offscreen `gui_smoke`), is green.

**Destructive change sets stay gated** behind an explicit interactive user command, with no routine substitute. Interactive sessions are unaffected — they already have the command they need.

## Consequences

### Positive

- The merge rule is identical across all sixteen repositories: one sentence to learn, no per-repo exception to remember.
- Owner-authorized maintenance routines (dependency bumps, doc alignment, agent-config sweeps) can close their own green, non-destructive loops instead of parking every one of them on a human.
- The two conditions are restated inline everywhere the rule appears, so a reader who never opens this ADR still sees "non-destructive" and "green verification".

### Negative / Trade-offs — the accepted risk

- **This is a real security regression, accepted knowingly.** The "owner-authorized routine" claim reaches the session as **prompt text**, and the agent cannot cryptographically verify it. A scheduled trigger someone else edited, an instruction injected through an issue body, a PR description, a pasted task description — any text reaching the session from outside the repository — can assert routine status and thereby inherit merge rights. ADR-0003 built an allowlist specifically to close this hole; ADR-0004 closed it by deleting the feature; this ADR reopens it. The trade is **a prompt-injection boundary exchanged for automation throughput**, and the owner has made that trade deliberately.
- The blast radius is bounded but not small: a merge to `main` is one dispatch away from a published release, and `release.yml` runs with `contents: write` to publish the exe the in-app updater hands to users.
- Verification is **self-reported by the same session** that claims routine status. Whoever can author the prompt can also claim the checks were green. The mitigations below shrink the plausible payload; none of them authenticates the claim.
- Re-tightening later means writing another superseding ADR and re-editing the same six documents.

### Mitigations that remain in force

- **Non-destructive change sets only** — additive; no history rewrite, no force-push, no repo-settings change, no forced migration.
- **Verification must be green** — a red `check` job blocks the merge under the `/pr merge` pre-flight, which is unchanged.
- **Destructive changes stay gated** — explicit interactive user command required, no routine substitute.
- **Releases stay a separate, deliberate act.** A merge alone publishes nothing: `release.yml` is `workflow_dispatch`-only and a guard job fails any dispatch from a ref other than `main`. A routine that also dispatches must satisfy the same two conditions.
- **GitHub Actions stay pinned by commit SHA** (#22), so a merged workflow edit cannot silently pull different third-party code into the release job.
- Every merge lands as a reviewable commit on `main` — nothing here weakens the audit trail or the ability to revert.

### Neutral

- Nothing else about agent scope changes: pushing to feature branches and opening/updating PRs were already unattended-friendly, as are the pre-approved Claude Code Remote trigger tools in `.claude/settings.json`.
- ADR-0003 and ADR-0004 stay in the repo as history. ADR-0003's references to the deleted `agent_docs/authorized_routines.md` remain unresolvable; this ADR does **not** restore that file — the exception is self-declared again, as it was before ADR-0003.

## Alternatives Considered

- **Keep ADR-0004 as-is** — rejected by the owner: it is the strictest rule in the fleet, it stalls maintenance routines in exactly one repository, and the inconsistency is itself a source of agent error.
- **Rebuild the ADR-0003 allowlist instead** — rejected: already tried here and it never fired once. The trigger id it depends on is not reliably resolvable from session metadata, so it degrades to "not authorized" and reproduces ADR-0004's behavior at four documents' worth of upkeep.
- **Allow routine merges but never anything that can reach a release** — rejected: every merge to `main` is one dispatch from a publishable build, so the boundary is not definable in prose. The `workflow_dispatch` + `main` guard is the mechanical version of this idea and it already exists.
- **Gate the exception on cryptographic or out-of-band verification of routine identity** — not rejected on merit, but out of scope: no such channel exists in the current harness. If one appears, a superseding ADR should gate the exception on it.

## References

- Supersedes `docs/adr/0004-agent-merges-require-an-explicit-user-command.md` (which superseded `docs/adr/0003-routine-merge-pre-approval-is-allowlist-gated.md`)
- `CLAUDE.md → Deployment`, `agent_docs/deployment.md`
- `.claude/skills/pr/SKILL.md → /pr merge`
- `agent_docs/architecture_principles.md`
- Issue #21
