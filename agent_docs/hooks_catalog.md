# Hooks Catalog — Tier-2/3

Ready-to-paste hook snippets that enforce optimizer rules beyond the Tier-1 minimum in `.claude/settings.json`. Copy what fits, paste into `.claude/settings.json` under the matching trigger.

> **Tier-1 hooks** (already in `.claude/settings.json`): CLAUDE.md size guard, SessionStart memory reminder. (GitNexus is OFF in this project's manifest — no GitNexus pre-commit guard.)
> **Tier-2** = recommended, default off — copy if relevant.
> **Tier-3** = optional, situational — copy only if you actively want the behavior.

## How to use
1. Open `.claude/settings.json`.
2. Find the matching trigger (`PostToolUse`, `PreToolUse`, `Stop`, `PreCompact`, `UserPromptSubmit`).
3. Append the snippet's hook entry to the trigger's array. Don't duplicate matchers — merge into existing matcher's `hooks` list.

---

## Tier 2 — Recommended

### MEMORY.md size warning (>16,000 chars)

```json
{
  "matcher": "Edit|Write",
  "hooks": [
    {
      "type": "command",
      "command": "f=\"$CLAUDE_PROJECT_DIR/MEMORY.md\"; [ -f \"$f\" ] && [ $(wc -c < \"$f\") -gt 16000 ] && echo 'MEMORY.md > 16000 chars — remove obsolete entries per memory_process.md.' || true"
    }
  ]
}
```

Trigger: `PostToolUse`

### SCRATCHPAD.md size warning (>8,000 chars)

```json
{
  "matcher": "Edit|Write",
  "hooks": [
    {
      "type": "command",
      "command": "f=\"$CLAUDE_PROJECT_DIR/SCRATCHPAD.md\"; [ -f \"$f\" ] && [ $(wc -c < \"$f\") -gt 8000 ] && echo 'SCRATCHPAD.md > 8000 chars — clean resolved entries; promote long-lived ones to MEMORY.md.' || true"
    }
  ]
}
```

Trigger: `PostToolUse`

### Stop — scratchpad cleanup reminder

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "echo 'Session ending — verify SCRATCHPAD.md is clean. Promote stable entries to MEMORY.md per memory_process.md.'"
    }
  ]
}
```

Trigger: `Stop`

### PreCompact — dump scratchpad state

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "f=\"$CLAUDE_PROJECT_DIR/SCRATCHPAD.md\"; [ -f \"$f\" ] && echo '=== SCRATCHPAD before compact ===' && cat \"$f\" || true"
    }
  ]
}
```

Trigger: `PreCompact`

### Stop — review reminder

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "echo 'Session ending — if code changed this session, review process per agent_docs/review_process.md must have run before commit.'"
    }
  ]
}
```

Trigger: `Stop`

### Block push to main on red (project checks)

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "cmd=$(jq -r '.tool_input.command // empty'); if echo \"$cmd\" | grep -q 'git push'; then ref=$(echo \"$cmd\" | grep -oE '\\b(main|master|develop|trunk)\\b' | head -1); [ -n \"$ref\" ] || ref=$(git -C \"$CLAUDE_PROJECT_DIR\" rev-parse --abbrev-ref HEAD 2>/dev/null); case \"$ref\" in main|master|develop|trunk) cd \"$CLAUDE_PROJECT_DIR\" && { python -m compileall -q src scripts && QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -c 'import sys; from listen_to_me.selftest import gui_smoke; sys.exit(gui_smoke())'; } || { echo 'BLOCKED: checks failing — never push to main on red.' >&2; exit 2; };; esac; fi"
    }
  ]
}
```

Trigger: `PreToolUse`. Runs this project's checks (`compileall` + offscreen Qt smoke) before a push to a protected branch. Requires `jq` — without it the guard never fires (see Notes). Err-safe: a bare `git push` is resolved via the current branch; it only blocks when the checks are red.

