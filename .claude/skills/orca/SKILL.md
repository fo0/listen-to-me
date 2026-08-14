---
name: orca
description: "Orchestrator mode, toggled with '/orca' — also 'orca mode', 'orchestrator mode', 'orca an/aus', 'delegate everything from now on'. While ON the main agent does no task work itself: every unit goes to subagents that inherit its model and effort, at most N in parallel (default 5). '/orca off' restores normal behavior. Load it when the user toggles the mode or asks for its state, and at session start when SCRATCHPAD.md still marks the mode ON."
argument-hint: "[on|off|N|status]"
---

# Orca — Orchestrator Mode

## When to Use

- `/orca` · `/orca on|off|status` · `/orca 10` — the user toggles the mode or asks what it is set to
- "orca mode", "orchestrator mode", "orca an/aus", "ab jetzt alles delegieren", "delegate everything"
- Session start, when `SCRATCHPAD.md` still carries an Orca line from an earlier session or from before a compaction

Not this skill: a one-off "use a subagent for this". That is the normal delegation table in
`agent_docs/review_process.md → Subagent Delegation`.

## Toggle

| Argument                                 | Effect                                                                         |
| ---------------------------------------- | ------------------------------------------------------------------------------ |
| _(none)_                                 | Flip the current state — off → on at the last width (5 if never set), on → off |
| `on` / `off`                             | Set explicitly                                                                 |
| `N` — any number (`/orca 10`, `/orca 2`) | On, with at most N subagents running at once                                   |
| `status`                                 | Report state + width, change nothing                                           |

**Default is off.** Until someone types `/orca`, this file changes nothing about how the session works. Switching on
or off is confirmed in one line — state, width, and what it means for the next turn.

**State** lives in `SCRATCHPAD.md` → _Current Work_ as one line — `**Orca mode** — ON, max <N> parallel (<date>)` —
because a mode that only exists in context silently disappears at the next compaction. Switching off removes the
line. A line left over from an earlier session is _state, not authority_: say in one sentence that the mode is still
on, then work in it — the user has `/orca off`.

## The contract while ON

1. **Every unit of task work is delegated. No exception.** Reading a file for its content, searching, planning,
   editing, writing tests, running checks, reviewing — all of it happens in a subagent, including the units that
   would plainly be faster done directly. "Too small to delegate" is not a judgment this mode makes; `/orca off` is.
2. **The orchestrator keeps four things,** and all four are decisions rather than work: decomposition and assignment ·
   read-only verification of what comes back (`git status`, `git diff`, reading the changed files) · integration and
   its gates (commit, push, `/pr`, `/ci`, `/rollback`, merge, release dispatch) · the report to the user. A gate handed
   to a subagent is a gate that answers itself — the subagent holds the tool and has nobody to ask.
3. **Subagents inherit the orchestrator's quality — by omission, not by setting.** Leave the model parameter off and
   the subagent runs the session's model; leave the effort / reasoning parameter off, where the surface has one, and
   it runs the session's effort. Never pass a smaller model, never pass a lower effort, never route work to a cheaper
   agent to save tokens. Two places where inheritance does not happen on its own: a repo-local `.claude/agents/*.md`
   whose frontmatter pins a `model:` overrides it — pass the session's model explicitly for that agent type or do not
   use it; and `subagent_type: fork` always inherits the parent model whatever else is passed.
4. **Width: N in parallel, default 5.** Independent assignments go out in a single message, up to N; the rest waits
   for a free slot. Dependent work is sequenced — never parallelized in the hope that the order works out.
5. **Disjoint write scopes.** Two subagents in the same wave never hold write access to the same file. Split by file,
   or sequence, or give each one its own git worktree (`isolation: "worktree"`) where the surface offers it. In this
   repo `settings_ui.py` and `app.py` are the files two assignments most easily collide on.
6. **Assignments are self-contained.** A subagent has no conversation history: name the goal, the exact paths, what
   was already tried, the skill file to follow if one applies, the constraints, and what the return value must
   contain. Ask for a structured return — files touched, what changed, what was verified, what is still open.
7. **Verify the diff, not the summary.** A subagent's report describes intent. After every write-capable agent, read
   the actual change. A wave is done when the orchestrator has looked at what it produced, not when the agent says so.

## Rules

- **A failed subagent is a re-assignment, not a takeover.** Sharpen or split the assignment and send it again; the
  orchestrator never "just fixes it quickly" itself. Third failure on the same unit → `.claude/skills/stuck/SKILL.md`.
- **Unattended runs** (`CLAUDE_CODE_REMOTE=true`) keep the mode and keep the ban on ending a turn with a question —
  subagents cannot ask either, so the assignment states the assumption it runs under. See `CLAUDE.md` → _Autonomy_.
- **Skills stay in force.** A skill the user invokes while the mode is on is followed by the orchestrator; the work
  that skill asks for is what gets delegated.
- **This is the subagent contract, nothing wider.** It does not by itself authorize heavier multi-agent machinery
  (workflow-style fan-out over dozens of agents) — that stays an explicit user request.
- **Cost is the trade-off, and it is the user's to make.** The mode multiplies token use and adds latency per unit of
  work; that buys parallel width and a main context that stays clean. Say it once when switching on, then never again.

## Report

Close every wave with:

```
### Orca — wave <n> (<k>/<N> parallel)
| Assignment | subagent_type | Scope | Result | Verified |
|------------|---------------|-------|--------|----------|
| <what> | <type> | <files> | done / partial / failed | diff read ✅ / ❌ |

Next: <next wave / integration step / "nothing — reporting to user">
```
