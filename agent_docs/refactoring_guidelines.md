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

> Figures below were measured on 2026-08-12 — they drift with every commit. Re-measure with `wc -l src/listen_to_me/*.py | sort -rn | head` instead of trusting a copied number.

- **`settings_ui.py` (~3175 lines)** — the clearest split target: one module per settings page (General / Whisper / Audio / Overlay / Integrations / Assistant / History / Updates / Help) plus shared card/row helpers. The Home page already lives in `home_page.py`. Do it only when a change to the settings window is being blocked by the size. Tracked in `BACKLOG.md`.
- **`selftest.py` (~2945 lines)** — grows with every regression guard, which is the point; split by check group only if navigating it starts to cost more than it saves.
- **`app.py` (~970 lines)** — over the ~500 bar. Keep new behavior in the component modules, not in `App`; extract the event `_handle` dispatch only if it keeps growing.
- **`theme.py` (~580)** — just over the bar, cohesive; no split planned. `home_page.py` (~475) dropped back under the bar and is no longer a candidate.

## Verification after a refactor

1. `python -m compileall -q src scripts`
2. `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"`
3. If deps are installed: `python -m listen_to_me --selftest`
4. Manually confirm the affected flow still works (record → transcribe → insert, or the touched settings page).
