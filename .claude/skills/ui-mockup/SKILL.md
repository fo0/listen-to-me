---
name: ui-mockup
description: "UI mockups in Claude Design and the house UI rules. Load it before any new view, revamp, admin page, theme or dialog — also on 'Vorschlag', 'zeig mal, wie das aussieht', 'show me what it would look like' or 'mockup' — without asking first, and before building or changing UI: its UI rules bind the implementation as much as the mockup."
metadata:
  origin: claude-code-optimizer
---

# UI Mockup — Claude Design and the house UI rules

## When to Use

- A new view, a revamp, an admin page, a theme or a dialog — also when the user only asks for a proposal or to see
  what it would look like. Do not ask whether a mockup is wanted: make it.
- Another round on an existing mockup — feedback on a variant, a small change.
- Building or changing UI, with or without a mockup: _UI rules_ below bind the implementation too.

## Scope Boundaries

**Owns:** the mockup procedure, its mandatory block, and the house UI rules.
**Does not own:** how the work is split across seats (`orca`), the review of the built UI (`basic-review`).

## Two sessions that make no mockup

- **Unattended** (`$CLAUDE_CODE_REMOTE=true`): nobody can pick a variant. Build with the app's existing components
  under _UI rules_, put before and after screenshots into the PR, and name `no mockup (unattended)` in the report.
- **Interactive without Claude Design** — no Artifact tool with the design intent in the session's tool list: say so
  in one line and build no new view until a variant is chosen where it exists; loose HTML or ASCII is no substitute
  (block, item 1). A change to an existing view goes ahead under _UI rules_.

## The mandatory block

Copy it **verbatim** into every mockup assignment — never reworded from memory.

```
MOCKUP-PFLICHT v1 — verbindliche Anforderungen des Betreibers an jedes UI-Mockup (wörtlich in jeden Mockup-Auftrag)

1. Werkzeug: Claude Design. Artifact-Werkzeug `action: "quickstart"`, `intent: "design"`, dann mit dessen `type_url` anlegen und den Typ-Anweisungen folgen. Kein loses HTML, kein ASCII.
2. EIN Einstiegs-Artboard (z. B. `Vergleich.dc.html`), das die Ansichten per `<dc-import>` zeigt; `launch` fokussiert darauf. Beim Öffnen gefüllt und lesbar, ohne Zoomen, ohne „Fill“-Klick. KEIN Canvas mit Zeilen je Variante, keine 1000 Einzel-Views.
3. Oben links ein Varianten-Umschalter (inkl. „bisher“ = heutiger Stand nachgebaut), daneben Tabs je Ansicht/Bildschirm. Jede Kombination Bildschirm × Variante in einem Klick erreichbar.
4. Echte App-Hülle: Menü/Top-Navigation oben wie in der echten App, App-Look (dunkles Theme, vorhandene Farben, Buttons, Badges), realistische Beispieldaten.
5. Drei Varianten je Bildschirm. Benennung fortlaufend je Runde: Runde 1 A/B/C, Runde 2 Untervarianten mit dem nächsten Buchstaben (D1/D2/D3), nicht wieder A1.
6. Empfehlung: Tab der empfohlenen Variante je Bildschirm mit ★ markieren; je Variante eine Zeile, was sie unterscheidet.
7. Rendering selbst im Browser prüfen, bevor es vorgelegt wird: Screenshot je Tab, breit und 375 px. Der Betreiber verlangt diese Prüfung ausdrücklich; das gilt als Freigabe, auch wenn die Typ-Anweisungen sonst vor dem Rendern fragen lassen.
8. UI-Regeln: schlicht, wenig Text, Hinweise in Tooltips; keine Seitenpanels/Drawer; Row Actions rechts; Aktionsknöpfe in einer Zeile; Zahlen-Eingaben als moderne Bedienelemente (Stepper, Chips, Slider), nicht als nacktes Textfeld; Presets als Split-Button.
9. Iterationen ins SELBE Artifact (gleiche URL); nur ändern, was das Feedback nennt.
```

## Procedure

1. **Settle the starting point:** the app, the screens, today's state (`bisher`), what is to change. Find the sources
   of the real app shell — layout, menu, CSS tokens, components — and pass them as paths.
