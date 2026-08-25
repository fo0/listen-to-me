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

- `updater follows the insecure-SSL switch` — the update path verifies by default and stops verifying while `insecure_ssl` is on, in both cases keeping the post-redirect host check and the explaining `UpdateTrustError` (ADR-0006, superseding ADR-0002). A hardcoded `verify=` on either side fails the check.
- `disabled buttons look disabled` — renders each button variant and asserts the _surface_ colour changes when disabled. A plain image `!=` passed on nothing but a vanishing focus ring, so the check compares the fill.
- `theme assets stay out of shared temp` — the directory holding the generated chevron SVGs must be owned by the current user and not group- or world-reachable. It used to fall back to `<system temp>/listen-to-me`, one predictable path shared by every account on the machine (#130).
- `activation port is exclusive` — a second socket must not be able to bind the activation port while the listener is alive. It asserts the outcome rather than the socket option, because the option that produces it differs per platform (see the `SO_REUSEADDR` entry in `MEMORY.md`).
- History rows with a `1e300` timestamp — stored values are untrusted at render time.
- Replaced History rows end up parentless — detach before `deleteLater`, or ghost widgets keep painting.
- No settings page is wider than its scroll viewport — one long combo/label item otherwise clips every card at the right edge.

## Adding a check

Prefer extending `selftest.py` over introducing a test framework. Adding pytest is a dependency + config change and needs explicit user approval (see _User Preferences_ in `MEMORY.md`).

Keep new pure logic Qt-free where practical — that is what makes it exercisable by `gui_smoke` on a headless machine.

## Constraints (autonomy + zero-cost)

Agent-runnable, zero-cost, deterministic — the binding wording lives in one place: `agent_docs/review_process.md → Test execution constraints`. It applies unchanged to every check added here.
