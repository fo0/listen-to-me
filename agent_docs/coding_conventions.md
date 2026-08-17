# Coding Conventions — full reference

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps the seven rules that bite most often; this file is the complete set.

## Language

- Comments and docstrings in **English**. Docstrings explain _why_, not just _what_ — this codebase leans heavily on them.
- UI strings are inline English literals. There is **no i18n framework**; don't introduce one without user approval.
- App log output is English.

## Module hygiene

- **`from __future__ import annotations`** at the top of every module.
- **Imports:** stdlib → third-party → local (`from .x import y`). Heavy or optional dependencies (Qt, `sounddevice`, `pynput`, `faster_whisper`, `numpy`, `openvino*`, `onnx_asr`) are imported **inside** functions so `--version` / `--selftest` stay fast and headless.
- **Logging, not print** — one `log = logging.getLogger(__name__)` per module. `print` is reserved for CLI output in `main()`.

## Naming

- Modules and functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- "Private" helpers are prefixed `_`.

## Types

- Type hints on public function signatures.
- `X | None` unions (Python 3.10+ syntax), not `Optional[X]`.

## Formatting

Double quotes, 4-space indent, trailing commas in multi-line literals, line length ~100.

**No formatter enforces this.** There is no black, no ruff, no isort — match the surrounding style by hand. Adding a formatter is a dependency + config change requiring user sign-off.

## Error handling

Broad `except Exception` at boundaries (this is a desktop app that must never crash), logged with `log.exception(...)`; user-facing failures surface through `App.notify(...)`. Never let a cleanup path leave a target app stuck muted — see `_quit` / `integrations.reset()`.

**Silent failure is the anti-pattern that has bitten this codebase most** — read a write back instead of assuming it worked (`autostart.enable`, `Config.save`), and never leave a failure as a no-op the user cannot see.

Silent failure is the anti-pattern this codebase has been bitten by most (autostart, tray icon, overlay): if a write can fail invisibly, read it back and report.

## File size

~300 lines → evaluate a split; ~500 lines → split strongly recommended. Known exceptions and the split plan: `agent_docs/refactoring_guidelines.md`.

## Threading

All Qt work on the main thread. Background threads communicate one-way through `App.post(...)` / `App.notify(...)`. See `agent_docs/key-patterns.md → Threading model`.
