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

## 2026-06-15 — Morning briefing: email pipeline retired, replaced by per-person Slack DMs

**Decision:** Killed the old 8 AM "morning briefing" email (`notify.py --morning`, fired as a side-effect of the lesson pipeline, Shane-only, never ran on a real schedule). Replaced with `scripts/morning_briefing.py`: reads open tasks from the platform PM board (Firestore `pm_issues`, via REST), buckets by assignee (overdue / this week / in progress / queued), and has Claude (claude-sonnet-4-6) write a short DM in Shane's voice to each of Cade (QC), Shane (project progress + items), and Ethan (business). Delivery via `slack.py dm <email>`. To feed it automatically: sync route now auto-assigns QC-source tasks to Cade, and moving a task to In Review auto-assigns it to Shane.

**Why:** The old briefing was vestigial (tied to a winding-down content pipeline), email-only, and one-recipient. The team needs role-specific morning context, and the platform now holds the dates/tasks to source it. Hybrid (deterministic data + Claude voice) keeps it reliable and in-voice.

**Alternatives considered:** Pure deterministic template (no voice); pure Claude agent doing everything; platform cron route using Gemini instead of a separate Python job. Direct Firestore gRPC client (hangs off-GCP — switched to REST).

**Open blockers (manual, Shane):** (1) Slack bot needs `users:read.email` + `im:write` scopes added + app reinstall before DMs work. (2) Deploy target: Cloud Run job + Cloud Scheduler (8 AM ET, SA reads Firestore cleanly) — needs deploy. Local ADC is reauth-expired so it can't run from this machine.

**Owner:** Shane.

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

## 2026-05-15 — Google API auth: gws replaced with ADC + custom OAuth client

**Decision:** Replace gws CLI with `google-api-python-client` + Application Default Credentials (ADC) authenticated via a custom GCP OAuth 2.0 Desktop client (`D:\AIOS\oauth-client.json`).

**Why:** GK12 Academy Google Workspace domain enforces RAPT (Re-Authentication Proof Token) policy. gws CLI auth tokens expire after hours to days and break unattended pipelines. Two other paths were also blocked by org policy: service account key generation and gcloud ADC with Google's default OAuth client ID ("access blocked"). The custom Desktop client (created in genesis-aios GCP project) bypasses both restrictions. ADC auto-refreshes without RAPT — no manual reauth needed.

**Auth command:**
```
gcloud auth application-default login --client-id-file="D:\AIOS\oauth-client.json" "--scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/drive"
```

**Alternatives considered:** gws CLI (RAPT breaks it); service account keys (blocked by org policy); default ADC client (blocked by Workspace policy).

**Owner:** Shane / AIOS

---

## 2026-05-15 — Lesson pipeline: thinking tokens disabled, 60K safety limit, markdown stripped

**Decision:** Set `thinkingConfig.thinkingBudget: 0` inside `generationConfig`, cap drafts at 60K chars, and strip markdown from all output via `strip_markdown()`.

**Why:** Gemini 2.5 Flash with thinking enabled produced 428K and 679K char responses — 10–25x the expected draft size. These are thinking token blowouts that cost tokens and corrupt Google Doc tabs. Setting budget to 0 disables thinking entirely. The 60K limit is a hard safety net. Markdown stripping is needed because Gemini ignores "no markdown" instructions inconsistently — `strip_markdown()` cleans `**`, `*`, `#`, `>`, and bullet markers from all output.

**Alternatives considered:** Budget cap (e.g., 2048) instead of full disable — better long-term option but unstable during initial pipeline build. Revisit when pipeline is stable.

**Owner:** Shane / AIOS

---

## 2026-05-15 — Pipeline automation: Task Scheduler daily + hourly tasks registered

**Decision:** Register two Windows Task Scheduler tasks (RunLevel Highest, StartWhenAvailable): daily at 8:05am (20 lessons), hourly from 9am (5 lessons + retry-failed). Both run `pm_agent.py` which orchestrates all downstream agents and pushes manifest to GitHub on completion.

**Why:** June 12 content deadline requires ~27.5 lessons/week. Manual runs are not viable. The daily batch handles the bulk; hourly task catches failures and adds lessons on a rolling basis. GitHub push after each batch keeps the morning briefing agent in sync.

**Alternatives considered:** Single daily batch only (slower failure recovery); cron via WSL (adds complexity, not needed).

**Owner:** Shane / AIOS

---

## 2026-05-15 — Image pipeline: Drive upload via google-api-python-client, stored in MS Curriculum

**Decision:** Image agent uploads generated images to Drive using `google-api-python-client` with `supportsAllDrives=True` on all API calls. Root folder set to `GOOGLE_DRIVE_MS_CURRICULUM_ID`. Folder structure: `MS Curriculum / Creationeering / [Lesson ID] / image.png`.

