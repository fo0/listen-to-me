---
name: pr
description: "Use for any GitHub Pull Request work. Auto-detects lifecycle phase (create / update / report) from current state — only requires explicit command for status, comments, or merge. Triggered by /pr, 'PR', 'create PR', 'open PR', 'update PR', 'PR status', 'merge PR'. Suggests, never auto-creates without user invocation."
---

# PR — Pull Request Workflow

## When to Use

- User says "PR" / "/pr" / "create PR" / "open PR" / "update PR" → **auto-route by state**
- User says "PR status" / "/pr status" / "check PR" → status (override)
- User says "PR comments" / "/pr comments" → read review comments (override)
- User says "merge PR" / "/pr merge" → merge (explicit command only, never auto-routed — see `/pr merge`)
- After done-skill push step on a feature branch → suggested, user invokes `/pr` to trigger

## Prerequisites

```bash
gh auth status && gh repo view --json name,owner
```

No `gh`? Use the equivalent `mcp__github__*` tool for every `gh` call below — that is the normal path in web/remote sessions and is not a reason to stop (`agent_docs/mcp_catalog.md` → the `github` row). Never create or merge a PR by hand in the browser instead.

> **Dependency bots:** this repo has no Dependabot, Renovate, Snyk or pyup configured (`agent_docs/deployment.md` — bumps are manual). Should a bot PR ever appear, route it like any other PR and run `/beacon` for the compatibility verdict; the merge rule under `/pr merge` covers it with no separate workflow.

## Auto-Routing (default `/pr`)

When the user invokes `/pr` or "PR" without a sub-command, **detect the lifecycle phase from current state** and act:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
PR_JSON=$(gh pr list --head "$BRANCH" --state all --json number,state,url,headRefOid 2>/dev/null)
HEAD_SHA=$(git rev-parse HEAD)
```

> `--state all` is required — `gh pr list` defaults to open PRs only. If the branch has several PRs, route on the open one; only when none is open does the `MERGED`/`CLOSED` row apply.

Decision matrix:

| State                                                      | Action                                 |
| ---------------------------------------------------------- | -------------------------------------- |
| Branch is `main`/`master`/`develop`/`trunk`                | Stop: `On main branch — no PR needed.` |
| No PR exists for branch                                    | → **create** (Phase A)                 |
| PR exists, `headRefOid != HEAD_SHA` (local ahead)          | → **push + update body** (Phase B)     |
| PR exists, `headRefOid == HEAD_SHA`, body stale vs commits | → **update body only** (Phase B)       |
| PR exists, fully synced                                    | → **status** (Phase C, read-only)      |
| PR exists but `MERGED`/`CLOSED`                            | Report final state + URL, stop         |

Always print the detected phase before acting.

## Phase A — Create

1. **Push if needed:** if branch has no upstream → `git push -u origin <branch>`.
2. **Title:** derived from branch name OR latest commit subject (see heuristics). Keep ≤70 chars.
3. **Body:** generated from commits between base and HEAD:

   ```bash
   BASE=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
   git log "origin/$BASE..HEAD" --oneline
   ```

   Format:

   ```markdown
   ## Summary

   - <1-3 bullet points from commit subjects, deduplicated>

   ## Test plan

   - [ ] <what the user/reviewer needs to verify>

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   ```

4. **Create:** `gh pr create --title "..." --body "$(cat <<'EOF' ... EOF)"`. Use HEREDOC for body.
5. **Report URL** from gh output.

## Phase B — Update

1. `gh pr view --json number,url,body,state,baseRefName` — load existing PR.
2. **Push first** if local is ahead: `git push` (no force unless user explicitly requested).
3. Re-derive Summary from commits since base.
4. **Preserve user-edited sections** outside `## Summary` and `## Test plan`.
5. `gh pr edit <number> --body "$(cat <<'EOF' ... EOF)"`
6. Report: `Updated PR #N: <url>`

## Phase C — Status (default for synced PRs, or explicit `/pr status`)

```bash
gh pr view --json number,state,statusCheckRollup,reviewDecision,mergeable,url
gh pr checks
```

Report compact:

```
PR #N: <state> | CI: <pass/fail/pending> | Review: <approved/changes_requested/pending> | Mergeable: <yes/no/conflict>
URL: <url>
Failing checks: <list, only if any>
```

## `/pr comments` — read review comments (explicit override)

```bash
gh api "repos/{owner}/{repo}/pulls/{n}/comments" --jq '.[] | {user: .user.login, path, line, body}'
gh api "repos/{owner}/{repo}/issues/{n}/comments"  --jq '.[] | {user: .user.login, body}'
```

Group by reviewer + file. Show unresolved comments first. Do NOT auto-fix — surface findings, let user decide.

## `/pr merge` — merge (explicit only, never auto-routed)

**Never run without explicit user command.** Default `/pr` never reaches this phase.

**Routine exception.** A session running an **owner-authorized routine** counts as an explicit user command, so its merges are pre-approved — _including_ any pipeline the merge triggers — when the change set is **non-destructive** (additive; no history rewrite, no force-push, no repo-settings change, no forced migration) **and** verification is green. **Destructive change sets stay gated** and still need an explicit interactive command. The routine claim is prompt text the agent cannot verify; that residual risk is knowingly accepted. See CLAUDE.md → Deployment and ADR-0005 (superseding ADR-0004).

Pre-flight:

1. `gh pr view --json state,statusCheckRollup,reviewDecision,mergeable` — verify mergeable.
2. CI must be green. If not → stop: `Cannot merge: CI failing.`
3. If `reviewDecision != APPROVED` and repo requires approval → stop.
4. Merge strategy: read from CLAUDE.md "Git Conventions → Merge Strategy". This project uses **merge commits** — default `--merge`.

```bash
gh pr merge <number> --merge --delete-branch  # this project uses merge commits, not squash
```

Report: `Merged PR #N (merge commit). Branch deleted.`

## Rules

- **Auto-route only on default `/pr`.** Explicit sub-commands override detection.
- **Print detected phase before acting** so user can interrupt if wrong.
- **Never force-push** to update PR — `gh pr edit` for body, `git push` (no force) for code.
- **Never merge automatically.** Default `/pr` never reaches the merge phase. Merging needs an explicit `/pr merge` — or an owner-authorized routine that meets the non-destructive + green-verification conditions above.
- **Issue linking:** if commit messages contain `#<n>` → include `Closes #<n>` in PR body Summary.
- **Draft PRs:** if user says "draft PR" → `gh pr create --draft`.
- **Branch-name → title heuristics:** this project's branches are `claude/<slug>` with no type prefix — derive the title from the latest commit subject (imperative), not from the branch slug.

## Error Recovery

| Failure                                 | Action                                                                               |
| --------------------------------------- | ------------------------------------------------------------------------------------ |
| `gh` not installed                      | Stop, print install instructions (or use `mcp__github__*` tools if MCP is connected) |
| `gh auth status` fails                  | Stop, print `gh auth login`                                                          |
| `git push` rejected (non-fast-forward)  | Stop, ask user before force operations                                               |
| `gh pr create` fails due to existing PR | Re-run auto-route (will land in Phase B)                                             |
| Merge conflict on `gh pr merge`         | Stop, instruct user to rebase/merge locally                                          |
| Required status check not yet started   | Print pending state, do not retry-loop                                               |
