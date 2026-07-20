---
name: done
description: "Use when the user signals work completion with 'done', 'fertig', 'finished', 'abschluss', '/done'. Detects current branch (main vs feature), runs closure checks defined in CLAUDE.md, handles commit and push based on branch context, closes related GitHub issues, and reports a strict short summary."
---

# Done — Work Closure

## When to Use

- User says "done", "fertig", "finished", "abschluss", "/done"
- End of a feature, bugfix, or task when ready to wrap up

## Workflow

### 1. Detect branch context

```bash
git rev-parse --abbrev-ref HEAD && git status --porcelain && git log origin/$(git rev-parse --abbrev-ref HEAD)..HEAD --oneline 2>/dev/null || echo "no upstream"
```

Classify:
- `main` / `master` / `develop` / `trunk` → **main branch mode** (conservative)
- anything else → **feature branch mode** (standard)

### 2. Read CLAUDE.md closure requirements

- **Commands section** → identify the automated checks (this project: `compileall` + Qt offscreen smoke; no lint/format/typecheck)
- **Git Conventions** → commit format (imperative subject), branch rules, merge strategy
- **Documentation Rules** → verify affected docs (CLAUDE.md, README.md, MEMORY.md, SCRATCHPAD.md, BACKLOG.md, config table) are up to date

### 3. Auto-format (write mode)

Run the project's format-write command from the CLAUDE.md Commands block. **This project has NO formatter configured — skip this step.** (If a formatter is added later and listed in CLAUDE.md, run it here before the checks and stage the result into the upcoming commit with `git add -u`.)

### 4. Run automated checks

Execute the project's checks from CLAUDE.md:

```bash
python -m compileall -q src scripts
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"
```

If any fail:
- **Feature branch:** report failure, stop. Do not commit.
- **Main branch:** hard stop. Never push to main on red.

### 5. Verify scope

Run `git status` and verify no unexpected files are staged (stray `.claude/**`, generated artifacts, `build/`, `dist/`). Revert anything that wasn't the point of the task with `git checkout -- <paths>` before committing.

### 6. Commit uncommitted changes (if any)

- Follow the project's commit convention: imperative capitalized subject, optional `area:` prefix, **not** Conventional Commits.
- Reference the GitHub issue number if applicable (e.g. `Fix crash on empty audio #42`).
- **Main branch:** if the uncommitted diff is large/unfocused → ask user before committing.

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
✅ <branch>: <what was done — max 3 lines>

→ Next: <max 2 lines, only if something is open; omit entirely if nothing pending>
```

## Rules

- **This project has no formatter/linter/typechecker** — the check step is `compileall` + the Qt smoke test. Do not add tooling to make a check pass.
- **Never push to `main` with failing checks.** Hard stop.
- **Never force-push** without explicit user request.
- **Ambiguous state on main** (large uncommitted diff, unclear scope) → ask first.
- **Report line limits are hard.** 3 lines for summary, 2 lines for next. No preamble, no postamble.
- If nothing to commit AND nothing to push AND no open issue → single-line confirmation: `✅ <branch>: already clean, nothing to do.`