**Why:** Original gws-based Drive upload had the same RAPT/auth issues as the lesson pipeline. Replacing with ADC-based Drive API calls (`drive` scope) solved 404 errors on folder creation. `supportsAllDrives=True` is required because the GK12 Main drive is a Shared Drive — without it, the API returns 404 even for valid folder IDs.

**Alternatives considered:** Local-only image storage (no Drive access for team); Project Content as root (moved to MS Curriculum on 2026-05-15 for better organization).

**Owner:** Shane / AIOS

---

## 2026-05-15 — AIOS dashboard: PWA project scoped, deferred post-June 12

**Decision:** Build a mobile-first Progressive Web App (PWA) as a separate project after the June 12 content deadline. Not a native app — PWA installs to phone home screen from browser, works on iOS and Android, no App Store required.

**Why:** Shane wants a JARVIS-like interface — pipeline metrics, Google Docs content rendered inline, push notifications, and eventually a conversational layer. ntfy handles alerts well enough for now. Building the dashboard during the content sprint would split focus at the worst time.

**Planned scope (in order):**
1. PWA shell — dashboard with pipeline metrics pulled from manifest on GitHub
2. Google Docs viewer — lesson content rendered inline on phone
3. Push notifications — replace ntfy with built-in web push
4. Chat interface — natural language queries against pipeline state

**Tech:** Next.js, Google Drive/Docs API, hosted on Vercel (free tier).

**Trigger to start:** June 12 content deadline cleared.

**Alternatives considered:** Native iOS/Android app (too slow to build, App Store friction); Notion/Airtable dashboard (no custom pipeline integration).

**Owner:** Shane / AIOS

---

## 2026-05-16 — Assessment agent built; all 38 QC-passed lessons have quizzes

**Decision:** Build `assessment_agent.py` (Gemini 2.5 Flash) to generate 5 MCQ per lesson. Run it across all 38 QC-passed Creationeering lessons. Wire `--generate-assessments` into the Cloud Run nightly entrypoint.

**Why:** Assessments are required for LearnWorlds course completion tracking and certificates. 38 lessons × manual quiz writing = not viable. Gemini generates pedagogically sound MCQs from the lesson draft in under 10 seconds per lesson, total batch cost under $0.05. JSON output stored in `scripts/assessments/[id].json`, manifest updated with `assessment_status: done`.

**Robustness improvements added:** `_clean_json_text()` strips markdown fences and smart quotes; truncation fallback on JSON parse error; maxOutputTokens bumped 2048→4096.

**Result:** 38/38 QC-passed lessons now have assessment JSON files. Zero failures.

**Owner:** Shane / AIOS

---

## 2026-05-16 — LearnWorlds Pro Trainer constraints documented; import workflow TBD

**Decision:** Research LearnWorlds fully before designing the import workflow. Finding: Pro Trainer has no API, no bulk SCORM import, and a 20-SCORM-package cap. Decision on import approach is pending discussion with Shane.

**Why:** The import workflow is the largest unresolved time sink before June 12. Before building anything, needed to know what's actually possible on the current plan. Key constraint: each SCORM package must be manually added as a Learning Activity — no programmatic option without upgrading to Learning Center ($249/mo annual).

**Options on the table:**
- Manual batched upload (time cost unknown)
- Upgrade to Learning Center → API → automate
- Hybrid: ZIP bulk upload for non-SCORM assets; manual SCORM only
- Skip SCORM for launch; use embed or PDF; add SCORM post-launch

**Decision pending:** Shane to decide based on time budget and cost trade-offs.

**Alternatives considered:** Zapier workaround (webhooks are also Learning Center+); scraping the LearnWorlds UI (fragile, unsupported).

**Owner:** Shane

---

## 2026-05-16 — Level-up: meeting-note skill + GK12-Platform project initialized

**Decision:** This week's automation = `/meeting-note` skill (add agenda items to Google Calendar events via MCP). Secondary: initialize `D:\GK12-Platform` as a clean separate git repo for the Gemini AI tutor widget and custom LMS — kept out of AIOS repo to prevent scope creep.

