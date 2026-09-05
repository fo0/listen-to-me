---
name: orca
description: "Orchestrator mode — the default working mode of this project, not a toggle to find. The main agent does no task work itself: every unit goes to a role-framed subagent that inherits its model and effort, at most 5 in parallel unless overridden. Takes an objective: '/orca <objective>' or '/orca <N> <objective>' runs it as a delegated objective run — steps, a review per step, one overall review over the combined diff. Load it for that, for the contract (roles, width, write scopes, verification), when the user says '/orca', 'orca mode', 'orchestrator mode', 'orca an/aus', 'delegate everything', or asks what the width is set to. '/orca off' drops to plain behavior for this session only."
argument-hint: "[on|off|status|N] [objective]"
metadata:
  origin: claude-code-optimizer
---

# Orca — Orchestrator Mode

## When to Use

- `/orca` (reports state and width) · `/orca on|off|status` · `/orca 10` — the user asks what the mode is set to, or changes it
- `/orca <objective>` · `/orca <N> <objective>` — an objective to carry through a delegated run, optionally at a stated width
- "orca mode", "orchestrator mode", "orca an/aus", "ab jetzt alles delegieren", "delegate everything"
- Session start, when `SCRATCHPAD.md` still carries an Orca line from an earlier session or from before a compaction

Not this skill: choosing a `subagent_type` for one assignment while already orchestrating. That is the type/role
table in `CLAUDE.md → Subagents`, with the longer form in `agent_docs/review_process.md → Subagent Delegation`.

## Scope Boundaries

