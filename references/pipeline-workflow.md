# GK12 Lesson Pipeline — Workflow Reference

*Last updated: 2026-05-15*

---

## Architecture Overview

> **Stale as of 2026-07-30.** This diagram describes the retired Cloud Run *Job*
> batch design and its `entrypoint.sh`, which has been deleted. What runs today is
> the Cloud Run *service* `gk12-pipeline-worker`: `startup.sh` → gunicorn →
> `scripts/pipeline_worker.py`, with `/dispatch` fanning lessons out through Cloud
> Tasks to `/process` one at a time. The per-lesson steps below are still accurate.

```
Cloud Scheduler (8:05am CDT daily)
  └─> Cloud Run Job: gk12-lesson-pipeline   [RETIRED]
        └─> entrypoint.sh                    [deleted 2026-07-30]
              ├─ git clone Genesis-AIOS (fresh each run)
              └─ pm_agent.py --course both --batch 20 --type all
                               --generate-images --generate-interactives
                    │
                    ├─ [for each lesson in queue]
                    │    ├─ 1. lesson_pipeline.py  → Google Doc tab
                    │    ├─ 2. qc_agent.py         → manifest (scores + flags)
                    │    ├─ 3. media_agent.py       → media_prompts.json
                    │    ├─ 4. interactive_agent.py → interactives/[id]/*.html
                    │    └─ 5. image_agent.py       → Google Drive
                    │
                    ├─ git commit + push manifest, media_prompts, interactives
                    └─ notify.py → ntfy.sh → Shane's phone
```

---

## Step-by-Step Data Flow

### Step 1 — Lesson Draft (`lesson_pipeline.py`)

| Field | Value |
|---|---|
| Model | Gemini 2.5 Flash |
| Tools | Google Search grounding (Works Cited), Horstemeyer 2022 PDF (File API) |
| Input | Topic, phase, previous lesson, prompt template |
| Output | ~3,000-word draft written directly to Google Doc tab via ADC |
| Config | thinkingBudget: 2048, maxOutputTokens: 24576, temp: 0.7 |
| Safety net | 60K char hard limit — rejects thinking blowouts before writing |
| Post-process | strip_markdown() removes **, *, #, >, bullets from all output |

### Step 2 — Quality Check (`qc_agent.py`)

| Field | Value |
|---|---|
| Model | Gemini 2.5 Pro (independent from drafter) |
| Input | Lesson draft (first 6,000 chars) |
| Output | Manifest updated: qc_status, qc_scores (5 dimensions + overall), qc_notes |
| Config | thinkingBudget: 1024, maxOutputTokens: 4096, temp: 0.2 |
| Structural check | No API call — validates required sections, word count (2,000–4,000), frameworks, scripture |
| Threshold | Pass = overall ≥ 2 AND no individual score of 1 |
| On fail | Lesson flagged, pipeline continues — does NOT block or re-draft |

Structural check criteria:
- Required sections present (Lesson Overview, Learning Objectives, Key Vocabulary, Engineering Journal, Technical Documentation, Summary, Works Cited)
- Word count in range
- Creationeering, Multiscale, OCV frameworks all mentioned
- At least one scripture reference (book:chapter pattern)

### Step 3 — Image Prompts (`media_agent.py`)

| Field | Value |
|---|---|
| Model | Gemini 2.5 Flash Lite |
| Input | Draft (first 5,000 chars), topic, style guide prefix |
| Output | media_prompts.json — one entry per lesson, 5–7 prompts (cover + per section) |
| Config | No thinking, maxOutputTokens: 2048, temp: 0.6 |
| Prompt format | 60–90 words per prompt, section label, concept tag, aspectRatio (16:9 or 1:1) |

### Step 4 — Interactives (`interactive_agent.py`)

| Field | Value |
|---|---|
| Models | None (vocab/OCV parsing), Claude claude-opus-4-7 (concept interactive) |
| Input | Lesson draft (full text) |
| Output | scripts/interactives/[lesson-id]/vocab.html, ocv.html, concept.html |
| Manifest | interactive_status (done/partial/failed), interactive_files paths |

Three outputs per lesson:
- **vocab.html** — Two-column checkmark grid. Parsed from Key Vocabulary table in draft. No API call.
- **ocv.html** — Three-tab widget (Objective / Constraints / Variables) with student text input. OCV content parsed from draft. No API call.
- **concept.html** — Claude-generated custom JS interactive (drag-drop, quiz, trade-off slider, or simulation). Appropriate to lesson topic. ~8,000–14,000 chars, fully self-contained.

### Step 5 — Image Generation (`image_agent.py`)

| Field | Value |
|---|---|
| Generation model | gemini-2.5-flash-image |
| QC model | Gemini 2.5 Flash Lite (vision) |
| Input | media_prompts.json, GK12 logo (inline_data for color reference) |
| Output | PNG files in output/images/[course]/[lesson-id]/ + uploaded to Google Drive |
| Drive structure | GK12 Main > MS Curriculum > [Creationeering\|Mousetrap Build] > [Lesson ID] |
| QC criteria | Color palette, style (clean illustration), concept fit, age-appropriate |
| Retry | Max 2 rework attempts on flagged images |

---

## AI Model Assignments

