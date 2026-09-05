---
name: done
description: "Use when the user signals work completion with 'done', 'fertig', 'finished', 'abschluss', '/done'. Detects current branch (main vs feature), runs closure checks defined in CLAUDE.md, handles commit and push based on branch context, closes related GitHub issues, and reports a strict short summary."
metadata:
  origin: claude-code-optimizer
---

# Done — Work Closure

## When to Use

- User says "done", "fertig", "finished", "abschluss", "/done"
- End of a feature, bugfix, or task when ready to wrap up

## Scope Boundaries

**Owns:** closing a piece of work out — format, the automated-check chain, scope check, commit, push, issue close.
**Does not own:** the review itself (`review`), the PR object (`pr`), remote build state (`ci`). It _suggests_ those and never runs them — that fence is what keeps `/done` predictable enough to type without reading it first.

## Workflow

### 1. Detect branch context

```bash
git rev-parse --abbrev-ref HEAD && git status --porcelain && git log origin/$(git rev-parse --abbrev-ref HEAD)..HEAD --oneline 2>/dev/null || echo "no upstream"
```

Classify:

- `main` / `master` / `develop` / `trunk` → **main branch mode** (conservative)
- anything else → **feature branch mode** (standard)

### 2. Read CLAUDE.md closure requirements

- **Commands section** → identify the automated checks, in the canonical order stated there (this project: Prettier for Markdown, then `compileall` + Qt offscreen smoke; no Python lint/format/typecheck)
- **Git Conventions** → commit format (imperative subject), branch rules, merge strategy
- **Documentation Rules** → verify affected docs (CLAUDE.md, README.md, MEMORY.md, SCRATCHPAD.md, BACKLOG.md, config table) are up to date

### 3. Auto-format (write mode)

Run **this project's** format-write command, exactly as CLAUDE.md → _Commands_ names it. There is no Python formatter; Markdown is the one formatted surface — when any `.md` file changed, run it before the rest of the chain, or the drift reaches CI and fails `docs-format.yml` there:

```bash
npx --yes prettier@3.9.6 --write "**/*.md"   # no install, no package.json — version pinned in docs-format.yml
```

- No `.md` file changed → skip this step.
- If formatting changed files, **stage them with `git add -u` so they go into the upcoming commit (step 6)** — do NOT split formatting into its own commit.
- Re-run `git status --porcelain` after formatting to see what changed.

### 4. Run automated checks

Execute the project's check chain from CLAUDE.md → _Commands_, in the order stated there:

```bash
npx --yes prettier@3.9.6 --check "**/*.md"   # only when Markdown changed — matches docs-format.yml
python -m compileall -q src scripts
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"
```

If any fail:

- **Feature branch:** report failure, stop. Do not commit.
- **Main branch:** hard stop. Never push to main on red.

### 5. Verify scope

Run `git status` and verify no unexpected files are staged (stray `.claude/**`, generated artifacts, `build/`, `dist/`). Revert anything that wasn't the point of the task with `git checkout -- <paths>` before committing.

### 5b. Context budget check

```bash
wc -c CLAUDE.md MEMORY.md SCRATCHPAD.md 2>/dev/null
```

Over 20,000 / 16,000 / 8,000 chars → offload per `agent_docs/context_budget.md` **now**, in this commit: move content to `agent_docs/` (or `docs/adr/`, `agent_docs/memory_archive/`) and leave a one-line pointer. Never delete to fit. This is the closure gate that keeps the always-loaded files from drifting — deferring it just moves the cost to every future session.

### 6. Commit uncommitted changes (if any)

- Follow the project's commit convention: imperative capitalized subject, optional `area:` prefix, **not** Conventional Commits.
- Reference the GitHub issue number if applicable (e.g. `Fix crash on empty audio #42`).
- **Main branch:** if the uncommitted diff is large/unfocused → ask user before committing. Unattended (`$CLAUDE_CODE_REMOTE=true`) nobody answers: leave it uncommitted, report the `git diff --stat` as the open point, and finish the steps that do not depend on it (CLAUDE.md → _Autonomy_).

### 7. Push

- **Feature branch:** `git push` (use `git push -u origin <branch>` on first push)
- **Main branch:** `git push origin <branch>` — only after all checks green
- **Never force-push** unless user explicitly requests

### 8. Suggest PR + CI (feature branch only)

After push on a feature branch, suggest follow-ups — do NOT run them automatically:

- Print: `Run /pr to handle the PR (auto-detects: create / update / status).`
- Print: `Run /ci to check the build (auto-detects: status / logs / fix).`
- The PR skill (`.claude/skills/pr/SKILL.md`) and CI skill (`.claude/skills/ci/SKILL.md`) auto-route by state. Done-skill never invokes them directly.

### 9. Close related GitHub issue (if applicable)

- Comment on the issue in **English** with a short summary of what was delivered
- Close the issue

### 10. Report

Strict format, strict limits:

```
✅ <branch>: <what was done>

→ Next: <only if something is open; omit entirely if nothing pending>
```

## Rules

- **Format-write always runs before the checks** when Markdown changed — never commit unformatted `.md` files; `docs-format.yml` is unforgiving. Python has no formatter/linter/typechecker here: the check step is `compileall` + the Qt smoke test. Do not add tooling to make a check pass.
- **Never push to `main` with failing checks.** Hard stop.
- **Never force-push** without explicit user request.
- **Ambiguous state on main** (large uncommitted diff, unclear scope) → ask first; unattended → uncommitted plus a report line (step 6).
- **The report is the two lines above and nothing else.** No preamble, no postamble, nothing the commit message already says; the `Next:` line only when something is open.
- If nothing to commit AND nothing to push AND no open issue → single-line confirmation: `✅ <branch>: already clean, nothing to do.`