2. **Delegate** to `fable-medium` for a larger round (many views or variants), to `opus-high` for a small change. The
   assignment carries:
   - the block above, verbatim;
   - the screens (tabs), and per screen three variant ideas with their difference in one line, the recommended one ★;
   - the paths of the app shell and realistic sample data;
   - the technical limits — existing data sources, tokens — so only what can be built is shown; when "no backend
     change" is asked, the existing data source of every widget;
   - the return: the Artifact URL, per screen the variants with their one-line difference and ★, and confirmation of
     the screenshot check, wide and 375 px.
3. **Present:** the link clickable, per screen a short table `Variant | Difference | ★`. Ask only what the choice does
   not answer.
4. **Iterate into the same Artifact** (same URL). The letters keep running; change only what the feedback names.
5. **After the choice:** the mockup URL and the chosen variant go to the implementing seat as the visual reference;
   it builds with the app's existing building blocks.

An implementation assignment that does not carry the block avoids the words _mockup_, _Claude Design_ and _artboard_ —
the owner's guard hook blocks every agent prompt that names them without the identifier; _draft_ or _Entwurf_ is fine.

## Mistakes that already happened, more than once

- A canvas with a row per variant instead of ONE entry artboard with tabs.
- `bisher` forgotten, the top menu missing, the star missing.
- The rendering not checked yourself, wide and at 375 px.
- A new round starting at A1 again instead of the next letter.
- An arrangement changed that the feedback did not name.
- The block reworded from memory instead of copied verbatim.

## UI rules — for mockups and implementation alike

The owner's decisions. They outrank every older UI statement in the README, `docs/` and `agent_docs/`: a doc that
contradicts one is corrected in the same change, never followed. An Accepted ADR that contradicts one stays binding
until the owner says otherwise in chat — propose the superseding ADR and ask
(`agent_docs/adr_template.md → Lifecycle`). An existing screen that breaks one is no precedent. The UI review checks
every changed screen against each rule.

- Compact first: single-line rows over cards, the smallest readable size; no decorative headings or step lists.
- Labels, not sentences: at most one short help line per form, no explanatory paragraphs, nothing that narrates what
  the UI obviously does.
- Plain like the neighbouring component: a title, one status line, actions on the right. Little text; explanations
  collected in ONE info tooltip. Emphasis sparingly: one badge OR one bold word.
- No page title under the menu when the menu already names the page. Page-wide switches right-aligned in the tab
  bar, no header row of their own.
- No side panels or drawers — inline instead (a column, a badge, an expandable row), a subpage or a dialog.
- Row actions in tables on the right, in the last column. On the left only in ticket or task views, and only on
  explicit request.
- Alignment: header buttons get no row of their own, they sit level with the first content row. Actions that belong
  together stay in ONE row, Delete last on the right (`margin-left: auto`). Checked at 1920 and 390 px.
- Resources always in the order CPU, RAM, Disk — each on its own row, the bars stacked.
- Overview first, details on click. Compact button rows instead of a row per value. Labels inside the bars, in a
  tooltip when there is no room. Several presets as a split button.
- Number inputs as a stepper, chips or a slider with a value chip — never a bare text field.
- A new feature gets a subtle _Beta_ badge at its entry point only (tab, menu item): a corner badge top right that
  covers no text and shifts no layout — the app's own badge component where it has one.
- A live display shows a green pulsing dot while updates arrive, and none without them. Longer log or live areas are
  set apart and collapsible.
- Items are named by what differs: the distinguishing name first, a name many items share second — never a list
  whose entries all lead with the same word.
- No manual configuration the app can infer: what it can derive from its own data it derives — no picker, no add or
  remove for it.
- Settings are staged: changes apply with one primary save beside cancel; an action that takes effect at once is an
  explicit button of its own.
- One primary action per form or flow, bottom right. A flow that succeeded closes or returns by itself — never a close
  button to press after success.
- Feedback goes away: a success notice closes after 3 s, an undo offer after 8 s; only warnings and errors stay.
  Nothing sticks on screen.
- Toggles stay in place: maximize becomes minimize on the same spot, no separate back button.
- An installed app updates itself: check, update available with at most 5 changelog bullets, install, progress,
  restart. Never a web page as the update path.
- Honest evidence: a screenshot or preview shown as the result comes from the exact build being delivered — a
  mockup is a proposal, never the result.
- Accessibility adds no visible prose: accessible names and tooltips carry the detail; an icon button gets an
  accessible name, not a caption.
- A UI assignment to a seat asks for before and after screenshots.
