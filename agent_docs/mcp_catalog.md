# MCP Catalog

This file documents:

1. **Common MCPs** the agent may encounter in any Claude Code environment.
2. **This project's intended MCPs** — declared by the user, not detected from the host.

> **Cross-machine rule:** the optimizer never auto-detects which MCPs are installed locally. The catalog reflects intent + reference, not host probe. If a listed MCP isn't installed on the current machine, the agent silently falls back to non-MCP equivalents (Read / Bash / WebFetch / etc.) and notes once: `MCP <name> not available locally — falling back to standard tools.`

## Project MCPs (intended for this project)

> Edit this list when adding/removing MCP integrations from the project. The optimizer preserves user edits on re-run.

| MCP                | Purpose in this project           | Notes |
|--------------------|-----------------------------------|-------|
| `github`           | PRs, issues, CI status, releases via the GitHub API | **The `gh` fallback, canonical:** every `gh` command in `.claude/skills/{pr,ci,rollback}/SKILL.md` may be executed with the equivalent `mcp__github__*` tool. Claude Code web/remote sessions have no `gh` CLI, so there that is the only path — a missing `gh` is not a reason to stop. What stays forbidden either way: creating or merging a PR by hand in the browser, and merging at all without an explicit interactive user command (CLAUDE.md → Deployment). PR-activity subscribe/unsubscribe registers under this server on the web surface. |
| `claude-code-remote` | Web/remote session management — scheduled Routines/triggers, `send_later` self check-ins, PR-activity subscriptions | The whole server is pre-approved in `.claude/settings.json` → `permissions.allow` via one `mcp__<server>__*` glob per spelling. See *Prompt-free triggers* below. |

## Common MCPs (reference — not necessarily used here)

| MCP            | Typical use                                                  |
|----------------|--------------------------------------------------------------|
| `gitnexus`     | Code intelligence — symbol graph, impact, refactor (OFF in this project's manifest) |
| `filesystem`   | Sandboxed file access beyond CWD                            |
| `github`       | Issue / PR / repo metadata via API (alternative to `gh`)    |
| `claude-code-remote` | Claude Code web/remote session management — Routines/triggers, `send_later`, PR-activity subscriptions. PR-activity subscribe/unsubscribe may register under the `github` MCP server instead — the allowlist covers both spellings |
| `postgres` / `mysql` / `sqlite` | Live DB schema introspection + read queries |
| `puppeteer` / `playwright` | Headless browser, used for UI automation, scraping, e2e |
| `fetch`        | HTTP fetch wrapper                                          |
| `slack`        | Read/post messages — for ops integrations                   |
| `sentry`       | Error tracking lookup                                       |
| `notion` / `linear` / `jira` | Work tracking integrations                  |
| `aws` / `gcp` / `azure` | Cloud resource queries (use carefully — non-zero cost) |

## Prompt-free triggers everywhere (one-time, optional)

This repo's `.claude/settings.json` pre-approves **every** Claude Code Remote tool — present and future — with one `mcp__<server>__*` glob per known server spelling (`claude-code-remote`, `Claude_Code_Remote`, `claude_code_remote`), plus the two exact `mcp__github__(un)subscribe_pr_activity` entries because the PR-activity pair registers under the GitHub server on the web surface.

**No carve-outs, including `add_repo` / `register_repo_root`.** A prompt that fires mid-run is exactly what breaks unattended operation, and those tools can only attach repositories the account already reaches. To re-gate one in this repo, add it to `permissions.ask` by hand — rules evaluate **deny → ask → allow**, first match wins, so an `ask` entry prompts even though the broader `allow` glob matches. The optimizer never writes that array and never removes a user-added entry.

**Trust gate** (the usual cause of "the allowlist is there but it still prompts"): `permissions.allow` from a *project* settings file only applies after the workspace-trust dialog for this repo has been accepted. Until then the rules are read but inert (`ask`/`deny` are unaffected). Fix it once per machine by accepting the dialog, or put the same list into the **user-level** `~/.claude/settings.json`, where no trust gate applies and it covers every repo:

```json
{
  "permissions": {
    "allow": [
      "mcp__claude-code-remote__*",
      "mcp__Claude_Code_Remote__*",
      "mcp__claude_code_remote__*",
      "mcp__github__subscribe_pr_activity",
      "mcp__github__unsubscribe_pr_activity"
    ]
  }
}
```

Merge additively into an existing file; never remove user entries. **The agent never writes this file on its own** — it lives outside the repo, so applying it is the user's call.

**Self-heal:** if a Claude Code Remote tool still raises an approval prompt, its server spelling is missing. Append `mcp__<that spelling>__*` to the repo's `permissions.allow` and commit it on the current branch/PR — additive only, never `deny`/`ask`, never a reorder. One heal per spelling.

## Selection Heuristic for the Agent

1. **Project MCPs first.** If the project intends an MCP for a task, use it.
2. **Common-MCP fallback.** For tasks that fit a common MCP, try it; if unavailable, fall back to standard tools.
3. **Never make MCP usage a hard requirement.** All workflows must work without MCPs (autonomy + cross-machine rule).
4. **Never call cost-incurring MCPs** (cloud, paid APIs) unless explicitly requested by the user.

## Adding a New Project MCP

1. Add a row to the **Project MCPs** table above with purpose + notes.
2. If the MCP needs setup, document the install/auth steps in CLAUDE.md "External Integrations" section.
3. If a workflow becomes MCP-dependent, add a fallback path that works without it.
