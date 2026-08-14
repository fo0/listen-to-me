# Loop — default maintenance pass

One pass per iteration, in this order. Stop at the first item with real work, finish it, and report in one line. If
nothing is pending, say so in one line and do not invent work.

1. **Unfinished work from this session** — `SCRATCHPAD.md` holds the current task and open questions. Continue it.
2. **This branch's pull request** — new review comments, a failed CI run, or a merge conflict. Red build →
   `.claude/skills/ci/SKILL.md`. Comments and merge state → `.claude/skills/pr/SKILL.md`. Address them; do not just
   describe them.
3. **Verification** — the full gate for this repo (there is no lint, typecheck or test framework):

   ```bash
   python -m compileall -q src scripts
   QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
     python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"
   npx --yes prettier@3.9.6 --check "**/*.md"   # only when Markdown changed
   ```

   Anything red is the work for this iteration.

4. **Backlog** — the top item in `BACKLOG.md` if it is small and self-contained. Anything larger stays where it is.

Rules for every iteration:

- No new initiatives outside this list.
- Irreversible actions — push, merge, branch deletion, release dispatch — only when they continue something this
  session already authorized.
- Never add a linter, formatter or test framework to make a check pass — that is a dependency decision needing user
  sign-off (`CLAUDE.md` → _Commands_).
- Nothing changed → one line, no summary of what was checked.
- Open point that needs a human → `BACKLOG.md`, then keep going. See `CLAUDE.md` → _Autonomy_.
