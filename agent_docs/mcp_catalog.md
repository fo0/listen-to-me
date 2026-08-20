# MCP Catalog

This file documents:

1. **Common MCPs** the agent may encounter in any Claude Code environment.
2. **This project's intended MCPs** — declared by the user, not detected from the host.

> **Cross-machine rule:** the optimizer never auto-detects which MCPs are installed locally. The catalog reflects intent + reference, not host probe. If a listed MCP isn't installed on the current machine, the agent silently falls back to non-MCP equivalents (Read / Bash / WebFetch / etc.) and notes once: `MCP <name> not available locally — falling back to standard tools.`

## Project MCPs (intended for this project)

> Edit this list when adding/removing MCP integrations from the project. The optimizer preserves user edits on re-run.

| MCP                  | Purpose in this project                                                                                             | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `github`             | PRs, issues, CI status, releases via the GitHub API                                                                 | **The `gh` fallback, canonical:** every `gh` command in `.claude/skills/{pr,ci,rollback}/SKILL.md` may be executed with the equivalent `mcp__github__*` tool. Claude Code web/remote sessions have no `gh` CLI, so there that is the only path — a missing `gh` is not a reason to stop. What stays forbidden either way: creating or merging a PR by hand in the browser, and merging outside the rule in CLAUDE.md → Deployment (an explicit user command, or an owner-authorized routine meeting its non-destructive + green-verification conditions). PR-activity subscribe/unsubscribe registers under this server on the web surface. |
| `claude-code-remote` | Web/remote session management — scheduled Routines/triggers, `send_later` self check-ins, PR-activity subscriptions | The whole server is pre-approved in `.claude/settings.json` → `permissions.allow` via one `mcp__<server>__*` glob per spelling. See _Prompt-free triggers_ below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

## Common MCPs (reference — not necessarily used here)

