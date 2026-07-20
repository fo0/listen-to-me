---
name: security-review
description: "Use when the user wants a focused security audit of the current diff or recent changes. Triggered by /security-review, 'security review', 'audit this for security', 'check for vulnerabilities', 'OWASP review'. Runs deeper checks than the generic review — OWASP / secrets / injection / auth / crypto. Independent of the generic review skill."
---

# Security Review — Focused Vulnerability Audit

## When to Use

- User says "/security-review", "security review", "audit for security", "check for vulnerabilities", "OWASP review"
- After implementing anything touching: the injector, the assistant HTTP client, the updater download/self-swap, config/secret handling, or subprocess/`os.startfile` calls
- Before merging high-risk PRs

## Scope

Diff-based by default. Full-codebase only on explicit user request (`/security-review --full`).

## Workflow

```
1. git status + git diff                              → identify changed files
2. Read CLAUDE.md "Architecture Principles" + Secrets  → understand trust boundaries
3. Read every changed file completely
4. Evaluate against the checklist below
5. Run security-relevant tooling (see Tooling)
6. Fix findings inline (prefer over defer; security debt compounds)
7. Output standard Security Review Results table
8. For NOT-fixed findings → BACKLOG.md with explicit Sev: P0/P1
```

## Checklist — OWASP-adapted + this app's real surfaces

### Secrets & Data
- [ ] Assistant `api_key` never logged, never committed, never echoed in a notification
- [ ] `history.json` stores text only — never audio, never secrets
- [ ] No hardcoded credentials / tokens anywhere in the diff
- [ ] Config written via `atomic_write_json` (no partial/truncated writes)

### Injection & Subprocess
- [ ] `open_path` / `subprocess.Popen` / `os.startfile` receive only trusted, non-user-crafted paths; no shell string interpolation
- [ ] The text injector (`pynput` type / clipboard paste) does not execute content — it only inserts; confirm no eval/exec of transcript or assistant output
- [ ] No `shell=True`, no `eval`/`exec`, no `pickle.loads` of untrusted data

### Network (assistant + updater)
- [ ] All external HTTP is opt-in and fail-soft (raw transcript on assistant failure; silent on updater failure)
- [ ] Updater downloads over HTTPS; the downloaded executable is validated (size/URL from the GitHub Releases API, not an arbitrary user URL) before the self-swap
- [ ] No SSRF: the assistant `base_url` is user-configured (local by default) — do not add code that fetches arbitrary URLs from transcript content
- [ ] `requests` calls have timeouts (assistant uses `cfg["assistant"]["timeout"]`)

### Robustness (a must-never-crash tray app)
- [ ] Every new external boundary has a fail-soft `except` + `log.exception` + user `notify`
- [ ] No unhandled exception can reach the Qt main loop
- [ ] Single-instance lock / autostart registry writes handle failure gracefully

### Dependencies
- [ ] `pip-audit` clean (no known high/critical vulns) if run
- [ ] New dep justified; `requirements.txt` and `pyproject.toml` kept in sync

## Tooling (run if available, never gate on availability)

| Tool                     | Command                        | What it catches |
|--------------------------|--------------------------------|-----------------|
| `gitleaks` / `trufflehog`| `gitleaks detect --source .`   | Committed secrets |
| `pip-audit`              | `pip-audit`                    | Vulnerable Python deps |
| `bandit`                 | `bandit -r src`                | Python SAST (subprocess, eval, weak crypto) |

If a tool isn't available locally → note in report, do NOT block the review.

## Severity & Fixing Rules

- **All security findings default to P0 or P1.** P2 only for clearly informational items.
- **Never defer a P0** without explicit user override + BACKLOG entry naming the user as the deferring party.
- **Fix inline** — security tech debt compounds.

## Report

```
### Security Review Results

| # | Area | Sev | Status | Finding | Action |
|---|------|-----|--------|---------|--------|
| 1 | Secrets | P0 | ⚠️ Fixed | api_key echoed in a notify() | Redacted from message |
| ... |

Tools run: <list>
Summary: X findings | Y fixed | Z deferred (with explicit user override) → Backlog
```

Footer:
```
🔐 security-review skill — independent of generic /review
```

## Rules

- **Do not run automatically.** On-demand only.
- **Do not skip checklist sections** even if "looks fine".
- **Do not silently lower severity.** If unsure, default to higher.
- **Do not commit fixes without re-running the affected checks** (autonomy + zero-cost rule still applies).
