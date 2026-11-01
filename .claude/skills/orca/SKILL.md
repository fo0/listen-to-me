---
name: orca
description: "Orchestrator mode, this project's default working mode. Short units the main agent does itself; long waits, bulk reads and multi-file work go to role-framed Opus seats, at most 5 in parallel. '/orca <objective>' or '/orca <N> <objective>' runs a delegated objective: steps, a review each, one overall review. Load it for that, for the contract, on '/orca', 'orca mode', 'orchestrator mode', 'orca an/aus', or a question about the width. '/orca off': plain behavior for this session."
argument-hint: "[on|off|status|N] [objective]"
metadata:
  origin: claude-code-optimizer
---

# Orca — Orchestrator Mode

## When to Use

- `/orca` (reports state and width) · `/orca on|off|status` · `/orca 10` — the user asks what the mode is set to, or changes it
- `/orca <objective>` · `/orca <N> <objective>` — an objective to carry through a delegated run, optionally at a stated width
- "orca mode", "orchestrator mode", "orca an/aus", "ab jetzt delegieren", "delegate more"
- Session start, when `SCRATCHPAD.md` still carries an Orca line from an earlier session or from before a compaction

Not this skill: choosing the seat for one assignment while already orchestrating. That is the `description` of each
seat in `.claude/agents/opus-*.md`; the roles and their seat criteria are in `CLAUDE.md → Subagents`.

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

**The width is 1 to 10.** A number outside that range sets nothing: say so in one line and keep the current width
(an objective after it still runs).

**A control word counts only as the whole argument.** `/orca off` is the mode command; `/orca off-by-one in the
paginator` is an objective, because "off" is not the entire string. Same for `on` and `status`. An objective that
genuinely starts with a bare control word gets rephrased, not guessed at.

**An objective never starts with another slash command.** Claude Code expands stacked skills at the start of a
message, so `/orca /basic-review src/auth` loads _both_ skills and hands `src/auth` to each — orca never sees the `/basic-review`
as its objective. Write the objective as prose and name the skill inside it ("review src/auth against …"); the run
delegates it either way.

**The width in `/orca <N> <objective>` is a session setting like any other** — it does not snap back when the run
ends, and it follows the persistence rule below. `/orca 5` puts it back.

**This invocation's argument:** $ARGUMENTS

## State

**On by default, width 5.** Every session starts orchestrating; there is no activation step. The width is the only
number to think about, and only if the default is wrong for the task. A compaction summary that says to carry on
directly changes none of this: the mode and a width line in `SCRATCHPAD.md` hold after it as before.

**Off is a command, never a default.** The next session orchestrates again, because nothing carries `off` forward —
not this file, not CLAUDE.md, not `SCRATCHPAD.md`. Only a non-default _width_ is worth persisting: write it to
`SCRATCHPAD.md` → _Current Work_ as `**Orca** — width <N> (<date>)` so a compaction cannot lose it. **A line there is
authority, not staleness** — obey it and say in one sentence that the width came from the scratchpad; the user has
`/orca 5` if it is wrong. No line means width 5. (Correcting the line to the default instead would throw away the one
thing it exists to protect: a same-day compaction and a same-day earlier session are indistinguishable from the date.)

**`/orca off` stops no running agent.** Agents already out finish or get cancelled — the orchestrator brings them to
one of the two and says which; only new work runs plain.

## The contract

1. **Delegate only what waits long, reads raw material in bulk or implements across files; do the rest yourself.**
   A unit goes out when it is at least one of these: it waits long (CI, deploy, build, a long test run) · it reads a
   lot of raw material — logs, transcripts, many files — and only its result counts · it is real implementation
   across several files or repos. A unit is short when it takes about five tool calls without a wait, writes at most
   one file and reads nothing the main context does not need afterwards — a git status, a short search, one command,
   a small edit, a file already in context. That one is yours: each subagent pays the always-loaded set again, so a
   unit smaller than that costs more delegated than done. **A change you wrote yourself still gets its `reviewer`**
   (item 2).
2. **Each assignment names a role, from the roster in CLAUDE.md → _Subagents_.** The role is the lens the brief
   frames — `architect`, `implementer`, `reviewer`, `domain`, `product`, `docs`, `security` — and the wave report
   names it. Seat the roles the change actually calls for, never a standing panel and never two agents with the same
   lens: agreement between identical lenses is not evidence. **A code change always seats `reviewer`, and never the
   agent that wrote it** — a fresh reading beats an author verifying the intent it already holds. A unit that judges
   no code — a search, a log read, a pipeline watch — applies no lens and names none.
3. **The orchestrator keeps five things:** decomposition and assignment · the short units of item 1 ·
   read-only verification of what comes back (`git status`, `git diff`, reading the changed files) · integration and
   its gates (commit, push, `/pr`, `/ci`, `/rollback`, merge, release dispatch) · the report to the user. A gate
   handed to a subagent is a gate that answers itself — the subagent holds the tool and has nobody to ask. It stays
   responsive while the seats work: a wait runs in the background, never as a call that blocks the chat.