**Why:** Meeting notes to calendar is a high-frequency, low-risk task Shane was doing manually (told Claude what to put in Ethan's event, Claude executed manually). Skill makes it one command. Google Calendar MCP tools added to autorun allowlist so it runs without permission prompts. Platform project isolated so pipeline work and product work don't mix in git history.

**Shipped:**
- `~/.claude/skills/meeting-note.md` — skill registered globally
- `.claude/settings.json` — Calendar MCP tools added to allow list
- `D:\GK12-Platform/` — new git repo, CLAUDE.md with full architecture, COPPA notes, cost model

**KPI:** Time saved on recurring meeting prep. Platform project clean enough to open in a new Claude Code session and start building Phase 1 (AI tutor widget) immediately.

**Owner:** Shane / AIOS

---

## 2026-05-16 — Genesis Education Solutions: standalone platform confirmed, building now

**Decision:** Build a standalone LMS product called "Genesis Education Solutions" — not a LearnWorlds supplement. Genesis K-12 Academy MS courses will launch on this platform (not LearnWorlds). Building starts immediately. Target: August 2026 launch. Repo: `D:\GK12-Platform`.

**Why:** LearnWorlds is a rental. A custom platform gives full control over the AI tutor (key differentiator), data, branding, and long-term pricing. At 500 students, GCP cost is $30–40/month vs $249+/month on LearnWorlds Learning Center. Long-term potential: license the platform to other faith-based homeschool curriculum providers.

**Stack:** Next.js 15 + Firebase (Auth, Firestore, Storage, App Hosting) + Gemini 2.5 Flash-Lite AI tutor. GCP project: genesis-aios (existing).

**LearnWorlds:** Kept as a potential fallback only. Decision on LearnWorlds upgrade tabled — platform build supersedes it. Ethan to be briefed Wednesday.

**COPPA approach:** Parent-account model for MVP. No individual child logins until legal review in Phase 2.

**Owner:** Shane / AIOS

---

## 2026-05-15 — Interactive agent: Claude API added for concept interactives

**Decision:** Add `interactive_agent.py` to the lesson pipeline. Uses Claude (`claude-opus-4-7`) via Anthropic API to generate a custom JS interactive per lesson. Also generates a vocab grid (two-column checkmark style) and OCV tab widget from the lesson draft. Runs automatically via `--generate-interactives` in Cloud Run daily batch.

**Why:** LearnWorlds Starter plan has no API for content. Interactives must be hand-placed or SCORM-imported. Building them per lesson automatically saves 30-60 min of manual work per lesson and ensures every lesson ships with at least 3 reusable HTML components. Claude is better than Gemini for creative JS game generation — Gemini excels at drafting prose, Claude excels at structured interactive UI code.

**Alternatives considered:** Gemini for concept interactives (worse at creative JS); hand-coding interactives (not viable at scale); skipping interactives entirely (misses LearnWorlds engagement features Shane wants).

**Owner:** Shane / AIOS

---

## 2026-05/06 — Build a custom LMS (Genesis Education Solutions), retire LearnWorlds

**Decision:** Build and run our own platform (`D:\GK12-Platform`, Next.js + Firebase App Hosting, project `genesis-modularity`, live at gk12academy.com) instead of hosting the course on LearnWorlds. Deploy via `staging` → fast-forward `main`.

**Why:** LearnWorlds gated the API behind a pricier plan, capped SCORM, and couldn't deliver the AI tutor, custom interactives, workbook, and data we wanted. Owning the stack unlocked everything and is cheaper at our scale (~$0.25–0.35/active student/mo).

**Owner:** Shane / Ethan (approval)

---

## 2026-06-11 — Engineering workbook architecture (Mousetrap-only, block-canvas, AI-seeded)

**Decision:** A separate per-lesson workbook authored on the existing block canvas (`BlockCanvasEditor`) with new workbook field block types; Mousetrap-only; AI-seeds pages from existing lesson content (then human QC); students fill it in the lesson side panel (replacing the old free-form notebook); parents review in the gradebook. Observational (no auto-grading). Printable PDF planned.

**Why:** The build course needs structured lab worksheets; the lessons already contain the prompts, so AI extraction scales authoring. Reusing the block canvas maximized reuse. Full design: `references/workbook-design.md`.

**Owner:** Shane

---

## 2026-06-11 — Anonymous feedback surveys + "Bez" assistant naming

**Decision:** (1) A reusable `survey` block (rating + free text) writes **anonymous** responses (server-side dedupe marker, unlinkable to the response), reviewed in an admin dashboard. (2) Named the AI content assistant **"Bez"** (after Bezalel, the Spirit-gifted craftsman/builder of Exodus 31).

**Why:** Beta needs honest feedback without identifying minors. The assistant needed an identity that fits a faith-based engineering brand.

**Owner:** Shane

---

## 2026-06-12 — Link Slack for two-way chat; refresh the AIOS docs

**Decision:** Connect Slack so the AIOS can read + post in a channel (two-way), and bring the stale AIOS docs (connections, priorities, CLAUDE.md, this log) back in sync with the custom-platform reality. Launch moved July → **August 2026**.

**Why:** The AIOS had drifted a month out of date during the platform build; Slack gives a live ops channel to talk to the AIOS.

**Owner:** Shane / AIOS

---

## 2026-06-21 — Feature scope reduction: AI tutor + blog as "coming soon" for launch; defer custom model

**Decision:** Mark AI Study Assistant (in-lesson tutor, parent tutor history/toggle) as "Coming Soon" for the August 2026 launch via a single `TUTOR_ENABLED = false` flag in `src/lib/features.ts`. Blog is already admin-only with no public route. Defer building a custom/fine-tuned model for the tutor until post-launch at meaningful scale.

**Why:** Pre-revenue with no sales yet — every recurring API cost (Gemini per-token for tutor, Anthropic for Bez/QC) needs to be self-sustaining before it's a launch feature. Lean rollout reduces ongoing cost exposure and simplifies the product story at launch. Custom model research (June 2026) showed self-hosting a GPU costs $250–400/mo minimum vs. ~$8–10/mo for Gemini Flash at 500 students — not economically rational until 5,000+ students. Blog requires a public reader route that doesn't exist yet anyway.

**Re-enable path:** Flip `TUTOR_ENABLED = true` in `src/lib/features.ts` — one line, instant. Per-student `tutorEnabled` Firestore preferences are preserved so parents retain per-child control when it re-enables. For the model: switch to Gemini Flash Lite when activating (same SDK, ~$1–5/mo at 500 students, 5-min migration). Custom fine-tuning only if monthly tutor cost exceeds ~$200 (implies 10,000+ active students).

**Also shipped same session:** model downgrades in AIOS scripts (qc_agent pro→flash, interactive_agent opus→sonnet, morning_briefing sonnet→haiku) — saves ~$15–30 pre-launch + $2.85/mo ongoing.

**Owner:** Shane

---

## 2026-06-21 — Bookkeeping: lean in-platform finance, defer accounting SaaS

**Decision:** Don't buy QuickBooks (or any paid accounting SaaS) yet. Build bookkeeping into the GK12 platform: revenue read live from Stripe + a small admin-entered expense ledger in Firestore, surfaced at `/admin/finance` (P&L cards, revenue detail, expense CRUD) with a monthly-close cron that snapshots the P&L and posts a Gemini-voiced summary to Slack. Defer a formal double-entry ledger (Wave free, or QBO) until an accountant or tax filing actually requires it; at that point export from the platform or connect Stripe→Wave directly.

**Why:** Pre-revenue with a single Stripe revenue stream — a paid QBO seat is premature spend, and most of the value (net income, fees, runway, monthly close) comes from data the platform already has. Keeps with the platform-first / lean ethos. Reuses existing secrets (STRIPE_SECRET_KEY, SLACK_BOT_TOKEN, CRON_SECRET) — no new infra except a monthly Cloud Scheduler job (still TODO).

**Alternatives considered:** QuickBooks Online now (overkill pre-revenue, ~$35–90/mo); Wave free immediately (still external, and the AIOS automation layer is the real leverage); AIOS Python scripts instead of platform routes (Shane chose platform admin route + cron).

**Owner:** Shane / AIOS

---

## 2026-06-16 — Workbook: cross-lab data references + formula calculator + LaTeX steps

**Decision:** Add three linked workbook capabilities for the middle-school course, built on one primitive: addressable student data via human-named reference keys. (1) Named keys on workbook inputs (`refKey` on short-answer, per-column keys on data tables) — keys, not random `block.id`, are the reference so they survive re-authoring and frozen content versions. (2) A `wb-calculator` block: variables bound to keys + block-level constants, a free-form formula run through a safe (no-eval) shunting-yard parser, result written back as its own addressable field. (3) Worked calculation steps rendered in LaTeX via the existing KaTeX renderer (symbolic → values substituted → result), built from the same parsed AST so steps always match the number. Cross-lab references (a `wb-prev-data` display block + cross-lesson calculator inputs) come in Slice 2. Sidebar/multi-window deferred. Full plan: `D:\GK12-Platform\docs\workbook-calculator-plan.md`.

**Why:** The build course needs students to reuse baseline data from prior labs and compute on it (density, average speed, etc.); the workbook already stores every answer at an addressable `(lessonId, fieldId)`, so this is mostly a reference layer + a safe evaluator on top. Named keys (vs raw block ids) chosen for version stability. Free-form formula (vs fixed-operation dropdown) for flexibility, made safe with a dependency-free parser. Slice 1 (same-page) ships value with zero cross-lesson plumbing; Slice 2 adds the headline cross-lab flow.

**Alternatives considered:** Reference raw `block.id` (breaks on re-author/versioning); fixed operation dropdown (less flexible); mathjs/expr-eval dependency (heavier, against the no-eval ethos); sidebar TOC + multi-window as the data-reuse mechanism (only enables manual retyping, not structured reuse — deferred).

**Owner:** Shane

---
