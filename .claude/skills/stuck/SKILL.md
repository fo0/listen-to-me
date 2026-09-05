---
name: stuck
description: "Use when the agent is in a fix-retry loop, an error keeps recurring after multiple attempts, or the user says 'stuck', 'loop', 'going in circles', '/stuck'. Snapshot what was tried, surface to user, never silent-retry past 3 attempts."
metadata:
  origin: claude-code-optimizer
---

# Stuck — Loop / Dead-End Recovery

## When to Use

- User says "stuck", "loop", "going in circles", "/stuck"
- Agent self-detects a loop:
  - Same error after 2nd fix attempt → log warning, third attempt MAY proceed if a different angle is being tried
  - Same error after 3rd attempt → STOP, invoke this skill
  - Same file edited 5+ times in one session for the same defect
- A check passes locally but fails in CI 2+ consecutive runs without a code change in between (likely flake)

## Scope Boundaries

**Owns:** breaking a fix-retry loop — snapshot, attempt log, diagnosis of the loop type, escalation.
**Does not own:** undoing the damage (`rollback`), the review that would have caught the defect (`review`), the decision to abandon the approach — that one is escalated, never taken here.

## Workflow

### 1. Snapshot

```bash
git status --porcelain
git diff --stat
git log --oneline -10
```

Plus:

- Last error message verbatim (no paraphrasing)
- Last 3 commands run and their exit codes
- Files touched in this loop

### 2. Attempt Log

```
Attempt 1: <approach> → <result>
Attempt 2: <approach> → <result>
Attempt 3: <approach> → <result>
```

If you can't articulate the attempts as distinct approaches → that itself is the diagnosis (you've been trying the same thing).

### 3. Diagnose Loop Type

| Pattern                                              | Likely cause                                                         | Action                                   |
| ---------------------------------------------------- | -------------------------------------------------------------------- | ---------------------------------------- |
| Same fix re-applied because the Qt smoke still fails | Import order / cross-thread / lazy-import regression                 | Re-read the threading model in CLAUDE.md |
| Import / module-not-found that "should work"         | A heavy import got hoisted to module scope                           | Move it back inside the function         |
| CUDA / GPU error surviving every attempt             | Wrong fallback path, or a transient OOM misread as "GPU unavailable" | Re-read `transcriber.py` fallback logic  |
| Qt error only offscreen / only in CI                 | Widget touched off the main thread                                   | Route through `App.post`                 |
| Check flake (passes/fails non-deterministically)     | Race / shared state / timing                                         | Treat as flake → BACKLOG.md              |
| Network / external-API error                         | Unmocked external dep                                                | Apply zero-cost rule — mock              |
| CI infra (apt install / timeout / OOM)               | NOT a code defect                                                    | Surface to CI skill, do not "fix" code   |

### 4. Surface to User

```
🛑 Stuck — escalating after <N> attempts on the same defect.

Snapshot:
- Branch: <branch>
- Last error: <verbatim, fenced>
- Files touched repeatedly: <list>

Attempts:
1. <approach> → <result>
2. <approach> → <result>
3. <approach> → <result>

Diagnosis: <loop type from table above, OR "unknown — pattern doesn't match">

Options for the user:
A) <concrete next-step option>
B) <alternative angle>
C) revert the loop work — `/rollback`
D) defer to BACKLOG and move on

What would you like?

<the handoff prompt for the option you recommend — CLAUDE.md → _Handoff Prompt_>
```

Then **stop**. Do NOT take a 4th attempt without user input. The handoff prompt is part of the escalation, not a
replacement for the options: it carries the one option you would pick, ready to send.

### 4b. Unattended run — same snapshot, no question

`$CLAUDE_CODE_REMOTE=true` (web/cloud session, routine runs included) means nobody will answer, and a run that ends on
"What would you like?" is a run that ended on nothing (CLAUDE.md → _Autonomy_). Same 3-attempt cap, same snapshot,
different landing:

1. Write the snapshot and the options as one `BACKLOG.md` entry (`agent_docs/backlog_process.md` format), status **Open**.
2. Leave the loop work uncommitted, or `/rollback` it if it made the tree worse. Never commit a defect to get past it.
3. Continue with the parts of the task that do **not** depend on the stuck defect — being blocked on one thing is not
   being blocked on everything.
4. End with the run's normal report, naming the defect, the backlog entry and what was finished around it.

Option D of the interactive format is the unattended default; A–C need a human and are recorded, not chosen.

## Hard Rules

- **3-attempt cap on the same defect.** No exceptions. The 4th try without user input is forbidden.
- **Snapshot before escalating.** No vague "I'm stuck" — show evidence.
- **Verbatim error messages.** Never paraphrase the error when escalating.
- **No silent retries.**
- **Loop work doesn't get committed silently.** Either user picks a path or rollback the loop.
- **Never end an unattended run with a question.** Escalation there means step 4b: backlog entry plus report.

## After User Response

- User picks a concrete option → execute, with attempt counter reset for the _new_ approach (not for the underlying defect).
- User asks for more info → produce the requested data, do NOT take it as license to retry.
- User says "keep trying" → ask once: "Same approach or a new angle? If same, I will stop after one more attempt." Then enforce that.