4. **Every seat is a typed Opus agent; its effort is chosen, never inherited.** A subagent runs as one of the four
   seats in `.claude/agents/` — `opus-high`, `opus-xhigh`, `opus-max`, `opus-medium` — each `model: opus` with a
   fixed `effort:`, and each description says when it is the one. `opus-high` is the default and the floor, for
   short work as much as long; `opus-xhigh` only for heavy work; `opus-max` only as an exception, with a one-line
   reason in the assignment; `opus-medium` is the one seat below the floor and only watches a pipeline — no merge, no
   change, no decision. Classify before every spawn; in doubt `opus-high`, not `opus-xhigh`. **Never a type whose
   level the session decides:** `general-purpose`, `Explore`, `Plan` and `subagent_type: fork` inherit the session's
   effort, so none of them is a seat; neither is a `model` or `effort` passed on the call, which would override the
   seat's own — never `sonnet`, never `haiku`. A repo agent of its own is a seat only when its frontmatter fixes
   `model: opus` and `effort: high` or above. The same floor holds for `opts.effort` in a workflow script. **No seat in
   the agent list** — the files are not written yet, or the session loaded its agents before they were — is the one
   case where the call carries the level: `general-purpose` with `model: opus` and the seat's `effort` on the call —
   the call's `model` also beats a host's `CLAUDE_CODE_SUBAGENT_MODEL`; where the call takes no `effort`, the
   orchestrator does the unit itself. Below
   `high` too many units came back wrong (owner, 2026-10-05); `xhigh` where `high` does is waste (2026-10-28).
5. **Width: 5 in parallel unless overridden.** Independent assignments — each in its own repo or worktree, on its own
   port — go out in a single message, up to N; the rest runs in waves as slots free up. Only what shares a file or a
   port is sequenced, and dependent work — never parallelized in the hope that the order works out. Cut along clean
   seams, not to fill N. An analysis that prepares a decision runs in parallel with the implementation that does not
   wait for it.
6. **Disjoint write scopes.** Two subagents in the same wave never hold write access to the same file. Split by file,
   or sequence, or give each one its own `git worktree` under `tmp/wt-<repo>-<topic>` in the workspace that holds
   the repo — never inside the repo's own tree — and remove it once its push or PR is done. In this repo
   `settings_ui.py` and `app.py` are the files two assignments most easily collide on.
7. **Assignments are self-contained.** A subagent knows nothing of the chat: name the goal, the exact paths, the facts
   already known and what was already tried, the skill file to follow if one applies, the rules, and the return
   format. The project's rules still bind it — the `CLAUDE.md` files of user, workspace and repo — and the
   orchestrator answers for their being kept. The return is terse: result, evidence (path:line, command, PR), open
   points — no retelling.
8. **Verify the diff, not the summary.** A subagent's report describes intent. After every write-capable agent, read
   the actual change. A wave is done when the orchestrator has looked at what it produced, not when the agent says so.
9. **Only the current goal.** No curiosity assignment, no second agent clarifying what another already does, no
   backlog side topic — that waits for its own task. A subagent does not orchestrate: it delegates nothing further.

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
table in `CLAUDE.md → Handoff Prompt` — that table is canonical and is not restated here. Its goal row is the
**default** and fires when the stop condition is one your own output demonstrates and nothing is left to decide;
how long the work will take is not the axis, and an objective that merely looks large is still this. Meets it →
it is a `/goal`, not this: say so in one sentence, hand over **one** ready-to-send `/goal …` block on a single
line — the whole briefing behind the command, within the character cap that section states, never split in
two — and stop, **at the start, not after a run that was going to end there anyway.**
A user who typed `/orca` is asking for the work, not for this command; naming the better one costs them one line
and saves the run. An objective that trips one of that section's three disqualifiers is an objective run, so continue.
**Unattended** (`$CLAUDE_CODE_REMOTE=true`), nobody can paste a block: Step 0 does not apply, the objective runs, and a
decision only the user can make lands in the report instead of a stop (CLAUDE.md → _Autonomy_).

**What an objective run is not: `/goal`.** It carries the objective through the run it starts. Claude Code's `/goal`
is a _cross-turn_ evaluator — a session-scoped prompt Stop hook that re-checks a condition after every turn — and no
skill can set one: a built-in slash command is not model-invocable, and a Stop hook written into settings mid-session
does not reach the session that wrote it. The two never both get sent — and there is no exception, not even width:
a `/goal` turn orchestrates anyway, because that is this project's default, and a non-default width is a sentence
_inside_ that one line (`work at width 3`), never an `/orca <N>` sent ahead of it. A handoff is one paste.
**Never generate a skill named `goal` to close this gap** — it would shadow the built-in, which is the defect
v1.30.0 removed.

## Rules

- **A failed subagent is a re-assignment, not a takeover — one seat higher.** An assignment that failed or came back
  unclear is not sent again as it was: sharpen or split it and give it to the next seat up — `opus-high` →
  `opus-xhigh`, and an `opus-xhigh` assignment that fails again → `opus-max` with its one-line reason; the
  orchestrator never "just fixes it quickly" itself. Third failure on the same unit →
  `.claude/skills/stuck/SKILL.md`.
- **Results reach the user only through you.** The user sees no subagent report, so pass on what matters. Never
  invent or anticipate a result: an agent still running is reported as running.
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
| <what> | <role from the roster> | <opus-* seat> | <files> | done / partial / failed | diff read ✅ / ❌ |

Next: <next wave / integration step / "nothing — reporting to user">
```

An objective run adds one line above the table, so the run's own state is never inferred from the wave count:

```
objective: <one sentence> — step <i>/<n> · <on track | stopped: stuck | stopped: wrong objective | stopped: decision needed>
```