### Block force-push without confirmation

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "cmd=$(jq -r '.tool_input.command // empty'); if echo \"$cmd\" | grep -qE 'git push.*(--force(-with-lease)?|-f)\\b'; then echo 'BLOCKED: force-push requires explicit user confirmation. Re-run after user approves.' >&2; exit 2; fi"
    }
  ]
}
```

Trigger: `PreToolUse`. Catches `--force`, `--force-with-lease`, and the short `-f` flag. Requires `jq` (see Notes).

### Mermaid validate on save

```json
{
  "matcher": "Edit|Write",
  "hooks": [
    {
      "type": "command",
      "command": "fp=$(jq -r '.tool_input.file_path // empty'); if echo \"$fp\" | grep -q '\\.mmd$'; then cd \"$CLAUDE_PROJECT_DIR\" && npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg 2>&1 | tail -5 || echo 'Mermaid syntax error — check diagram_prompt.md syntax rules.'; fi"
    }
  ]
}
```

Trigger: `PostToolUse`

### Doc-update reminder after src/ edit

```json
{
  "matcher": "Edit|Write",
  "hooks": [
    {
      "type": "command",
      "command": "fp=$(jq -r '.tool_input.file_path // empty'); if echo \"$fp\" | grep -qE '(^|/)src/'; then echo 'Source changed — verify CLAUDE.md / README.md / MEMORY.md / config table need updates per Documentation Rules.'; fi"
    }
  ]
}
```

Trigger: `PostToolUse`

---

## Tier 3 — Optional

### Warn on non-lazy heavy import (project-specific guardrail)

```json
{
  "matcher": "Edit|Write",
  "hooks": [
    {
      "type": "command",
      "command": "fp=$(jq -r '.tool_input.file_path // empty'); if echo \"$fp\" | grep -qE 'src/listen_to_me/.*\\.py$'; then echo 'Reminder: keep PySide6/sounddevice/pynput/faster_whisper/numpy imports lazy (inside functions), and never touch Qt from a worker thread.'; fi"
    }
  ]
}
```

Trigger: `PostToolUse`

### Dependency-install warning

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "cmd=$(jq -r '.tool_input.command // empty'); if echo \"$cmd\" | grep -qE 'pip install [a-zA-Z]|pip install -e'; then echo 'New dependency? Confirm with user, and keep requirements.txt + pyproject.toml (+ PyInstaller --collect-all) in sync per CLAUDE.md.'; fi"
    }
  ]
}
```

Trigger: `PreToolUse`

### Done-skill auto-trigger on "done"/"fertig"

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "p=$(jq -r '.prompt // empty'); if echo \"$p\" | grep -qiE '^(done|fertig|finished|abschluss|/done) *$'; then echo 'Trigger: load .claude/skills/done/SKILL.md and follow the closure workflow.'; fi"
    }
  ]
}
```

Trigger: `UserPromptSubmit`

---

## Notes
- **Hook input arrives as a JSON payload on stdin**, not via environment variables. Relevant fields: `.tool_input.command` (Bash tool), `.tool_input.file_path` (Edit/Write), `.prompt` (UserPromptSubmit). The snippets parse stdin with `jq` — there are no `$CLAUDE_TOOL_INPUT` / `$CLAUDE_USER_PROMPT` env vars.
- `$CLAUDE_PROJECT_DIR` IS a real environment variable (absolute project root), usable in any hook command.
- **`jq` is required** for every snippet that reads stdin. Without `jq` the hook errors out and does NOT block — for reminder hooks that's harmless, but the two BLOCK hooks then provide no protection.
- Exit code `2` from a `PreToolUse` hook blocks the tool call and feeds **stderr** back to Claude — block messages must go to stderr (`>&2`). Other non-zero exits print stderr but don't block.
- Hooks run in the user's shell. Quote paths, escape `$` carefully when copying.
- After modifying `.claude/settings.json`, restart the Claude Code session (or review via `/hooks`) for changes to take effect.
