# Plan: New quiz question types (fill-in-blank, multiple-answer, drag-and-drop)

> Drafted 2026-06-11 for a future focused build. This is a project — it ripples through the whole assessment stack. Approve/adjust before building.

## Why
Current quizzes are single-answer multiple-choice only. Shane wants richer assessment (fill-in-the-blank, multiple-answer, drag-and-drop) to test comprehension better and reduce "guessable" MC. Pairs with the new **question vetter** (grounding audit) — new types need vetting too.

## Current state (what we're extending)
- `AssessmentQuestion` ([types/index.ts:46](D:\GK12-Platform\src\types\index.ts#L46)): `{ question, options{A,B,C,D}, answer, explanation, type? }` — MC only.
- Banks stored as `lesson.assessmentJson` (`{questions:[]}`) and/or a `quiz` block (`QuizBlockData`).
- **Grading + render:** `QuizEngine` ([components/lesson/QuizEngine.tsx](D:\GK12-Platform\src\components\lesson\QuizEngine.tsx)) — `answers[i] === q.answer`, radio UI. Now start-gated.
- **Admin views:** `/admin/questions` (list + vetter), the lesson-editor quiz block editor, `/admin/courses/[id]/lessons/[id]` assessment editing.
- **Vetter:** `/api/admin/qc/vet-questions` serializes `options{A-D}/answer`.
- **Generation:** Python pipeline (D:\AIOS\scripts) generates MC banks today.

## Data model (backward-compatible)
Add a discriminated `kind` (default `"mc"` so all existing questions keep working — no migration):
- `kind: "mc"` (legacy) — `options{A-D}`, `answer: "A"`.
- `kind: "multi"` — `options{A..}`, `answers: string[]` (correct set). Grading: exact set match.
- `kind: "fill"` — `prompt` with blanks; `blanks: { id, accepted: string[] }[]`. Grading: each blank ∈ accepted (normalized: trim/lowercase; optional synonym list).
- `kind: "order"` — `items: string[]` in correct sequence. Grading: sequence matches.
- `kind: "match"` — `pairs: { left, right }[]`. Grading: all pairs correct.

Keep `explanation` + `type` (cognitive level) on all kinds.

## Build phases (smallest delta first)
1. **Multiple-answer (`multi`)** — closest to MC: checkbox UI + set-equality grading. Lowest risk; ship first.
2. **Fill-in-the-blank (`fill`)** — inline text inputs + accepted-answer grading (decide strictness). Vetter + editor updates.
3. **Drag-and-drop (`match` then `order`)** — the hard one: DnD UI. **Must be mobile-friendly** — use tap-to-select-then-tap-target as the primary interaction (drag is bad on touch), with drag as enhancement.

Each phase touches: model → QuizEngine (render + grade) → quiz-block editor (authoring) → vetter (serialize the new shape) → optionally the generation pipeline.

## Decisions to confirm before building
- **Partial credit vs all-or-nothing per question?** (Recommend all-or-nothing initially — keeps the 5-draw / % model simple; revisit for fill/multi.)
- **Drag-drop scope:** matching, ordering, or both? Confirm **tap-based** interaction for mobile.
- **Fill-in strictness:** case/whitespace-insensitive given; allow per-blank synonym lists? (Recommend yes — middle-schoolers phrase things differently.)
- **Authoring:** manual in the quiz-block editor first; add AI generation of new kinds later (pipeline + the admin AI assistant).

## Verification
Per phase on staging: author one new-kind question in the editor → it renders + grades correctly in the lesson quiz (start-gated) → the vetter classifies it → it counts toward the module-quiz pool. Mobile check for drag-drop.
