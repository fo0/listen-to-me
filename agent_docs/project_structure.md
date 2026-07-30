# Project Structure — full tree

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps the two-level directory view; this file lists the modules and their roles at a glance.

```
src/listen_to_me/     # The single application package — flat, no sub-packages
scripts/              # make_icon.py — generates the .ico PyInstaller bundles
.github/workflows/    # ci.yml (check job: compileall + Qt smoke, on PR/push)
                      # release.yml (manual dispatch: Windows exe + GitHub Release, main only)
docs/                 # ARCHITECTURE.mmd (+ .svg), adr/, research/
agent_docs/           # Agent process docs (this file, review, backlog, memory, budget, …)
.claude/skills/       # done, pr, review, security-review, rollback, ci, stuck
```

## `src/listen_to_me/` modules

Grouped by role. Full behavioral notes: `agent_docs/key-patterns.md`.

| Group | Modules |
|-------|---------|
| Entry points | `__main__.py`, `__init__.py` (version stamped by CI) |
| Core | `app.py` (state machine + event queue), `config.py`, `singleinstance.py` |
| Audio & transcription | `audio.py`, `transcriber.py`, `transcriber_openvino.py`, `transcriber_parakeet.py` |
| Input / output | `hotkeys.py`, `keymap.py`, `injector.py`, `livetype.py` |
| UI | `settings_ui.py`, `home_page.py`, `onboarding.py`, `widgets.py`, `overlay.py`, `voice_mic_widget.py`, `tray.py` |
| UI support | `theme.py`, `glyphs.py`, `icons.py`, `qtutil.py`, `choices.py`, `help_content.py` |
| Platform / system | `autostart.py`, `netutil.py`, `updater.py`, `integrations.py` |
| Data & extras | `history.py`, `assistant.py` |
| Verification | `selftest.py` (`gui_smoke()` = the CI subset), `diagnostics.py` (Settings self-test engine) |

## Notable sizes (2026-07-30)

`settings_ui.py` ~2700 lines and `selftest.py` ~1900 lines are the two files far past the size guideline; `app.py` (~720) and `theme.py` / `home_page.py` (~550 / ~530) are over it. Split plans: `agent_docs/refactoring_guidelines.md`.

## Finding things

There is no sub-package layout to navigate — use `glob`/`grep` over `src/listen_to_me/`. The table above is a map, not an index; it goes stale faster than the code.
