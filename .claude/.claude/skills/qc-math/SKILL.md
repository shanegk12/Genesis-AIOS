---
name: qc-math
description: Extracts display-math LaTeX ($$...$$) from lesson text blocks into dedicated math blocks, preserving all surrounding prose. Run after migrate_markdown_html.py and before qc_auto_convert.py. Trigger on "run math conversion", "extract math blocks", "fix latex formatting", or "qc math".
---

## What this skill does

Scans all done lessons for `$$...$$` display-math patterns trapped inside text block HTML, extracts them into typed `math` blocks, and keeps surrounding text in correctly ordered text blocks.

Operates on the live platform via the admin API. Dry-run mode available.

## When to run

- After running `migrate_markdown_html.py` (lessons are now multi-block but still have raw LaTeX in paragraphs)
- Before `qc_auto_convert.py --save` (so math blocks don't get passed to Gemini by accident)
- Any time the curriculum team adds new lessons with LaTeX notation

## Split logic

For a text block containing:
```
<p>Newton's second law:</p>
<p>$$F = m \cdot a$$</p>
<p>Where F is force, m is mass, and a is acceleration.</p>
```

Output is THREE blocks in order:
1. Text block → `<p>Newton's second law:</p>`
2. Math block → `{ latex: "F = m \\cdot a", display: true }`
3. Text block → `<p>Where F is force, m is mass, and a is acceleration.</p>`

Inline `$...$` math is left in text blocks — rendered client-side by LessonRenderer via KaTeX.

## Execution steps

### Step 1 — Dry run (always first)
```
python scripts/qc_math_convert.py --dry-run
```
Review output: each lesson lists equations that would be extracted.

### Step 2 — Apply
```
python scripts/qc_math_convert.py
```

### Step 3 — Optional: single lesson or course filter
```
python scripts/qc_math_convert.py --lesson-id C-033
python scripts/qc_math_convert.py --course C
python scripts/qc_math_convert.py --course M
```

### Step 4 — Follow-up QC (optional)
After math extraction, re-run QC auto-convert to catch any new vocab/callout blocks that appeared when the math paragraph was removed:
```
python scripts/qc_auto_convert.py --save
```

## Platform support

Math blocks (`type: "math"`) are fully supported:
- **Student renderer** (`LessonRenderer.tsx`): renders via KaTeX with display mode
- **Admin editor** (`BlockCanvasEditor.tsx`): live LaTeX preview with display toggle
- **Block type**: `{ id, type: "math", data: { latex: string, display: boolean }, meta: BlockMeta }`
- **blocksToHtml**: serializes to `<div data-math-display="...">` for legacy fallback

## Output contract

- Log written to `scripts/qc_math_log.json` (lesson ID → block counts + timestamp)
- All extracted blocks get fresh UUIDs
- Original block `meta` is preserved on surrounding text blocks
- Math blocks always get `qcStatus: "pending"` for review

## Inline math note

`$F=ma$` inline patterns remain in text blocks. KaTeX is loaded globally in LessonRenderer — these render correctly in the student view without any migration. If they need editing, use the rich text editor's "∑ inline" toolbar button.
