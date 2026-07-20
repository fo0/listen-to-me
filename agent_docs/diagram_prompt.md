# Architecture Diagram Generation

## When to generate
- On explicit user request ("generate architecture diagram", "update diagram")
- After major structural changes (new modules, changed data flow, new external dependencies)
- NOT on every code change — only when the high-level architecture shifts

## Output files
- `docs/ARCHITECTURE.mmd` — Raw Mermaid code (no markdown fences)
- `docs/ARCHITECTURE.svg` — Rendered SVG (validate with: `npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg`)

## Generation Instructions

Analyze the repository and produce a single, valid Mermaid.js architecture diagram.

### Phase 1 — Repository Analysis

Gather context:
1. Read the file tree. Exclude: `.git`, `__pycache__`, `.venv`, `venv`, `build`, `dist`, `.idea`, `.vscode`, `*.egg-info`.
2. Read README and `pyproject.toml`/`requirements.txt` to identify the tech stack.

Determine:
- **Project type**: PySide6 desktop tray application (single package `src/listen_to_me/`).
- **Main components**: app core/state machine, input (hotkeys/tray/overlay), processing (recorder/transcriber/assistant/injector), persistence (config/history), external services.
- **Relationships**: worker threads → `App.post` event queue → main-thread handlers; component wiring in `App.__init__`.
- **Architecture patterns**: event-queue-driven state machine, main-thread Qt loop, lazy-imported components.

### Phase 2 — Component Mapping

Map each identified component to its concrete module under `src/listen_to_me/`:
- Prefer specific files (this is a flat package, one responsibility per module).
- Use exact paths for `click` events.
- Aim for 15–25 mappings.

### Phase 3 — Mermaid Diagram Generation

Use `flowchart TD` (top-down, vertical orientation).

**Node shapes:** `("Label")` service/component · `[("Label")]` datastore · `["Label"]` generic module · `{{"Label"}}` external service · `(["Label"])` queue.

**Requirements:**
- Group related components in `subgraph` blocks (Entry / Core / Input & UI / Processing / Persistence / External).
- Show data flow with labeled arrows: `A -->|"description"| B` (only label when meaningful).
- Add `click NodeID "src/listen_to_me/<file>.py"` for every mapped component.
- Apply `classDef` styles to every node — colors are mandatory.
- Aim for 15–35 nodes total.

### Syntax Rules (CRITICAL — parser is strict)

1. QUOTE all labels with special characters.
2. QUOTE all edge labels with special chars.
3. NO spaces between pipes and quotes: `A -->|"text"| B`.
4. NO `:::class` on subgraph declarations.
5. NO subgraph aliases: use `subgraph "Name"`.
6. NO `%%{init: ...}%%` blocks.
7. NEVER use `end` as a node ID.
8. Node IDs must NOT start with a digit.
9. NO semicolons at line ends.
10. NO empty subgraphs.
11. NO nested quotes in labels.

### Validation

```bash
npx -y -p @mermaid-js/mermaid-cli mmdc -i docs/ARCHITECTURE.mmd -o docs/ARCHITECTURE.svg
```

If syntax errors occur, fix the Mermaid code without changing diagram meaning. Keep all click events and the vertical orientation.
