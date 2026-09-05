---
name: rollback
description: "Use when the user wants to undo a broken commit, push, or PR — triggered by /rollback, 'rollback', 'revert that', 'undo last commit', 'undo the push', 'restore branch'. Auto-detects the rollback target from current state (last commit / pushed range / open PR / merged PR) and chooses the safest reversal path. Never destroys history without explicit confirmation."
metadata:
  origin: claude-code-optimizer
---

# Rollback — Recovery Workflow

## When to Use

- User says "/rollback", "rollback", "revert", "undo", "restore"
- A broken commit / merged bad PR / pushed defect / corrupted branch needs reverting

## Scope Boundaries

**Owns:** reversing git state that already exists — uncommitted changes, local commits, pushed commits, an open or merged PR, a deleted branch.
**Does not own:** diagnosing _why_ it broke (`stuck`), fixing a red build forward instead of backward (`ci`), reversing a release (CLAUDE.md → _Deployment_). Reaching for it to escape a confusing state rather than a broken one is the wrong skill: that is `stuck`.

## Auto-Detect Target

No `gh`? Use the equivalent `mcp__github__*` tool for every `gh` call below — see `agent_docs/mcp_catalog.md` → the `github` row.

```bash
git rev-parse --abbrev-ref HEAD
git status --porcelain
git log -1 --pretty='%H %s'
git log @{u}..HEAD --oneline 2>/dev/null  # local-only commits
git log HEAD..@{u} --oneline 2>/dev/null  # behind upstream
gh pr list --head $(git rev-parse --abbrev-ref HEAD) --json number,state 2>/dev/null
```

Decision matrix:

| State                              | Action                                                  |
| ---------------------------------- | ------------------------------------------------------- |
| Uncommitted local changes only     | Phase A (discard working tree, opt-in)                  |
| Local commits, not pushed          | Phase B (reset back N commits)                          |
| Pushed commits on feature branch   | Phase C (revert + push, or force-with-lease — explicit) |
| Pushed to main + bad commit on top | Phase D (revert + push)                                 |
| Merged PR causing breakage         | Phase E (revert PR via gh)                              |
| Branch deleted by mistake          | Phase F (restore from reflog / origin)                  |

Always **print the detected state and proposed action before executing**, then wait for confirmation:

```
Detected: pushed 2 commits to claude/x; latest broke the check job.
Proposed: git revert HEAD~1..HEAD && git push (no force).
Proceed? (yes/no)
```

**Unattended** (`$CLAUDE_CODE_REMOTE=true`): nobody answers `Proceed?`, and a run that waits for it is a dead run (CLAUDE.md → _Autonomy_). The phases split by what they destroy. Phases C, D, E and F add commits or restore a ref — they run without the prompt, and the detection line above becomes a report line. Phases A and B and every force operation destroy work: they run unattended only when the instruction that invoked this skill ordered exactly that (the `stuck` skill's unattended step ordering the loop work discarded is one); otherwise skip, report the proposed command, and continue with what does not depend on it.

## Phase A — Discard uncommitted changes

User must explicitly confirm. Loses local work.

```bash
git diff --stat            # show what will be lost
# Wait for user "yes"
git restore --staged .
git restore .
```

## Phase B — Reset local-only commits

```bash
git log @{u}..HEAD --oneline    # confirm range
# Wait for user "yes"
git reset --hard HEAD~N         # N = number of unpushed commits
```

## Phase C — Revert pushed commits on feature branch

Default: revert (preserves history). Force-push only on explicit user request.

```bash
git revert --no-edit HEAD~N..HEAD
git push                                  # no force
# OR (only if user explicitly says "force"): git push --force-with-lease
```

## Phase D — Revert on main

Always use `git revert` on the default branch. Never `git reset --hard` there without explicit user override. "Main" is whatever this repo's default branch is called — resolve the name, never assume it:

```bash
BASE=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)   # MCP: the repo's default_branch
git revert --no-edit <bad-sha>
git push origin "$BASE"
```

If revert produces a conflict → stop, ask user to resolve manually.

## Phase E — Revert merged PR

`gh` has no `pr revert` subcommand — build the revert PR manually. A revert **PR** is preferred over a direct push to the default branch: it survives branch protection and keeps the change reviewable.

```bash
PR=<number>
BASE=$(gh pr view "$PR" --json baseRefName --jq .baseRefName)     # the branch the PR merged into — never assume `main`
SHA=$(gh pr view "$PR" --json mergeCommit --jq .mergeCommit.oid)
git checkout "$BASE" && git pull
git checkout -b revert-pr-$PR
git revert -m 1 "$SHA"                  # -m 1 = keep mainline parent
git push -u origin revert-pr-$PR
gh pr create --base "$BASE" --title "Revert PR #$PR" --body "Reverts #$PR — <reason>"
gh pr comment "$PR" --body "Reverted via #<new-pr-number> — <reason>"
```

## Phase F — Restore deleted branch

```bash
git reflog | head -20                    # find the lost SHA
git branch <name> <sha>                  # local restore
git push -u origin <name>                # if remote was also gone
```

## Hard Rules

- **Never `git reset --hard` on main.** Always revert.
- **Never `git push --force` on main.** Default is revert + new commit.
- **Never delete a branch** as part of rollback — only restore / revert.
- **Always print a dry-run diff** of what the rollback will change before executing.
- **Always confirm with the user before destructive ops** (`reset --hard`, `force-push`, branch delete). Unattended, the confirmation cannot happen, so the op is skipped and reported (_Unattended_ under Auto-Detect Target) — never assumed.
- **Checks must pass after rollback.** If the rollback itself breaks the build, stop and surface.

## After Rollback

1. Run `compileall` + Qt smoke per CLAUDE.md.
2. Comment on the original PR / issue explaining the rollback (English, short).
3. Recommend a follow-up: open a new branch, fix the root cause, do not just re-apply.

## Report

```
↩️ Rollback complete
Phase: <A/B/C/D/E/F>
Reverted: <commits or PR number>
Branch: <branch>
Checks: <pass/fail>
Next: <link to follow-up branch or issue, if applicable>
```

If failed:

```
❌ Rollback halted
Reason: <conflict / check failure / missing reflog entry>
State: <what's currently true on disk + remote>
Next steps: <concrete commands the user can run>
```
