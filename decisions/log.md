# Decisions Log

Append-only record of meaningful decisions and why they were made. `/level-up` Phase 2 (Method interview) writes scoped automation specs here. You can also append manually whenever you decide something worth remembering.

**Format per entry:**

```
## YYYY-MM-DD — Short title

**Decision:** what was decided.

**Why:** the reasoning, constraints, and what would change your mind.

**Alternatives considered:** what else was on the table.

**Owner:** who's accountable.
```

Keep it terse. Future-you will thank present-you for capturing the *why*, not just the *what*.

---

## 2026-05-14 — Google Docs tab creation: working method established

**Decision:** Use `gws docs documents batchUpdate` with `addDocumentTab` requests, invoked via Bash (not Python subprocess) with JSON body passed through shell variable from a temp file.

**Why:** Four failure modes hit before landing on this:
1. `gws auth` credentials corrupted — created on a different machine. Fix: `gws auth logout && gws auth login` to re-authenticate.
2. Python `subprocess.run` with `shell=False` can't find `gws` on Windows PATH. Fix: use Bash tool directly or `shell=True` with careful quoting.
3. Docs API operation name is `addDocumentTab`, not `createTab`. The API rejects `createTab` as unknown.
4. Tab titles capped at 50 characters — API returns 400 if any title exceeds this. Must validate and truncate before calling.

**Working pattern:**
```bash
# Write JSON body to temp file (avoids shell quoting issues with large payloads)
# Then call via Bash:
BODY=$(cat "$TEMP/body.json") && gws docs documents batchUpdate \
  --params '{"documentId":"DOC_ID"}' \
  --json "$BODY"
```

**Alternatives considered:** Python subprocess with shell=True (quoting too fragile for large JSON); gws @file syntax (not supported).

**Owner:** Shane / AIOS

---

## 2026-05-14 — MS curriculum agent pipeline: architecture decided

**Decision:** Build a 5-script Gemini-powered pipeline to draft all 110 remaining MS course lessons directly into Google Docs. Four agents (PM, Dev, QC, Media) + one write script. Gemini 2.0 Flash as the drafting model via Google AI Studio API.

**Why:** 110 lessons to write at 15.7/week to hit July launch. Manual drafting is not viable at that pace. Gemini 2.0 Flash is the most resource-efficient model — estimated cost under $0.50 for all 110 lessons once billing is enabled. Architecture keeps Shane in the loop as final reviewer before content is published.

**Pipeline:**
1. PM script — reads audit, selects next empty tab, packages context
2. Dev script — calls Gemini with prompt template → lesson draft (~3,000 words)
3. QC script — calls Gemini with draft + brand guide → pass/fail + notes
4. Write script — pushes approved draft into Google Doc tab via gws
5. Notify script — sends push to Shane's phone via ntfy when batch is ready

**Alternatives considered:**
- Claude API: 50x more expensive (~$7-10 vs ~$0.50); better quality but not justified for first drafts Shane will edit anyway.
- Manual Gemini + write script: removes copy-paste friction but still requires Shane in the drafting loop. Fine as a fallback if billing stays unresolved.
- No agents: unsustainable at 15.7 lessons/week.

**Blocker:** Google AI Studio billing must be enabled before scripts can run. Key is set in `.env`. Workspace accounts don't qualify for the personal free tier.

**Owner:** Shane / AIOS

---

## 2026-05-14 — Image pipeline: Imagen 4 → gemini-2.5-flash-image

**Decision:** Use `gemini-2.5-flash-image` (same API key) instead of Imagen 4 Fast for all curriculum image generation.

**Why:** Imagen 4 is deprecated and shuts down June 30, 2026 (6 weeks from now). Google's documented replacement is `gemini-2.5-flash-image`, available on the same `generativelanguage.googleapis.com` endpoint with no additional auth. Vertex AI style reference images are also off the table — only `imagen-3.0-capability-001` supports them, which is also deprecated.

**What we got instead:** The GK12 logo is passed as `inline_data` with a text instruction to extract the navy/gold palette. Gemini honors the brand colors without needing a Vertex AI reference image endpoint.

**Alternatives considered:** Vertex AI with a service account (requires gcloud + different billing); text-only style prompt (works fine but logo reference is better).

**Owner:** Shane / AIOS

---

## 2026-05-14 — Image agent QC loop + aspect ratio from media agent

**Decision:** Media agent sets `aspectRatio` per image prompt; image agent runs Gemini vision QC after each generation and writes `image_qc_status: passed|flagged` back to `media_prompts.json`; pm_agent runs a rework pass (max 2 retries) after every batch.

**Why:** Keeps quality control in the pipeline rather than requiring manual review of every image. Flagging is automatic; rework is bounded (2 retries cap). Aspect ratio is content-driven — media agent knows whether a section needs a wide diagram or a square close-up better than a hardcoded default.

**Alternatives considered:** Manual image review only; hardcoded 16:9 everywhere (current default anyway but media agent can override).

**Owner:** Shane / AIOS

---

## 2026-05-14 — MS curriculum full audit completed

**Decision:** Treat the full 159-lesson count (89 Creationeering + 70 Mousetrap) as the launch scope. No subsetting for July.

**Why:** Shane confirmed the July Tennessee launch is the full course, not a subset. Mousetrap course was larger than previously known — 46 tabs added today bringing it from 24 to 70 lessons. Updated audit saved at `context/ms-audit-2026-05-14.md`.

**Current state:** 49/159 lessons drafted (31%). 110 to write. Required pace: 15.7/week.

**Owner:** Shane

---
