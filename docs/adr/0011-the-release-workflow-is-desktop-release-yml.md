# ADR-0011: The release workflow is `desktop-release.yml`

- **Status:** Accepted
- **Date:** 2026-11-26
- **Decider(s):** user (asked in chat to resolve the ADR drift reported in issue #434)
- **Tags:** build, deploy, ci
- **Supersedes:** ADR-0005, ADR-0009 and ADR-0010, each in part — only the workflow file name `release.yml`. Every decision those ADRs attach to the release workflow stays in force unchanged.

## Context

ADR-0005, ADR-0009 and ADR-0010 name the workflow that builds and publishes the Windows exe `release.yml`. PR #319 (commit `79f3aa2`, "ci: Rename the release workflow to desktop-release.yml") renamed it to `.github/workflows/desktop-release.yml`, which `CLAUDE.md` and `agent_docs/deployment.md` already name. The ADRs were never updated, so ADR-0010's decision points at a file that no longer exists, and the repo-quality routine reported the mismatch as drift (issue #434). The PortAudio steps ADR-0010 describes — `PORTAUDIO_COMMIT`, **Build PortAudio with WASAPI loopback**, **Verify the PortAudio DLL exports WASAPI loopback** — live in `desktop-release.yml` unchanged.

## Decision

We will name `.github/workflows/desktop-release.yml` as the release workflow wherever ADR-0005, ADR-0009 or ADR-0010 says `release.yml`; nothing else in those ADRs changes through this ADR.

## Consequences

### Positive

- The ADR set names only workflow files that exist, so a reader following ADR-0010 lands on the file that builds the PortAudio DLL.

### Negative / Trade-offs

- None beyond one more ADR in the index for a rename.

### Neutral

- The three ADRs keep their text; each mention of the old name is marked _(superseded by ADR-0011)_ in place, as the lifecycle in `agent_docs/adr_template.md` requires.

## Alternatives Considered

- **Editing the file name in the ADRs directly** — rejected: an Accepted ADR's text stays; only status, in-place markers and the verbatim detail move are allowed.
- **Leaving the drift open** — rejected by the owner, who asked for it to be fixed.

## References

- Issue #434 (ADR drift report); PR #319, commit `79f3aa2` (the rename).
- `.github/workflows/desktop-release.yml`; ADR-0005; ADR-0009; ADR-0010.
