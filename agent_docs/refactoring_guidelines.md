# Refactoring Guidelines

Refactoring does NOT happen automatically. Only when:

- Explicit user request
- Repeated code smells across multiple files in review
- Feature implementation is significantly hindered by code structure

## Principles

1. **No over-engineering** — Only refactor what provides measurable benefit.
2. **AI-optimized structure** — Code is primarily maintained by AI agents:
   - Explicit > implicit (easier for AI to parse)
   - Focused files — split around ~300 lines, strongly recommended by ~500 (Python convention here)
   - Descriptive names > clever abstractions
   - Consistent patterns across similar components (AI can pattern-match)
   - Inline comments/docstrings for non-obvious decisions (AI has no project history context) — this codebase already documents _why_ heavily; keep that up
3. **Follow framework idioms** — Use PySide6/Qt best practices, no custom abstractions.
4. **Incremental** — Small chunks, each goes through the full review cycle.
5. **Extract, don't abstract** — Prefer extracting into focused modules over abstract base classes.
6. **Verify** — Every refactoring step must pass the automated checks (`compileall` + Qt smoke) before the next one begins.

## Project-specific invariants to preserve during any refactor

- **Threading model:** all Qt/tray/overlay work stays on the main thread; workers only `App.post`/`App.notify`. A refactor must not move GUI calls into a worker.
- **Lazy heavy imports:** don't hoist Qt/`sounddevice`/`pynput`/`faster_whisper`/`numpy` to module scope — `--version`/`--selftest` and `gui_smoke` depend on them being lazy.
- **Qt-free modules stay Qt-free:** `icons.py`, `keymap.py`, `help_content.py` (and the pure parts of `qtutil.py`/`selftest.py`).
- **Config access via `cfg["key"]`** and the `DEFAULTS` deep-merge; new keys must land in `DEFAULTS`.
- **Fail-soft boundaries:** broad `except Exception` + `log.exception` + `notify` at user-facing boundaries — don't remove fallbacks (CPU fallback, clipboard restore, mute reset on quit).

## Current candidates (assessment, not a mandate)

> **Never copy a figure out of this block — regenerate it.** One line does it:
>
> ```bash
> wc -l src/listen_to_me/*.py | sort -rn | head
> ```
>
> **The branch's _last_ commit is the one that has to run it**, and the stamp below has to say when it was run. Anything earlier — a docs commit in the middle of a branch, a number carried over from the previous sweep — measures files the branch then keeps changing, and lands here already wrong.
>
> **Stamp:** re-measured 2026-10-06 at `086718f`, the end of `claude/busy-mayer-oohdpn` (#286). The branch's last commit after it touches only `choices.py` under `src/` — a comment, and a file this block gives no figure for — so these figures describe that commit's tree too. That commit is the check: if `git log 086718f..HEAD -- src/listen_to_me/` shows a commit touching a file this block gives a figure for, these figures are behind and the line above has to be re-run. The previous stamp (`dc45c60`, 2026-10-04) is what that check caught this time: `main` and #286 together moved five figures — `selftest.py` by 1716 lines, `settings_ui.py` by 189, `app.py` by 89, `home_page.py` by 19, `overlay.py` by 16. Before it, the stamp `caafe06` (2026-09-30) was caught: four commits landed in `src/listen_to_me/` after it, and three figures were behind — `selftest.py` by 143 lines, `app.py` by 30, `settings_ui.py` by 25. Before that, `6482fa3` (2026-09-27): nine commits landed in `src/listen_to_me/` after it, and five figures were behind — `selftest.py` by 210 lines, `app.py` by 89, `settings_ui.py` by 81, `theme.py` by 8, `home_page.py` by 3. The three stamps before that caught the same drift: `cc31097` (2026-09-15) 23 commits and five stale figures, `1a12941` (2026-09-13) six commits and three stale figures, `68b279f` (2026-09-10, end of `claude/overlay-cursor-anchor`) three commits and two stale figures.
>
> **Measure at the end of a branch, not in its docs commit:** the `~5576` this block claimed for `selftest.py` was correct when it was written and 1405 lines short one commit later, because the very next commit on the same branch added the two features' regression guards. A number taken before a branch's last commit describes a file that no longer exists — which is the failure this paragraph exists to prevent, and it still happened. It then happened again one branch later: the figures were right at the end of #194/#195, #196 grew all four files, and #196's docs pass carried the old numbers over instead of re-running the line — caught in review, not by the paragraph. Which is why the command is now spelled out rather than described, and why the stamp names a commit you can diff against: reading the lesson has twice not been enough.

- **`settings_ui.py` (6433 lines)** — the clearest split target: one module per settings page (General / Engine / Audio / Overlay / Integrations / Assistant / History / Updates / Help) plus shared card/row helpers. The Home page already lives in `home_page.py`. Do it only when a change to the settings window is being blocked by the size. Tracked in `BACKLOG.md` (#1).
- **`selftest.py` (13212 lines)** — grows with every regression guard, which is the point; split by check group only if navigating it starts to cost more than it saves.
- **`app.py` (2452 lines)** — well over the ~500 bar, and the `_handle` dispatch did keep growing (#191 routes every recording branch by its source). Keep new behavior in the component modules, not in `App`; an extraction must keep `_handle`, `_register_hotkey` and `_toggle_hotkey_pause` callable **unbound on a stub**, which is how the headless self-test drives them. Tracked in `BACKLOG.md` (#40).
- **`overlay.py` (1505)** and **`home_page.py` (811)** — both kept climbing past the re-look mark set here on 2026-08-31 (~1015 / ~519) and are now tracked in `BACKLOG.md` (#39) rather than assessed as cohesive. **`theme.py` (656)** is just over the bar and cohesive; no split planned. `voice_mic_widget.py` (488) is approaching it: the painting is one animation and splitting it would only move the state flags away from the paths that read them — revisit if a third overlay mode is added. `choices.py` (510) crossed it with #286's Parakeet model list and stays cohesive (one module of dropdown data); `onboarding_engine.py` (484) was split out of `onboarding.py` by #286 and is the next file to watch.

## Verification after a refactor

1. `python -m compileall -q src scripts`
2. `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"`
3. If deps are installed: `python -m listen_to_me --selftest`
4. Manually confirm the affected flow still works (record → transcribe → insert, or the touched settings page).
5. Re-run the `wc -l` line above and update the figures **in the branch's last commit** — a refactor changes them by definition.

<!-- Generated by claude-code-optimizer v1.56.0 -->