| Task | Model | Rationale |
|---|---|---|
| Lesson drafting | Gemini 2.5 Flash | Cheap at scale, Google Search grounding for Works Cited, File API for Horstemeyer PDF |
| Lesson QC | Gemini 2.5 Pro | Better reasoning for nuanced rubric scoring; independent from drafter model |
| Image prompts | Gemini 2.5 Flash Lite | Simple JSON generation, no quality-critical output |
| Concept interactive | Claude claude-opus-4-7 | Superior structured code generation for complex, creative JS activities |
| Image generation | gemini-2.5-flash-image | Only available option (Imagen 4 deprecated June 30, 2026) |
| Image QC | Gemini 2.5 Flash Lite | Fast binary vision check |

**Rule of thumb:** Gemini for long-form prose and image generation. Claude for code and structured creative output.

---

## Estimated Cost Profile

Per lesson (all 5 steps):

| Step | Cost (est.) |
|---|---|
| Lesson draft (Gemini Flash) | ~$0.003 |
| QC (Gemini Pro) | ~$0.015 |
| Image prompts (Gemini Lite) | ~$0.001 |
| Concept interactive (Claude Opus) | ~$0.17 |
| Image generation (5–7 images) | ~$0.03 |
| **Total per lesson** | **~$0.22** |
| **110 remaining lessons** | **~$24 total** |

Claude interactives are the largest cost item by far (~77% of per-lesson cost). Acceptable given the value — each lesson ships with a custom JS game that would take 1–2 hours to build manually.

---

## Persistence Map

| Artifact | Stored in | Committed to GitHub |
|---|---|---|
| Lesson draft | Google Doc tab | No (source of truth is the Doc) |
| QC scores + flags | lessons_manifest.json | Yes (daily) |
| Image prompts | media_prompts.json | Yes (daily) |
| Interactive HTML files | scripts/interactives/[id]/ | Yes (daily) |
| Generated images | Google Drive + output/images/ (local) | No |
| Image QC records | media_prompts.json | Yes (daily) |

---

## Auth

| Service | Method |
|---|---|
| Google Docs / Drive | ADC via custom OAuth Desktop client (oauth-client.json) |
| Gemini API | GEMINI_API_KEY in .env / Cloud Run Secret Manager |
| Claude API | ANTHROPIC_API_KEY in .env / Cloud Run Secret Manager |
| ntfy.sh | Bearer token (NTFY_TOKEN) |
| GitHub | GITHUB_TOKEN in Cloud Run Secret Manager |

**In Cloud Run:** Service account auto-handles Google auth. No RAPT, no manual reauth.
**Locally:** `gcloud auth application-default login --client-id-file="D:\AIOS\oauth-client.json"`

---

## Human Touchpoints

| Trigger | Action |
|---|---|
| ntfy completion push (daily) | Shane reviews any QC-flagged lessons in Google Doc |
| Lesson flagged (qc_status=flagged) | Human eyeball: accept as-is, fix headers manually, or reset to pending for re-draft |
| Lesson flagged (structural only, Gemini score ≥ 2.6) | Usually a section header naming mismatch — quick manual fix |
| Lesson flagged (low Gemini score) | Reset to pending for full re-draft |
| Concept interactive review | Open concept.html in browser before placing in LearnWorlds |
| Image QC flagged | Runs auto-rework (max 2 retries) — review Drive folder if still failing |

---

## Course Registry

| Course | ID Prefix | Doc Key | Lessons |
|---|---|---|---|
| Creationeering | C- | creationeering | 89 total |
| Mousetrap Build | M- | mousetrap | 70 total |
| Future build courses | TBD | TBD | — |

Courses are architecturally separate — distinct Google Docs, ID namespaces, manifest entries, and Drive folders. Adding a new course requires only a new prefix + Doc ID; no pipeline code changes.

---

## Key Commands

```powershell
# Check pipeline status
python scripts/pm_agent.py --status

# Manual batch run (5 lessons, both courses)
python scripts/pm_agent.py --batch 5 --course both --type all

# Re-run QC on all lessons with missing scores
python scripts/rerun_qc.py

# Re-run QC on specific lessons
python scripts/rerun_qc.py --ids C-034 C-038

# Generate interactives for one lesson (reads from Google Doc)
python scripts/interactive_agent.py --lesson-id C-025

# Re-generate QC-flagged images
python scripts/image_agent.py --rework-flagged

# Send manual status push to phone
python scripts/status_report.py
```

---

## Known Gaps / Open Items

| Gap | Impact | Suggested fix |
|---|---|---|
| No targeted section revision | When QC flags one section, only option is full re-draft (slow, costly) | Build a `revision_agent.py` — passes flagged section + QC notes to Claude for targeted rewrite |
| No quiz/assessment generation | Shane writes quiz questions manually for LearnWorlds | Add `assessment_agent.py` after QC pass — generates 5 MCQ per lesson via Gemini Flash |
| No LearnWorlds content bridge | Lesson title, description, unit copy must be manually entered in platform | Claude or Gemini reads draft → outputs LearnWorlds-ready metadata JSON |
| Interactive files not yet in SCORM format | LearnWorlds Starter requires SCORM ZIP for bulk import | Wrap interactives in imsmanifest.xml + ZIP per lesson |
