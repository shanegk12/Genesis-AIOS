# Plan: Reusable interactive library (save once, insert anywhere)

> **SHIPPED to staging 2026-06-11** — built as the **canonical reference** model (Phase 2 below), not the copy-into-block Phase 1 this doc originally recommended. Lesson blocks link via `data.libraryId`; editing a library entry fans content out to every linked block. Backfill deduped 463 interactives → 450 entries across 159 primary lessons. Redundancy scan added (by-type filename grouping + exact-duplicate). See memory `project-interactive-library` for the full as-built notes + file list. Remaining: verify staging, ff→main, re-run backfill on prod.

> Drafted 2026-06-11 for a future build. Goal: save a code-embed/interactive once and reuse it across lessons without re-pasting the whole snippet — removing any need for "hidden blocks."

## Why
Shane builds rich `code-embed` interactives (e.g. a flowchart-builder web component). He wanted "hidden blocks" so a definition could be written once and reused with one line. **The cleaner answer is a reusable library** — the definition lives in the library, not as a hidden block in the lesson.

## The constraint that shapes the design
**Every `code-embed` renders in its own sandboxed iframe (`srcDoc`).** A custom element `define()`d in one iframe is invisible to another — so "define once in a hidden block, use `<flow-chart>` elsewhere" does NOT cross iframes. The library sidesteps this by making each inserted embed self-contained.

## Current state (what exists)
- `/admin/interactives` ([src/app/admin/interactives/page.tsx](D:\GK12-Platform\src\app\admin\interactives\page.tsx)) is a **read-only catalog** — it scans lessons for `embed`/`code-embed` blocks and previews them. No save/insert.
- Block types: `embed` (`EmbedBlockData {url,height,title,workbook?}`, rendered via `InteractiveEmbed` with the workbook bridge when a student ctx exists), `code-embed` (`CodeEmbedBlockData {html,height,title}`, sandboxed srcDoc iframe).
- Nested embeds in columns/accordions/tabs already work (editor `NestedBlocksProperties` + renderer `NestedBlocksRenderer` both handle embed/code-embed). The main canvas just previews them without the student runtime ctx — expected.
- The AI assistant already fetches *style* templates from existing interactives (`/api/admin/ai/templates`, `fetchInteractiveTemplate`) — different from this (that's "match the look," this is "reuse the exact component").

## Build (Phase 1 — self-contained snippet reuse; recommended)
1. **Store:** Firestore `interactiveLibrary/{id}` = `{ name, description?, type: "code-embed"|"embed", html?, url?, height?, createdAt }`. Admin-only in rules (`match /interactiveLibrary/{id} { allow read, write: if isAdmin(); }`). Students never read it — insert copies the html/url into the lesson block, which is already gated.
2. **Save to library:** a "Save to library" action on a code-embed/embed (block editor or the AI assistant panel) → prompts name + description → writes the doc. Also a small manage view (extend `/admin/interactives` with a "Library" tab) to list/edit/delete saved components.
3. **Insert from library:** an "Insert from library" picker in the lesson editor (and optionally the AI assistant) → drops a new `code-embed`/`embed` block with the saved html/url. **Self-contained** — each insert is its own iframe, fully independent, no hidden blocks, no cross-iframe issues. This is exactly "save it, reuse it everywhere."

## Phase 2 (optional upgrade — one-line usage)
Let authors write just `<flow-chart></flow-chart>` and have the **renderer inject the saved definition** into that embed's iframe srcDoc at render time (lookup by component name). Gives the "one line" authoring without breaking the sandbox. More machinery (a component registry + render-time concatenation); do only if the snippet-insert in Phase 1 isn't ergonomic enough.

## Verification
Save the flowchart code-embed to the library → open a different lesson → Insert from library → it renders + works (Preview / student view). Confirm it's independent across multiple inserts and survives publish (content lives in the block, not the library).
