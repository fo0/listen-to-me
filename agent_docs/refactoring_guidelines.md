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
> **Stamp:** re-measured 2026-09-13 at `1a12941` — `main`'s tip, and the base of the housekeeping branch that re-ran the line. That branch adds no commit under `src/`, so its last commit measures this same tree; nothing it gives a figure for was uncommitted or changed after the measurement. That commit is the check: if `git log 1a12941..HEAD -- src/listen_to_me/` shows a commit touching a file this block gives a figure for, these figures are behind and the line above has to be re-run. The previous stamp (`68b279f`, 2026-09-10, end of `claude/overlay-cursor-anchor`) is what that check caught: three commits landed in `src/listen_to_me/` after it, and two figures were behind.
>
> **Measure at the end of a branch, not in its docs commit:** the `~5576` this block claimed for `selftest.py` was correct when it was written and 1405 lines short one commit later, because the very next commit on the same branch added the two features' regression guards. A number taken before a branch's last commit describes a file that no longer exists — which is the failure this paragraph exists to prevent, and it still happened. It then happened again one branch later: the figures were right at the end of #194/#195, #196 grew all four files, and #196's docs pass carried the old numbers over instead of re-running the line — caught in review, not by the paragraph. Which is why the command is now spelled out rather than described, and why the stamp names a commit you can diff against: reading the lesson has twice not been enough.

- **`settings_ui.py` (5738 lines)** — the clearest split target: one module per settings page (General / Engine / Audio / Overlay / Integrations / Assistant / History / Updates / Help) plus shared card/row helpers. The Home page already lives in `home_page.py`. Do it only when a change to the settings window is being blocked by the size. Tracked in `BACKLOG.md` (#1).
- **`selftest.py` (10160 lines)** — grows with every regression guard, which is the point; split by check group only if navigating it starts to cost more than it saves.
- **`app.py` (2114 lines)** — well over the ~500 bar, and the `_handle` dispatch did keep growing (#191 routes every recording branch by its source). Keep new behavior in the component modules, not in `App`; an extraction must keep `_handle`, `_register_hotkey` and `_toggle_hotkey_pause` callable **unbound on a stub**, which is how the headless self-test drives them. Tracked in `BACKLOG.md` (#40).
- **`overlay.py` (1435)** and **`home_page.py` (775)** — both kept climbing past the re-look mark set here on 2026-08-31 (~1015 / ~519) and are now tracked in `BACKLOG.md` (#39) rather than assessed as cohesive. **`theme.py` (648)** is just over the bar and cohesive; no split planned. `voice_mic_widget.py` (488) is approaching it: the painting is one animation and splitting it would only move the state flags away from the paths that read them — revisit if a third overlay mode is added.

## Verification after a refactor

1. `python -m compileall -q src scripts`
2. `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"`
3. If deps are installed: `python -m listen_to_me --selftest`
4. Manually confirm the affected flow still works (record → transcribe → insert, or the touched settings page).
5. Re-run the `wc -l` line above and update the figures **in the branch's last commit** — a refactor changes them by definition.

<!-- Generated by claude-code-optimizer v1.42.0 -->
