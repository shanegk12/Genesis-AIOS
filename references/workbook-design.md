# Engineering Workbook / Student Notebook — Design (draft 2026-06-11)

> Scoping doc. Goal: turn the workbook from a blank notes pad into a real engineering lab workbook — structured prompts, data tables, and lab fields students complete, that persist, that parents/teachers review, that the tutor can route to, and that print to match a physical workbook.

## Why
Genesis K-12 is a hands-on engineering course. A real engineering workbook is where students record predictions, observations, **data tables**, measurements, calculations, and sketches — not free prose. Today we only have a blank TipTap pad + whatever interactives happen to report. Structured workbooks also: (a) cut tutor cost (route students to written work instead of chat), (b) give parents concrete evidence of work, (c) feed the records/transcript story, (d) enable a printable Workbook edition (kit companion).

## What exists today (reuse, don't rebuild)
- **Free-form notebook** — TipTap pad per lesson/child at `notebooks/{uid}/children/{childId}/lessons/{lessonId}` ([src/lib/notebook.ts](D:/GK12-Platform/src/lib/notebook.ts)); side panel in the lesson player + full page `/notebook/[courseId]/[lessonId]`; tutor can append.
- **Interactive bridge + persistence** — `gk12.save()/report()` → `progress/{uid}/children/{childId}/interactiveState/{lessonId}__{blockId}` ([src/lib/interactiveState.ts](D:/GK12-Platform/src/lib/interactiveState.ts)); auto save/resume; parent-readable under existing rules. "Activity Results" surface in [NotebookPanel.tsx](D:/GK12-Platform/src/components/lesson/NotebookPanel.tsx).
- **Block system + editor** — `BlockCanvasEditor`, discriminated `Block` union in `src/types`, nested-block renderer; new block types are a known pattern (`/new-block` skill).
- **Content versioning** — frozen per-lesson snapshots; anything authored as blocks versions automatically (launch lock honored).
- **Parent gradebook** — `dashboard/progress/[childId]` already reads reports.
- **AI assistant** — can generate block content from lesson context (reuse to seed workbooks).
- **PDF export plan** — Paged.js → Chromium on Cloud Run, Student/Teacher/**Workbook** editions ([project-pdf-textbook-export-plan]).

## DECIDED (2026-06-11, Shane)
- **Scope: Mousetrap (build course) ONLY.** Creationeering lessons are separate from builds and only need minor note-taking — the existing free-form notebook covers them. No workbook for Creationeering.
- **A separate, cohesive Workbook artifact** (not woven inline). Its own student-facing document: open the workbook, complete the build documents all at once, pull referenced blocks from lessons, navigate to builds. **Authored on a block canvas like the lesson editor** (reuse `BlockCanvasEditor` — drag/drop, insert-between, nesting, width, undo/redo, AI assistant) with new **workbook field block types**; prose still uses TipTap inside text blocks.
- **Authored inside the lesson editor.** Each workbook **page is linked to its lesson** — editing a Mousetrap lesson also builds that lesson's workbook page. Lets us generate the needed blocks in one run per lesson (accepted trade-off: a bit more QC).
- **Observational** — no auto-grading; parents/teachers eyeball the filled work.
- **Sketches: BOTH** — student chooses 📷 photo-upload OR ✏️ in-app drawing canvas per sketch field.
- **Printable, near-term + parallel.** GK12 sells **paper copies**, so we need **Export Mousetrap Workbook → PDF** (blank edition for print sales). Students fill digitally and don't need to print. Sequence the PDF path alongside the digital build.

## Architecture (as decided)
A **course-level Workbook** for Mousetrap = an ordered set of **pages**, each authored as a **template** linked to a lesson, assembled into one student-facing workbook + one printable PDF.

Two layers (keep template and student input separate):
- **Template (authored, versioned with the lesson):** a **`Block[]`** array — the SAME shape as a lesson — reusing the existing lesson block types + branding, plus new **workbook field block types**. Stored per lesson at `workbookPages/{lessonId}` ({ blocks, lessonId, order }), authored via a **"Workbook page" tab** in the lesson editor that mounts `BlockCanvasEditor`, and frozen into the lesson's version snapshot so a student's workbook matches their lesson version.
- **Student responses (per child):** keyed by `fieldId` in the progress tree —
  ```
  progress/{uid}/children/{childId}/workbook/{lessonId}
    = { fields: { [fieldId]: text | number+unit | cell-matrix | checklist[] | sketchRef },
        updatedAt, completedFieldCount }
  ```
  Parent-readable under existing progress rules (no rules change). Sketch images (photo or canvas export) go to family Storage with unguessable tokens (reuse the project-photo pattern); `sketchRef` stores the token URL.

Rendering = template + responses merged. **Print** = render templates blank (or filled) → PDF.

## Field widgets (new workbook block types)
Added to the existing block palette (existing lesson blocks — text/image/callout/columns/etc. — and branding are reused as-is). New fillable block types: **short/long answer**, **fill-in-the-blank** (inline blanks), **data table** (author sets columns + rows; lock header/given cells), **measurement** (number + unit), **checklist** (build steps), **sketch** (student toggles 📷 photo-upload OR ✏️ draw-canvas), and a **"go to build"** link block. Prose/instructions use the existing text block (TipTap inside).

## Surfaces
- **Author:** a "Workbook page" tab in the lesson editor (Mousetrap lessons), using the remade TipTap editor + the field-node toolbar. Optionally an AI "generate this lesson's workbook page" pass that drafts fields from the lesson content (then QC).
- **Student:** a dedicated **Workbook** experience — open it, page through (one page per build lesson), fill fields, navigate to builds; autosave + resume. (Free-form notebook stays for Creationeering note-taking.)
- **Parent/teacher:** workbook answers per lesson in the gradebook (observational; reuse existing read patterns).
- **Print/PDF:** **Export Mousetrap Workbook → PDF** — assemble all pages into a blank printable workbook (for paper sales); filled version optional for student records.

## Decided editor/storage (2026-06-11)
- **Editor:** reuse `BlockCanvasEditor` (a "Workbook page" tab in the lesson editor) with all existing block types + branding, plus the new workbook field block types. Workbook page = `Block[]`, same as a lesson.
- **Template storage:** separate `workbookPages/{lessonId}` collection (loads on demand, versions cleanly).
- **Print:** client-side print-to-PDF of the assembled workbook first; upgrade to Chromium/Paged.js ([[project-pdf-textbook-export-plan]]) for sale-quality later.
- **AI authoring:** AI-seed each Mousetrap lesson's workbook page from its content, then human QC.

## Recommended phasing
- **Phase 1 (mechanism):** template data model + remade TipTap workbook editor with core field nodes (short answer, fill-in-blank, data table, measurement, checklist) on a "Workbook page" tab in the Mousetrap lesson editor; per-child responses in the progress tree.
- **Phase 2 (student + sketch):** student Workbook experience (page-through, autosave/resume, go-to-build links) + sketch field (photo + canvas) + parent gradebook view.
- **Phase 3 (print):** Export Mousetrap Workbook → PDF (blank for sale; filled optional).
- **Phase 4 (AI + tutor):** AI-seed workbook pages from lesson content; tutor routing + completion awareness.

See [[project-course-workbook-roadmap]] [[project-pdf-textbook-export-plan]] [[reference-lesson-editor-architecture]] [[project-content-versioning]].
