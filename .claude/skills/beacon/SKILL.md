---
name: beacon
description: Dependency health check + update proposal through the beacon compatibility server. Trigger: /beacon, "check dependencies", "dependency updates", "update deps", or a scheduled/autonomous maintenance run. Starts from beacon-tracked Dependabot proposals when the project is GitHub-connected. Interactive sessions only PROPOSE updates; autonomous runs apply ONLY safe same-major (minor/patch) updates that beacon does not flag.
---

# beacon — check the stack, propose updates, apply only what is safe

Goal: use the beacon MCP tools (`compat_*`) to (1) pick up the Dependabot proposals beacon
already tracks, (2) check THIS project’s current stack, (3) propose dependency updates with
beacon’s verdicts attached, and (4) apply them — all of them only when the user picked
them; ONLY the safe subset when running autonomously.

## 1 · Verify identity (every run)

- Call `compat_whoami` and confirm it agrees with this repo ("fo0/listen-to-me", i.e.
  `git remote get-url origin`). Exactly two results are OK:
  - `project: "fo0/listen-to-me"` — a token bound to THIS project; or
  - `declares_project: true` — the shared master/onboarding token, bound to no project:
    then every call below MUST carry `project:"fo0/listen-to-me"` (`repo:` on report/observe),
    which is what attributes the run. This skill already passes it everywhere.
- Any other `project` → STOP and tell the user to re-onboard via beacon’s /onboard page;
  never write under another project’s token.

## 2 · Start from tracked proposals (GitHub-connected projects)

- Call `compat_proposals` with `project:"fo0/listen-to-me"`. **Expect proposals:** Dependabot runs
  weekly for `pip` and `github-actions` (`.github/dependabot.yml`, `agent_docs/deployment.md`).
  Skip when the tool is missing or `github.connected` is false.
- A returned proposal: treat it as a candidate for step 4 — prepared, not
  pre-approved (beacon’s verdict stays a veto, `compat_plan` below still applies) — and never
  merge or close that PR yourself; land the bump through this repo’s own branch/PR flow
  (steps 5–6) and record the outcome with `compat_decide` either way.

## 3 · Check the current stack

- Run `compat_check` with `project:"fo0/listen-to-me"` and the current stack. **There is no
  lock file here** (CLAUDE.md → Dependency Management): take the installed versions from
  `pip list --format=freeze` when a venv is available, otherwise the declared bounds in
  `requirements.txt` + `pyproject.toml`.
- Read: `summary`, flagged pairs in `results`, `derived` peer/advisory findings, and
  `recommendations` — beacon’s verified counter-proposals for flagged pairs.

## 4 · Collect update candidates

- Start from the open proposals of step 2 (when present) — that work is already prepared.
- List further available updates with the ecosystem’s tool: `pip list --outdated`.
- Classify every candidate:
  - **safe** — same-major semver bump (minor/patch) AND beacon flags nothing
    (`risky`/`broken`) for any affected pair.
  - **review** — major bump, non-semver tag change, a package this app is coupled to
    (PySide6, faster-whisper/ctranslate2, pynput, numpy, huggingface_hub), or beacon flags
    the target.
- Validate the intended set with `compat_plan` (`project`, current stack, `changes` as
  `{ecosystem, name, from, to}`): read the per-upgrade `upgrades` verdicts and `conflicts`,
  and prefer `recommendations` when a target lands on risky/broken.

## 5 · Interactive session (default)

Change nothing yet. Present a short proposal — safe updates (ready to apply), review
updates (each with beacon’s verdict + reason + recommendation), broken targets (do not
do; say why) — and apply exactly what the user picks. Then close the lifecycle (step 7).

## 6 · Autonomous run (only when explicitly running unattended)

Apply ONLY the safe class, as one small, reviewable batch:

- semver minor/patch within the SAME major — NEVER a major bump, a framework migration,
  or a non-semver tag change;
- drop any candidate whose plan roll-up verdict is `risky`/`broken` or that appears in
  `conflicts` (`unknown` is acceptable for a same-major bump);
- after bumping: run this repo’s only checks — `python -m compileall -q src scripts` plus the
  offscreen Qt smoke (CLAUDE.md → Commands). There is deliberately no linter/typechecker/test
  framework here; never add one to get a bump verified. On failure revert that bump and record
  it (`compat_decide` status:"failed" + note);
- keep `requirements.txt` and `pyproject.toml` in sync, and check whether the bump needs a
  `--collect-all` change in `.github/workflows/release.yml` (verified by the built exe’s
  `--selftest`);
- follow the repo’s branch/PR conventions — never commit straight to main;
- majors and review candidates stay a WRITTEN proposal (PR description or issue).

## 7 · Close the lifecycle (both modes)

- Re-run `compat_check` with `project:"fo0/listen-to-me"` and the new stack — it syncs the
  project dashboard and auto-marks planned upgrades `applied`.
- Verified something beacon did not know (an unknown/flagged pair now proven)? Write back
  ONE tight-range `compat_report` rule (`repo:"fo0/listen-to-me"`) for the pair you actually
  exercised — never blanket-report every routine bump.
- Updates you decided against — or that failed — record with `compat_decide`
  (`project:"fo0/listen-to-me"`, `rejected`/`failed`/`abandoned` + note), so the project
  dashboard shows why.
