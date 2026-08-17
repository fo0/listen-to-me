# ADR-0007: PySide6 (Qt 6) is the UI toolkit

- **Status:** Accepted
- **Date:** 2026-08-17 (back-filled; the migration itself landed with #18, "UI design revamp")
- **Decider(s):** user
- **Tags:** ui, dependencies, packaging

## Context

The app started on the Python standard toolkit: Tkinter for the settings window plus `pystray` for the system-tray icon. That combination is dependency-free and ships with CPython, which is why it was the obvious first choice for a tray utility.

It stopped being adequate once the app grew past a single options dialog. Three things it could not deliver:

- **A tray app is mostly its tray.** `pystray` gives a menu and an icon and nothing else — no tooltip that follows state, no per-item enable/disable, no submenus. The status line, the running take's clock and the "Recent transcripts" submenu all need a real tray API.
- **The floating status icon is a frameless, translucent, always-on-top, click-through-to-drag window that runs a 60 fps custom animation.** Tkinter has no compositing story for that on Windows, and no canvas performance to animate a smoothed Catmull-Rom ring at that rate.
- **The settings window became a multi-page application window** with a sidebar, scrolling pages, a theme that follows the OS light/dark setting, and code-drawn icons. Tkinter has no native-looking widget set on Windows and no palette/stylesheet system to theme one.

The counter-force is real and was weighed: PySide6 is by far the heaviest dependency in the project and dominates the one-file Windows build.

## Decision

We will build the entire UI on **PySide6 (Qt 6)** — settings window, tray, overlay, wizard and dialogs — and accept it as the app's one large runtime dependency. Tkinter and `pystray` are removed rather than kept as a fallback: two UI stacks would double the surface of every UI change for a fallback nobody runs.

Everything that does not need a widget stays out of it. `icons.py`, `keymap.py`, `help_content.py`, `choices.py`, `diagnostics.py` and `progress.py` import no `QtWidgets`/`QtGui`, so they are testable on a headless machine, and Qt is imported lazily inside functions so `--version`, `--help` and the light self-test never pay for it.

## Consequences

### Positive

- A tray icon with a live tooltip, a state line, enable/disable per item and submenus — the tray is where most interactions with this app actually happen.
- The animated floating icon exists at all: frameless + `WA_TranslucentBackground` + `WindowStaysOnTopHint` + `WindowDoesNotAcceptFocus`, with a `QPainter` animation that never steals focus from the field the transcript is going into.
- An OS-following light/dark theme, and a settings window that looks native on Windows.
- `QSystemTrayIcon`, `QTimer` and the signal/slot mechanism give a single, well-defined main thread to marshal worker results onto — the app's central threading rule (`App.post`) is built on it.

### Negative / Trade-offs

- PySide6 is ~100 MB of wheels and the largest single contributor to the one-file exe.
- Qt has its own footguns that the codebase now has to defend against by convention, several of them recorded in `MEMORY.md` and its archive: wheel events reaching unfocused combo boxes, `QScrollArea` honouring a combo's longest item as a minimum width, `deleteLater` ghost widgets, QSS `:disabled` specificity, and translucent windows being dropped by Windows without Qt noticing.
- Headless CI needs `libgl1`/`libegl1`/`libxkbcommon0` and `QT_QPA_PLATFORM=offscreen` to run the UI smoke test.

### Neutral

- The Qt licence (LGPLv3 for PySide6) is compatible with this project's MIT licence as long as Qt is dynamically linked, which the official wheels are.

## Alternatives Considered

- **Stay on Tkinter + pystray** — rejected: no translucent always-on-top animation, no tray tooltip/state line, no OS theme.
- **A web UI in a local browser** — rejected: a dictation tool must never steal focus from the field it types into, and a browser window is exactly a focus-stealing window. It also cannot own a tray icon.
- **wxPython / GTK** — rejected: comparable weight to Qt without Qt's tray, painting and stylesheet story, and a worse Windows-first story.

## References

- Migration: PR #18 (`claude/ui-design-revamp-hnvrw2`).
- Qt-free module list and the lazy-import rule: `CLAUDE.md` → _Key Patterns_, `agent_docs/key-patterns.md`.
- Accumulated Qt traps: `MEMORY.md` → _Gotchas & Pitfalls_ and `agent_docs/memory_archive/`.
