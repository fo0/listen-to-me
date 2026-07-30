# Testing

Offloaded from `CLAUDE.md` (context budget). CLAUDE.md keeps framework + run command + layout; this file carries the detail.

## What exists

There is **no test framework** — no pytest, no unittest suite. Verification is the CI `check` job in `.github/workflows/ci.yml`, which runs two things:

```bash
python -m compileall -q src scripts        # syntax-checks every source file (fast, no deps)

QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
  python -c "import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())"
```

`gui_smoke()` is the dependency-light subset of `selftest.py` that CI can run from source. The full packaging self-test — `python -m listen_to_me --selftest` — needs every runtime dependency installed and is what verifies the built exe in `release.yml`.

## Structure

`src/listen_to_me/selftest.py` holds all checks. Each check is a small function that constructs the real widgets/objects offscreen and asserts an invariant. Adding a check means adding it there and wiring it into `gui_smoke()` (light checks) or the full self-test (checks needing heavy deps).

Existing regression guards worth knowing about, because they lock in real bugs:

- `updater forces TLS verification` — the updater must stay carved out of `insecure_ssl` (ADR-0002).
- `disabled buttons look disabled` — renders each button variant and asserts the *surface* colour changes when disabled. A plain image `!=` passed on nothing but a vanishing focus ring, so the check compares the fill.
- History rows with a `1e300` timestamp — stored values are untrusted at render time.
- Replaced History rows end up parentless — detach before `deleteLater`, or ghost widgets keep painting.
- No settings page is wider than its scroll viewport — one long combo/label item otherwise clips every card at the right edge.

## Adding a check

Prefer extending `selftest.py` over introducing a test framework. Adding pytest is a dependency + config change and needs explicit user approval (see *User Preferences* in `MEMORY.md`).

Keep new pure logic Qt-free where practical — that is what makes it exercisable by `gui_smoke` on a headless machine.

## Constraints (autonomy + zero-cost)

This codebase is built and verified by AI agents. Any check added must be:

- **Agent-runnable** with the two commands above — no manual setup, no credentials, no interactive login, no real microphone, no GPU.
- **Zero-cost** — no real API calls (paid LLMs, GitHub), no model downloads in the default check path, no audio hardware.
- **Deterministic** — fake clocks/random; mock `sounddevice` / `pynput` / `requests` / `faster_whisper` at the boundary.

Real-service smoke/E2E tests only on explicit user request — never part of the default check pipeline. Rationale: `agent_docs/review_process.md → Test execution constraints`.
