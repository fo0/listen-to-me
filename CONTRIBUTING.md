# Contributing to Listen To Me

Thanks for your interest in improving Listen To Me! This is a small, local-first
desktop app (PySide6 + faster-whisper). Contributions of all kinds — bug
reports, fixes, features, docs — are welcome.

## Getting started

Requires **Python 3.10+**. A virtual environment is recommended:

```bash
git clone https://github.com/fo0/listen-to-me
cd listen-to-me
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .          # or: pip install -r requirements.txt
python -m listen_to_me    # run from source (add src/ to PYTHONPATH if not installed)
```

A quick, dependency-free check that the CLI works:

```bash
python -m listen_to_me --version   # prints the version, no Qt import
```

## Before you open a pull request

There is **no linter, formatter, type-checker, or test framework** for the
Python code — and please don't add one without discussing it first.
Verification is the same two checks CI runs on every pull request:

```bash
# 1. Syntax-compile every source file (fast, no dependencies)
python -m compileall -q src scripts

# 2. Headless Qt UI smoke test (needs PySide6 + Pillow)
QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"
```

Both must pass. The full packaging self-test (`python -m listen_to_me --selftest`)
additionally needs all runtime dependencies installed.

Markdown is the one exception to "no formatter": if your change touches any
`.md` file, `docs-format.yml` checks it with Prettier. Format it before
pushing — no install needed, and there is no `package.json` to add it to:

```bash
npx --yes prettier@3.9.6 --write "**/*.md"
```

Keep the version in sync with the one pinned in
`.github/workflows/docs-format.yml`.

## Coding conventions

- `from __future__ import annotations` at the top of every module.
- Double quotes, 4-space indentation, trailing commas in multi-line literals,
  line length ~100. No formatter enforces this — match the surrounding style by
  hand (the code is de-facto black-style).
- `snake_case` for modules/functions, `PascalCase` for classes, a leading `_`
  for private helpers.
- Type hints on public signatures; use `X | None` unions (3.10+).
- Comments and docstrings in **English**; docstrings explain _why_, not just
  _what_.
- Use `logging` (one logger per module), not `print` — except CLI output in
  `main()`.
- Keep heavy/optional imports (Qt, `sounddevice`, `pynput`, `faster_whisper`,
  `numpy`) **lazy** — import them inside the functions that use them, not at
  module top, so `--version` / `--selftest` stay fast and headless.

### Threading

All GUI / tray / overlay work happens on the Qt main thread. **Never touch Qt
from a worker thread** — background threads communicate one-way through the
event queue via `App.post(...)` / `App.notify(...)`, and a main-thread timer
drains it. Mutating Qt objects off the main thread crashes the app.

## Dependencies

New runtime dependencies are added only after discussion — they bloat the
one-file Windows build. Keep `requirements.txt` and `pyproject.toml` in sync
whenever a dependency changes; a dep with C extensions or data files may also
need a `--collect-all` entry in `.github/workflows/release.yml`.

## Commits & pull requests

- Work on a feature branch; don't commit straight to `main`.
- Commit messages: imperative mood, capitalized subject (~50–72 chars), e.g.
  `Add in-app Help page`. This is **not** Conventional Commits — no `feat:` /
  `fix:` prefixes required. Reference issues/PRs with `#N`, and add a short body
  explaining _why_ for non-trivial changes.
- Open the pull request against `main`. CI (`ci.yml`) runs the fast check job
  (syntax + offscreen Qt smoke) automatically; the Windows build and GitHub
  Release live in a separate workflow (`release.yml`) that is dispatched
  manually and only from `main`.

## Reporting bugs

Open a GitHub issue with your OS, Python version, what you did, what you
expected, and what actually happened. Logs are written to a rotating file in the
config directory (tray icon → _Open config folder_) and can help a lot.
