# Deployment

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps trigger + pipeline path + agent scope + the merge/dispatch rule; this file carries the full wording and the mechanics.

## Trigger & pipeline

- **Trigger:** manual `workflow_dispatch` on `.github/workflows/release.yml`. It builds the Windows one-file exe and publishes a GitHub Release tagged `vYYYY.MM.DD.<run>`. A guard job fails any dispatch from a ref other than `main`.
- **Verification reuse:** `release.yml` calls the `ci.yml` `check` job via `workflow_call`, so a release can never be built from a red tree.
- **PRs** only run the `ci.yml` `check` job — never a build, never a release.
- **Distribution:** portable single-file `ListenToMe-<date>-<hhmm>-win64.exe` (UTC timestamp) attached to the Release. The in-app updater (`updater.py`) offers newer releases from the GitHub Releases API.
- **Environments:** none. There is no server; the "environment" is the user's desktop.

## Agent scope

The agent may push to feature branches and open/update PRs. Merging a PR and dispatching the release build each require an explicit user command.

**Routine exception.** A session running an **owner-authorized routine** counts as an explicit user command. Its merges are pre-approved — *including* any pipeline a merge triggers — provided **both** conditions hold:

- the change set is **non-destructive**: additive; no history rewrite, no force-push, no repo-settings change, no migration forced on existing users; **and**
- **verification passed**: the `ci.yml` `check` job, or its local equivalent (`python -m compileall -q src scripts` plus the offscreen `gui_smoke`), is green.

**Destructive change sets stay gated** behind an explicit interactive user command — no routine substitutes for one there.

**Accepted risk.** The routine claim arrives as prompt text, which reaches a session from outside the repository, and the agent cannot verify it: a scheduled trigger someone else edited, or an instruction injected through an issue or PR body, can assert routine status and inherit merge rights on a repo whose release workflow runs with `contents: write`. The owner accepted that trade knowingly, for fleet-wide consistency with the fifteen sibling repos and for automation throughput. The mitigations that remain are the two conditions above, the SHA-pinned actions (#22), and the fact that a merge alone publishes nothing — `release.yml` is `workflow_dispatch`-only and guarded to `main`. Full reasoning and alternatives: ADR-0005, superseding ADR-0004 (issue #21).

Merge gate: `.claude/skills/pr/SKILL.md → /pr merge`.

## GitHub Actions are pinned by commit SHA

Never by tag (#22). A tag can be moved to point at different code, and `release.yml` runs with `contents: write` and publishes the exe the in-app updater hands to users.

- Format: `uses: owner/repo@<40-hex-sha> # vX.Y.Z`
- To bump one, resolve the new SHA first: `git ls-remote --tags https://github.com/<owner>/<repo>`. For an annotated tag take the `^{}` line — that is the commit.
- Update the trailing comment with the new version.
- There is no Dependabot here, so bumps are manual and deliberate.

## Rollback

See `.claude/skills/rollback/SKILL.md`. For a bad release, prefer a revert-PR plus a fresh dispatched build over hand-editing a published asset — the updater serves whatever the Release carries.