| MCP                             | Typical use                                                                                                                                                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `gitnexus`                      | Code intelligence — symbol graph, impact, refactor (OFF in this project's manifest)                                                                                                                                                |
| `filesystem`                    | Sandboxed file access beyond CWD                                                                                                                                                                                                   |
| `github`                        | Issue / PR / repo metadata via API (alternative to `gh`)                                                                                                                                                                           |
| `claude-code-remote`            | Claude Code web/remote session management — Routines/triggers, `send_later`, PR-activity subscriptions. PR-activity subscribe/unsubscribe may register under the `github` MCP server instead — the allowlist covers both spellings |
| `postgres` / `mysql` / `sqlite` | Live DB schema introspection + read queries                                                                                                                                                                                        |
| `puppeteer` / `playwright`      | Headless browser, used for UI automation, scraping, e2e                                                                                                                                                                            |
| `fetch`                         | HTTP fetch wrapper                                                                                                                                                                                                                 |
| `slack`                         | Read/post messages — for ops integrations                                                                                                                                                                                          |
| `sentry`                        | Error tracking lookup                                                                                                                                                                                                              |
| `notion` / `linear` / `jira`    | Work tracking integrations                                                                                                                                                                                                         |
| `aws` / `gcp` / `azure`         | Cloud resource queries (use carefully — non-zero cost)                                                                                                                                                                             |

## Prompt-free triggers everywhere (one-time, optional)

This repo's `.claude/settings.json` pre-approves **every** Claude Code Remote tool — present and future — with one `mcp__<server>__*` glob per known server spelling (`claude-code-remote`, `Claude_Code_Remote`, `claude_code_remote`), plus the two exact `mcp__github__(un)subscribe_pr_activity` entries because the PR-activity pair registers under the GitHub server on the web surface.

**One glob per spelling, and nothing a glob already covers.** A per-tool entry such as `mcp__claude-code-remote__create_trigger` is matched by its server glob, grants nothing extra, and only makes the list look like an enumeration someone must keep current. Sixteen such entries were pruned on 2026-08-02; **do not re-add one**. The `mcp__github__(un)subscribe_pr_activity` pair is the deliberate exception: there is no `mcp__github__*` glob here — the GitHub server is intentionally _not_ blanket-approved — so those two entries are the only thing covering the pair. Should a `mcp__github__*` glob ever be added, they become redundant too.

**No carve-outs, including `add_repo` / `register_repo_root`.** A prompt that fires mid-run is exactly what breaks unattended operation, and those tools can only attach repositories the account already reaches. To re-gate one in this repo, add it to `permissions.ask` by hand — rules evaluate **deny → ask → allow**, first match wins, so an `ask` entry prompts even though the broader `allow` glob matches. The optimizer never writes that array and never removes a user-added entry.

**Trust gate — the fact that decides whether any of the above does anything.** `permissions.allow` from a _project_ settings file grants capability, so Claude Code applies it **only after this repo's workspace-trust dialog has been accepted** (`ask`/`deny` are unaffected). That single fact splits the two surfaces, and they are not equally fixable:

| Surface                                                             | What actually happens                                                                                                                                                                                                                                                     | The one-time fix                                                                                                            |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **Local CLI**                                                       | The trust dialog appears on the first interactive run in this repo; accept it and the block above is live for good                                                                                                                                                        | Accept the dialog — or put the rules in user settings below and cover every repo at once                                    |
| **Claude Code web / cloud** (routines, Claude Tag, mobile included) | No trust dialog exists and every session starts from a fresh container, so the block is dropped at startup — `Ignoring N permissions.allow entries from .claude/settings.json: this workspace has not been trusted` — and `delete_trigger` & friends prompt on every call | User settings, installed by the cloud environment's **setup script** (below). Nothing inside this repo can fix this surface |

Same rules either way, in `~/.claude/settings.json` — user scope carries no trust gate and applies to every repo:

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

**Cloud/web — paste this into the environment's _Setup script_** (claude.ai → Claude Code → cloud environment settings). It runs as root before Claude Code launches, and what it writes survives in the environment snapshot, so later sessions start with the file already in place. Merge-safe: it adds only what is missing.

```bash
python3 - <<'PY'
import json, os, pathlib
d = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or (pathlib.Path.home() / ".claude"))
d.mkdir(parents=True, exist_ok=True)
f = d / "settings.json"
cfg = json.loads(f.read_text()) if f.exists() else {}
allow = cfg.setdefault("permissions", {}).setdefault("allow", [])
for rule in ["mcp__claude-code-remote__*", "mcp__Claude_Code_Remote__*", "mcp__claude_code_remote__*",
             "mcp__github__subscribe_pr_activity", "mcp__github__unsubscribe_pr_activity"]:
    if rule not in allow:
        allow.append(rule)
f.write_text(json.dumps(cfg, indent=2))
PY
```

Editing the setup script re-runs it and rebuilds the snapshot; the cache also expires after roughly seven days. Verify in the next session with `cat ~/.claude/settings.json`. **Why not a `SessionStart` hook in this repo:** hooks do run in an untrusted workspace, but settings are read _before_ hooks fire — the rules would apply to the session _after_ the one that wrote them, and in the cloud there is no session after: each gets a new container. The web surface pre-approves the GitHub MCP server on its own, which is why the prompts that survive there are the Claude Code Remote ones.

Merge additively into an existing file; never remove a user's own entries there. **The agent never writes this file on its own** — it lives outside the repo, so applying it is the user's call.

Two more keys earn their place in that same user-level file — both are read **only** from user settings, which is why this repo never writes them:

| Key                                             | Effect on unattended work                                                                                                                                                                                                                                                              |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `"askUserQuestionTimeout": "5m"`                | An unanswered `AskUserQuestion` auto-continues after 5 minutes with whatever was preselected instead of holding the session open. The default `"never"` waits forever — that is what turns one ambiguous moment into a dead overnight run. Values: `"60s"`, `"5m"`, `"10m"`, `"never"` |
| `"permissions": {"defaultMode": "acceptEdits"}` | Optional. File edits and common filesystem commands stop prompting; every other rule still applies. A project file _can_ carry this, but how much a machine may do unsupervised is the owner's call, not the repo's. `bypassPermissions` belongs only in a container you can lose      |

**Self-heal — local sessions only.** If a Claude Code Remote tool still raises an approval prompt in a session where the block applies, its server spelling is missing: **append** `mcp__<that spelling>__*` to the repo's `permissions.allow` and commit it on the current branch/PR. One heal per spelling — append the _glob_, never the individual tool name, and **never write a `deny` or `ask` entry**. Removing a glob, or narrowing one into per-tool entries, is not a heal.

In a web/cloud session (`$CLAUDE_CODE_REMOTE=true`) the agent **appends nothing**: the entry could not take effect there in any session, so committing it would manufacture dead config. Name the one-time user-scope fix above once and carry on.

## MCPs in cloud and routine runs

A cloud session — every routine run included — starts from a fresh clone of `main`. Nothing added locally with `claude mcp add` travels with it, because that configuration lives on the machine, not in the repo. Two paths make a server reachable in an unattended run:

1. **A committed `.mcp.json` at the repo root** (project scope). It is part of the clone, so it applies everywhere the repo goes:

   ```json
   {
     "mcpServers": {
       "example": { "type": "http", "url": "https://mcp.example.com/mcp" }
     }
   }
   ```

   stdio servers use `"command"` + `"args"` instead of `"type"`/`"url"`. `${VAR}` and `${VAR:-default}` expand in `command`, `args` and `env` — **use them for every credential**; a token committed in `.mcp.json` is a leaked token. Project servers need approval before they connect: `.claude/settings.json` → `enableAllProjectMcpServers: true` grants it, and like every project-level allow rule it applies only after the workspace-trust dialog is accepted.

   **This repo has no `.mcp.json`**, which is why `.claude/settings.json` deliberately carries no `enableAllProjectMcpServers` key — it would approve an empty set. Add the key in the same change that adds the file, never before.

2. **claude.ai connectors.** A routine includes the account's connectors, and its own form is where you narrow them to what the run needs. Connector traffic goes through Anthropic's servers, so it is unaffected by the environment's allowed-domains list.

Neither path is a hard requirement — Selection Heuristic rule 3 still holds. A run whose MCP is missing falls back and says so once.

## Selection Heuristic for the Agent

1. **Project MCPs first.** If the project intends an MCP for a task, use it.
2. **Common-MCP fallback.** For tasks that fit a common MCP, try it; if unavailable, fall back to standard tools.
3. **Never make MCP usage a hard requirement.** All workflows must work without MCPs (autonomy + cross-machine rule).
4. **Never call cost-incurring MCPs** (cloud, paid APIs) unless explicitly requested by the user.

## Adding a New Project MCP

1. Add a row to the **Project MCPs** table above with purpose + notes.
2. If the MCP needs setup, document the install/auth steps in CLAUDE.md "External Integrations" section.
3. If a workflow becomes MCP-dependent, add a fallback path that works without it.
