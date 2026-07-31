# Deployment

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps trigger + pipeline path + agent scope + the routine rule in short form; this file carries the full wording and the mechanics.

## Trigger & pipeline

- **Trigger:** manual `workflow_dispatch` on `.github/workflows/release.yml`. It builds the Windows one-file exe and publishes a GitHub Release tagged `vYYYY.MM.DD.<run>`. A guard job fails any dispatch from a ref other than `main`.
- **Verification reuse:** `release.yml` calls the `ci.yml` `check` job via `workflow_call`, so a release can never be built from a red tree.
- **PRs** only run the `ci.yml` `check` job — never a build, never a release.
- **Distribution:** portable single-file `ListenToMe-<date>-<hhmm>-win64.exe` (UTC timestamp) attached to the Release. The in-app updater (`updater.py`) offers newer releases from the GitHub Releases API.
- **Environments:** none. There is no server; the "environment" is the user's desktop.

## Agent scope

The agent may push to feature branches, open/update PRs, and suggest merge. The agent does **NOT** dispatch the release build without an explicit user command.

## Routine exception

A session running an **owner-authorized routine** counts as an explicit user command. Its merges are pre-approved — including any pipeline they trigger — when **both** of the following hold:

1. The change set is non-destructive: additive, no data migration, no history rewrite, no repo-settings change.
2. The routine's verification passed.

Destructive change sets stay gated regardless. **Release dispatch is not covered** — `workflow_dispatch` on `release.yml` always needs an explicit user command, routine or not.

Merge gate: `.claude/skills/pr/SKILL.md → /pr merge`.

> This replaced an allowlist-gated version (ADR-0003, Issue #21) that required the session's trigger id to be listed in a file committed to `main`. It was removed in ADR-0004 because the environment exposes no trigger id, so the check declined authorized and unauthorized sessions alike. The trade-off ADR-0004 accepts: the trust anchor is prompt text again, which reaches a session from outside the repo. Read ADR-0004 before widening the exception further.

## GitHub Actions are pinned by commit SHA

Never by tag (#22). A tag can be moved to point at different code, and `release.yml` runs with `contents: write` and publishes the exe the in-app updater hands to users.

- Format: `uses: owner/repo@<40-hex-sha> # vX.Y.Z`
- To bump one, resolve the new SHA first: `git ls-remote --tags https://github.com/<owner>/<repo>`. For an annotated tag take the `^{}` line — that is the commit.
- Update the trailing comment with the new version.
- There is no Dependabot here, so bumps are manual and deliberate.

## Rollback

See `.claude/skills/rollback/SKILL.md`. For a bad release, prefer a revert-PR plus a fresh dispatched build over hand-editing a published asset — the updater serves whatever the Release carries.