**Owns:** how work is divided across subagents and at what width — the delegation contract itself.
**Does not own:** when the work runs (`scheduler`), the stop condition checked between turns (Claude Code's built-in `/goal`), the review contract it delegates against (`agent_docs/review_process.md`).

## Invocation

The text after the skill name is the argument. It arrives substituted at the bottom of this section; parse it in
this order — the first match wins:

| Argument                    | Reading           | Effect                                                                                                                   |
| --------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------ |
| _(empty)_                   | status            | Report state and width, change nothing                                                                                   |
| exactly `status`            | status            | Report state and width, change nothing                                                                                   |
| exactly `on` / `off`        | mode              | `off` → plain Claude Code behavior for the rest of **this** session · `on` → back to orchestrating at the last width set |
| exactly an integer `N`      | width             | Set the parallel width for this session, change nothing else                                                             |
| integer `N` **+ more text** | width + objective | Set the width, then run the rest as an **objective run** (below)                                                         |
| anything else               | objective         | An **objective run** at the current width                                                                                |

**A control word counts only as the whole argument.** `/orca off` is the mode command; `/orca off-by-one in the
paginator` is an objective, because "off" is not the entire string. Same for `on` and `status`. An objective that
genuinely starts with a bare control word gets rephrased, not guessed at.

**An objective never starts with another slash command.** Claude Code expands stacked skills at the start of a
message, so `/orca /review src/auth` loads _both_ skills and hands `src/auth` to each — orca never sees the `/review`
as its objective. Write the objective as prose and name the skill inside it ("review src/auth against …"); the run
delegates it either way.

**The width in `/orca <N> <objective>` is a session setting like any other** — it does not snap back when the run
ends, and it follows the persistence rule below. `/orca 5` puts it back.

**This invocation's argument:** $ARGUMENTS

## State

**On by default, width 5.** Every session starts orchestrating; there is no activation step. The width is the only
number to think about, and only if the default is wrong for the task.

**Off is a command, never a default.** The next session orchestrates again, because nothing carries `off` forward —
not this file, not CLAUDE.md, not `SCRATCHPAD.md`. Only a non-default _width_ is worth persisting: write it to
`SCRATCHPAD.md` → _Current Work_ as `**Orca** — width <N> (<date>)` so a compaction cannot lose it. **A line there is
authority, not staleness** — obey it and say in one sentence that the width came from the scratchpad; the user has
`/orca 5` if it is wrong. No line means width 5. (Correcting the line to the default instead would throw away the one
thing it exists to protect: a same-day compaction and a same-day earlier session are indistinguishable from the date.)

## The contract

1. **Every unit of task work is delegated. No exception.** Reading a file for its content, searching, planning,
   editing, writing tests, running checks, reviewing — all of it happens in a subagent, including the units that
   would plainly be faster done directly. "Too small to delegate" is not a judgment this mode makes; `/orca off` is.
2. **Each assignment names a role, from the roster in CLAUDE.md → _Subagents_.** The role is the lens the brief
   frames — `architect`, `implementer`, `reviewer`, `domain`, `product`, `docs`, `security` — and the wave report
   names it. Seat the roles the change actually calls for, never a standing panel and never two agents with the same
   lens: agreement between identical lenses is not evidence. **A code change always seats `reviewer`, and never the
   agent that wrote it** — a fresh reading beats an author verifying the intent it already holds.
3. **The orchestrator keeps four things,** and all four are decisions rather than work: decomposition and assignment ·
   read-only verification of what comes back (`git status`, `git diff`, reading the changed files) · integration and
   its gates (commit, push, `/pr`, `/ci`, `/rollback`, merge, release dispatch) · the report to the user. A gate
   handed to a subagent is a gate that answers itself — the subagent holds the tool and has nobody to ask.
4. **Subagents inherit the orchestrator's quality — by omission, not by setting.** Leave the model parameter off and
   the subagent runs the session's model; leave the effort / reasoning parameter off, where the surface has one, and
   it runs the session's effort. Never pass a smaller model, never pass a lower effort, never route work to a cheaper
   agent to save tokens. Two places where inheritance does not happen on its own: a repo-local `.claude/agents/*.md`
   whose frontmatter pins a `model:` overrides it — pass the session's model explicitly for that agent type or do not
   use it; and `subagent_type: fork` always inherits the parent model whatever else is passed.
5. **Width: 5 in parallel unless overridden.** Independent assignments go out in a single message, up to N; the rest
   waits for a free slot. Dependent work is sequenced — never parallelized in the hope that the order works out.
6. **Disjoint write scopes.** Two subagents in the same wave never hold write access to the same file. Split by file,
   or sequence, or give each one its own git worktree (`isolation: "worktree"`) where the surface offers it. In this
   repo `settings_ui.py` and `app.py` are the files two assignments most easily collide on.
7. **Assignments are self-contained.** A subagent has no conversation history: name the goal, the exact paths, what
   was already tried, the skill file to follow if one applies, the constraints, and what the return value must
   contain. Ask for a structured return — files touched, what changed, what was verified, what is still open.
8. **Verify the diff, not the summary.** A subagent's report describes intent. After every write-capable agent, read
   the actual change. A wave is done when the orchestrator has looked at what it produced, not when the agent says so.

## Objective runs — `/orca <objective>`

An objective run is the contract above pointed at one stated outcome instead of at whatever the current turn asks
for. It adds no mechanism: it is the ordering of ones this project already has.

1. **Restate the objective in one sentence, and say what is out of scope.** Both go to `SCRATCHPAD.md` →
   _Current Work_ under `**Orca objective** — <one sentence> (<date>)`, with the out-of-scope list under it. That is
   what survives a compaction; the conversation is not.
2. **Cut it into steps, each with an observable result** — a check that passes, a file that exists, a command that
   exits 0. A step whose result cannot be observed is not a step, it is a hope.
3. **Per step: build, then review.** The implementer wave, then a `reviewer` seat that wrote none of it. Verify the
   diff yourself before the next step starts (contract 8).
4. **One overall review over the combined diff at the end,** by an agent that wrote none of it. A boundary that
   moved, a duplication spread over two steps, an interface quietly widened in step four — none of that is visible in
   any single-step review.
5. **Close through `/done`.**

**Three stop conditions end the run rather than bend it:** the same defect three times → `.claude/skills/stuck/SKILL.md` ·
the objective turns out to be the wrong one → say so and stop · a decision only the user can make → stop, with the
block from `CLAUDE.md → Handoff Prompt`.

**Step 0 — is this an objective run at all?** Before restating anything, check the objective against the selection
table in `CLAUDE.md → Handoff Prompt` — that table is canonical and is not restated here. Its goal row fires when the
**user wrote the stop condition** (`until …`, `bis …`), that condition is one your own output demonstrates, and nothing
is left to decide; how long the work will take is not the axis, and an objective that merely looks large is still
this. Meets all three → it is a `/goal`, not this: say so in one sentence, hand over the ready-to-send
`/goal <done-condition>` as its own message — the condition alone, within the character cap that section states,
never the prompt block behind it — and stop, **at the start, not after a run that was going to end there anyway.**
A user who typed `/orca` is asking for the work, not for this command; naming the better one costs them one line
and saves the run. Anything that fails one of those three tests is an objective run, so continue.

**What an objective run is not: `/goal`.** It carries the objective through the run it starts. Claude Code's `/goal`
is a _cross-turn_ evaluator — a session-scoped prompt Stop hook that re-checks a condition after every turn — and no
skill can set one: a built-in slash command is not model-invocable, and a Stop hook written into settings mid-session
does not reach the session that wrote it. The two never both get sent: a `/goal` turn orchestrates anyway, because
that is this project's default, and only a non-default width needs `/orca <N>` sent ahead of it.
**Never generate a skill named `goal` to close this gap** — it would shadow the built-in.

## Rules

- **A failed subagent is a re-assignment, not a takeover.** Sharpen or split the assignment and send it again; the
  orchestrator never "just fixes it quickly" itself. Third failure on the same unit → `.claude/skills/stuck/SKILL.md`.
- **Unattended runs** (`CLAUDE_CODE_REMOTE=true`) keep the mode and keep the ban on ending a turn with a question —
  subagents cannot ask either, so the assignment states the assumption it runs under. See `CLAUDE.md` → _Autonomy_.
  An objective run there states its assumption and finishes; it never stops on the decision it cannot get answered.
- **Skills stay in force.** A skill the user invokes while the mode is on is followed by the orchestrator; the work
  that skill asks for is what gets delegated.
- **This is the subagent contract, nothing wider.** It does not by itself authorize heavier multi-agent machinery
  (workflow-style fan-out over dozens of agents) — that stays an explicit user request.
- **Cost is real and already decided.** The mode multiplies token use and adds latency per unit of work; that buys
  parallel width and a main context that stays clean. It is the project's default, so do not re-litigate it per task
  and do not announce it every turn — mention it only if the user asks or if a task is genuinely the wrong shape for
  it, and then say so once with the recommendation, not as a question.

## Report

Close every wave with:

```
### Orca — wave <n> (<k>/<N> parallel)
| Assignment | Role | subagent_type | Scope | Result | Verified |
|------------|------|---------------|-------|--------|----------|
| <what> | <role from the roster> | <type> | <files> | done / partial / failed | diff read ✅ / ❌ |

Next: <next wave / integration step / "nothing — reporting to user">
```

An objective run adds one line above the table, so the run's own state is never inferred from the wave count:

```
objective: <one sentence> — step <i>/<n> · <on track | stopped: stuck | stopped: wrong objective | stopped: decision needed>
```
