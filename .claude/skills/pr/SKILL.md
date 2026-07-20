---
name: pr
description: "Use for any GitHub Pull Request work. Auto-detects lifecycle phase (create / update / report) from current state — only requires explicit command for status, comments, or merge. Triggered by /pr, 'PR', 'create PR', 'open PR', 'update PR', 'PR status', 'merge PR'. Suggests, never auto-creates without user invocation."
---

# PR — Pull Request Workflow

## When to Use

- User says "PR" / "/pr" / "create PR" / "open PR" / "update PR" → **auto-route by state**
- User says "PR status" / "/pr status" / "check PR" → status (override)
- User says "PR comments" / "/pr comments" → read review comments (override)
- User says "merge PR" / "/pr merge" → merge (explicit only, never automatic; owner-authorized routines count as explicit — see `/pr merge`)
- After done-skill push step on a feature branch → suggested, user invokes `/pr` to trigger

## Prerequisites

```bash
gh auth status && gh repo view --json name,owner
```

If `gh` is missing or unauthenticated:
- Print: `gh CLI required. Install: https://cli.github.com — then run: gh auth login`
- Stop. Do NOT fall back to manual PR creation via web.

> **Web/remote sessions:** if the `gh` CLI is unavailable but the GitHub MCP server is connected, use the `mcp__github__*` tools (create/update PR, list PRs, checks) as the equivalent of the `gh` calls below.

## Dependency-Bot PRs (auto-detect)

Before normal auto-routing, detect dep-bot PRs by **head branch pattern** (not by author — author can be spoofed):

| Bot          | Branch pattern               |
|--------------|------------------------------|
| Dependabot   | `dependabot/**`              |
| Renovate     | `renovate/**` or `renovate-bot/**` |
| Snyk         | `snyk-fix/**` / `snyk-upgrade/**` |
| pyup         | `pyup-update-**`             |

When a dep-bot PR is detected, follow the **Dep-Bot PR Workflow** below instead of standard `/pr` routing.

### Dep-Bot PR Workflow

1. **Identify scope** — `gh pr view --json title,body,files` — what packages and from/to versions.
2. **Read changelog/release notes** for each upgraded package. For major bumps, fetch the upstream changelog.
3. **Run the project's checks locally** on the dep-bot branch (`compileall` + Qt smoke; `--selftest` if deps installed).
4. **Classify by bump type:** patch → tests green → recommend merge · minor → review behavior changes → recommend merge if clean · major → never auto-recommend; read migration guide, surface breaking changes.
5. **Security advisories** in PR body → treat as P0 (security-review skill) — fix-forward.
6. **Group strategy** — multiple dep-bot PRs open → ask user whether to batch by ecosystem; never silently rebase across bots.
7. **Never auto-merge** dep-bot PRs without explicit user command. An owner-authorized dep-bot routine counts as explicit (see `/pr merge` → Routine exception); its bump-type rules (e.g. major = skip) still apply.

Report:

```
🤖 Dep-bot PR detected (<bot>): <N> packages bumped
Bumps: <package@from→to, ...>
Bump type: patch | minor | major
Local checks: <pass/fail>
Changelog risks: <none / list>
Recommendation: <merge / hold / surface for review>
```

## Auto-Routing (default `/pr`)

When the user invokes `/pr` or "PR" without a sub-command, **detect the lifecycle phase from current state** and act:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
PR_JSON=$(gh pr list --head "$BRANCH" --state all --json number,state,url,headRefOid 2>/dev/null)
HEAD_SHA=$(git rev-parse HEAD)
```

> `--state all` is required — `gh pr list` defaults to open PRs only. If the branch has several PRs, route on the open one; only when none is open does the `MERGED`/`CLOSED` row apply.

Decision matrix:

| State | Action |
|-------|--------|
| Branch is `main`/`master`/`develop`/`trunk` | Stop: `On main branch — no PR needed.` |
| No PR exists for branch | → **create** (Phase A) |
| PR exists, `headRefOid != HEAD_SHA` (local ahead) | → **push + update body** (Phase B) |
| PR exists, `headRefOid == HEAD_SHA`, body stale vs commits | → **update body only** (Phase B) |
| PR exists, fully synced | → **status** (Phase C, read-only) |
| PR exists but `MERGED`/`CLOSED` | Report final state + URL, stop |

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

**Routine exception:** a session running an **owner-authorized routine** whose prompt orders merges counts as an explicit user command (see CLAUDE.md → Deployment → Routine exception). Such merges may run unattended — including any deploy the merge triggers — for non-destructive change sets with green verification. The routine's own merge rules then override the pre-flight below.

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
- **Never merge automatically.** Explicit `/pr merge` required. Exception: owner-authorized routine.
- **Issue linking:** if commit messages contain `#<n>` → include `Closes #<n>` in PR body Summary.
- **Draft PRs:** if user says "draft PR" → `gh pr create --draft`.
- **Branch-name → title heuristics:** this project's branches are `claude/<slug>` with no type prefix — derive the title from the latest commit subject (imperative), not from the branch slug.

## Error Recovery

| Failure | Action |
|---------|--------|
| `gh` not installed | Stop, print install instructions (or use `mcp__github__*` tools if MCP is connected) |
| `gh auth status` fails | Stop, print `gh auth login` |
| `git push` rejected (non-fast-forward) | Stop, ask user before force operations |
| `gh pr create` fails due to existing PR | Re-run auto-route (will land in Phase B) |
| Merge conflict on `gh pr merge` | Stop, instruct user to rebase/merge locally |
| Required status check not yet started | Print pending state, do not retry-loop |
