---
name: ci
description: "Use when the user wants CI status, failed-job logs, or help fixing a red build. Triggered by /ci, 'CI status', 'check the build', 'fix CI', 'why is CI failing', 'look at the build'. Auto-routes by state: status / logs / fix-proposal. Reads logs locally — never re-triggers builds without explicit user command."
---

# CI — Continuous Integration Workflow

## When to Use

- After `git push` when CI may be running
- User says "/ci", "CI status", "check the build", "fix CI", "why is CI red", "look at the build"
- Triaging a failing branch / PR before merging

## This project's CI

Two separate workflows:
- **`.github/workflows/ci.yml`** ("CI", runs on every PR): `python -m compileall -q src scripts` + a Qt **offscreen** UI smoke test (`selftest.gui_smoke`). This is the only workflow that gates PRs.
- **`.github/workflows/release.yml`** ("Release", only on manual `workflow_dispatch`): guard job (fails off `main`) → CI checks (via `workflow_call`) → PyInstaller one-file build + `--selftest` on the exe + GitHub Release. **Never** triggered by PRs or pushes, so a PR being "green" only means the CI `check` job passed.

## Prerequisites

```bash
gh auth status && gh repo view --json name,owner
```

If `gh` is missing or unauthenticated → print install/login instructions, or use `mcp__github__actions_*` / `mcp__github__get_job_logs` if the GitHub MCP server is connected.

## Auto-Routing (default `/ci`)

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
HEAD_SHA=$(git rev-parse HEAD)
RUNS=$(gh run list --branch "$BRANCH" --limit 5 --json databaseId,status,conclusion,headSha,name,workflowName)
```

Decision matrix:

| State                                            | Action                              |
|--------------------------------------------------|--------------------------------------|
| No runs found for branch                         | Phase A — report "no CI runs yet"   |
| Latest run `in_progress` / `queued`              | Phase B — show running status       |
| Latest run `success`                             | Phase C — green report              |
| Latest run `failure` / `cancelled` / `timed_out` | Phase D — fetch logs + propose fix  |
| Latest run is for `headSha != HEAD_SHA` (stale)  | Phase E — note stale; `/ci logs` to inspect the old run |

Print detected phase before acting.

## Phase A — No runs

```
No CI runs found for branch <branch>. Possible reasons:
- Branch not yet pushed → git push -u origin <branch>
- Workflow not configured for this branch → check .github/workflows/ci.yml
- Workflow disabled → gh workflow list
```

## Phase B — In progress

```bash
gh run view <run-id>            # default (no waiting)
# gh run watch <run-id> --exit-status   # only if user opted into wait
```

```
🟡 Run #<id> "<workflow>" in progress — <N>/<M> jobs done.
URL: <url>
```

## Phase C — Green

```
🟢 Run #<id> "<workflow>" passed (<duration>).
URL: <url>
```

## Phase D — Failed (the work)

1. **Identify failed jobs:**
   ```bash
   gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion == "failure") | {name, databaseId, conclusion}'
   ```
2. **Fetch failed-step logs only:**
   ```bash
   gh run view <run-id> --log-failed
   ```
3. **Classify failure** by signal in the log:
   - `SyntaxError` / `compileall` failure → syntax error in a source file
   - `ImportError` / `ModuleNotFoundError` → a heavy import got hoisted, or a missing dep in the smoke-test install list
   - Qt / `gui_smoke` non-zero → UI construction failed offscreen (often a cross-thread or import-order issue)
   - `apt-get` / library install failure → CI infra (the Linux Qt libs step)
   - timeouts, OOM, runner shutdown → infra failure (NOT a code defect)
4. **Propose fix:**
   - Code defect → propose minimal patch, apply only on user confirm
   - Infra failure → propose `gh run rerun <run-id> --failed`. **Never auto-rerun**, always confirm.
   - Flaky → log to BACKLOG.md as P1, do NOT silently retry to "make it pass"
5. **Verify fix locally** before any push — run `compileall` + the offscreen Qt smoke exactly as CI does.

```
🔴 Run #<id> "<workflow>" failed.
Failed job: <name>
Failure type: <syntax | import | qt-smoke | infra>
Root cause: <one sentence>
Proposed fix: <patch summary OR "rerun (infra issue)">
Local verification: <results of compileall + offscreen gui_smoke>
URL: <url>
```

## Phase E — Stale run

```
Latest CI run was for <stale-sha> (now HEAD is <head-sha>). Push to trigger a fresh run, or use /ci logs to inspect the stale run anyway.
```

## Explicit Sub-Commands

| Command      | Behavior                                                  |
|--------------|-----------------------------------------------------------|
| `/ci`        | Auto-route per matrix above                               |
| `/ci status` | Force Phase B/C report, no log fetching, no fix proposal  |
| `/ci logs`   | Force Phase D log fetch even if green                     |
| `/ci fix`    | Force Phase D fix workflow                                |
| `/ci rerun`  | Confirm-then-`gh run rerun --failed` for the latest failed run |

## Hard Rules

- **Never `gh run rerun` without explicit user confirmation.**
- **Never propose a fix without reading the actual failed-step log.**
- **Always verify locally** before pushing a CI fix (autonomy + zero-cost rule).
- **Infra failures are NOT code defects.** Don't patch code for runner timeouts / apt failures.
- **Flaky tests go to BACKLOG.md, not silent retry.**
