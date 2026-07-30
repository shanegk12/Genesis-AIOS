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

## 2026-07-30 - Global operator skills: proveit, verify, roast, session-handoff

**Decision:** Installed four skills in the **global** directory `C:\Users\Shane\.claude\skills\`, so they load in every project (AIOS, GK12-Platform, PrivateChef) rather than only this repo. They are operator method, not GK12 work.

- `/proveit` runs BEFORE building. Cheapest probe of the load-bearing assumption. It is the only one allowed to conclude do-not-build.
- `/verify` runs AFTER building. Check at the layer of the claim, then stress test (tails, empty, scale, concurrency, failure paths, idempotence).
- `/roast` convenes a 5-persona council plus a Judge for business-idea validation, ending in GO / RESHAPE / KILL and a cheapest-48-hour test.
- `/session-handoff` produces a chat-only context handoff before clearing the window.

**Why:** `/proveit` and `/verify` were referenced by the fable-mode skill but never existed. Shane's decomposition made them distinct rather than redundant: proveit is logical planning before the work, verify is confirmation and stress testing after it. The test for which one applies is that only proveit can say do-not-build. `/roast` and `/session-handoff` came from https://www.youtube.com/watch?v=iTY8Q449YNQ (transcripts in `references/youtube/`).

**Adaptations from the published files:** fixed download mojibake in both; repointed hardcoded `C:\Users\Nate\...` plan and memory paths in session-handoff to Shane's, and noted memory is per-project keyed by directory slug. Added to roast: a cost warning (five parallel agents is the most expensive thing in the toolkit), an instruction to run the council on Sonnet and keep the Judge on the main model per `references/model-routing.md`, a scope boundary against `/proveit`, and a clause that the council advises but Shane decides. Added to session-handoff: unverified claims must carry across as unverified.

**Corrects the earlier 2026-07-30 fable-mode entry:** that entry records repointing fable-mode's dead `/proveit` and `/verify` references onto `/code-review`, `/security-review`, and `/audit`. Mapping them to `/audit` was wrong, since `/audit` scores the AIOS setup against the Four Cs and is a different job. fable-mode now points at the real `/proveit` and `/verify`.

**Alternatives considered:** Merging proveit and verify into one skill (rejected: they run at different times and only one can conclude do-not-build). Putting them in `.claude/skills/` so Ethan and Cade inherit them (rejected for now: they are Shane's operator method and the game project needs them too; revisit if the team wants them).

**Owner:** Shane

## 2026-07-30 - Adopt the Fable-mode method skill; route orchestration to cheap workers

**Decision:** Installed `fable-mode` (Nate Herk's "Fable method" skill, from https://www.youtube.com/watch?v=XTBWVVcF3Pk) at `C:\Users\Shane\.claude\skills\fable-mode\SKILL.md` — the **global** skills directory, so it loads in every project (AIOS, GK12-Platform, PrivateChef) rather than only in this repo. It is a method skill, not GK12 work, so it does not belong in the team repo. It is a method skill, not a workflow: five gates (scope, evidence, adversarial reasoning, verify, calibrated report) plus standing habits, applied to hard tasks so a cheaper model executes with the discipline of a stronger one. Scoped to GK12-Platform changes, prod/Firestore work, multi-lesson pipeline runs, and deploy debugging. Explicitly NOT applied to routine AIOS chores.

Second half of the same idea: for multi-agent work, prefer a strong orchestrator delegating to cheap workers (Opus orchestrator, Haiku scouts) over same-model-throughout.

**Why:** We do not own the models and cannot count on any tier staying available, but we can own the process. Herk's measured result was that an Opus orchestrator with Haiku scouts cost about 3x less than Opus-with-Opus at the same output quality, and Fable-with-Sonnet matched Fable-with-Fable. This lines up with the 2026-06-21 efficiency pass that already downgraded the pipeline scripts and Bez to Haiku.

**Adaptations from the published file:** fixed mojibake in the gate headings; retargeted the trigger phrases to Shane; removed hardcoded model versions (it was pinned to Opus 4.8 / Sonnet 5); repointed dead skill references (`/proveit`, `/verify`) to our real `/code-review`, `/security-review`, `/audit`; rewrote the "repeating work gets a script" habit to respect the platform-first rule (in-platform admin route, not a local script, since org policy blocks SA keys); added the archives-not-delete rule.

**Not verified:** the ~3x cost figure is Herk's on his workloads, not measured on ours. Worth confirming on a real pipeline run before treating the number as a planning input.

**Owner:** Shane / AIOS

## 2026-07-30 - Model routing table; migrate text-content scripts to Sonnet 5 / Opus 5

**Decision:** Wrote `references/model-routing.md` as the standing reference for which model does which job, and pointed CLAUDE.md at it. It sets the provider split (Claude for dev/admin tooling, Gemini for student-facing and all image generation), a per-job table with current pricing, the orchestrator-plus-cheap-workers pattern, and the effort-level guidance.

Then migrated the text-content scripts off previous-generation models: `revision_agent.py` to `claude-opus-5`, and `interactive_agent.py`, `rewrite_lessons_gdoc.py`, `mousetrap_crop_images.py`, `screenshot_extract_images.py`, `screenshot_import.py`, `qc_generate_simulations.py` to `claude-sonnet-5`. Raised `max_tokens` by roughly 50% on five of them, because Sonnet 5's tokenizer produces about 30% more tokens for the same text and the old limits would truncate.

**Why now:** Text content is finished, so the pipelines are no longer on the critical path and can absorb a change. Cade (cade@gk12academy.com) starts as PM on the HS project in August, and the fewer stale or half-migrated systems he inherits, the better.

**Deliberately not changed:** `scripts/video_pipeline/common.py` stays on Sonnet 4.6 because video content is still in production and the model does not get swapped under a running pipeline. The five Haiku 4.5 call sites are already on the current model; the dated `claude-haiku-4-5-20251001` id is valid, just not the preferred alias, and churning working QC code for cosmetics is a bad trade. `archives/` is frozen.

**Verified:** git diff shows only the intended lines, and all seven files compile. **NOT verified:** no live round-trip. The `ANTHROPIC_API_KEY` in `.env` returns `400 invalid_request_error` for low credit balance, which fires before model validation. Run one script against a real lesson once the API account has a balance. Note that a Claude Pro plan covers Claude Code sessions but does not fund API-key calls; those bill separately.

**Corrected in the same pass:** `gemini-2.5-flash-lite` is live and current, confirmed by a real generateContent round-trip. An earlier memory wrongly called it deprecated by conflating it with `gemini-2.5-flash-lite-preview-06-17`, which is the id that 404s. `scripts/image_agent.py` and `scripts/media_agent.py` were never broken. Separately, `gemini-3.5-flash` returned a 503 for high demand, so do not point an unattended pipeline at it without a fallback.

**Alternatives considered:** Deferring the whole migration until after the August launch (the original recommendation, withdrawn once Shane confirmed text content was finished). Bulk-swapping every call site including the Haiku ones for consistency (rejected: churns working QC code for a cosmetic alias change). Leaving `max_tokens` untouched (rejected: the tokenizer shift would truncate HTML generation silently, which is the worst failure mode here).

**Follow-up:** several of these local scripts may already be superseded by in-platform admin routes under the platform-first rule. Worth auditing before the HS handoff.

**Owner:** Shane / AIOS


## 2026-07-13 — Split platform AI: dev/admin tooling on Claude, student/teacher-facing on Gemini

**Decision:** Formalized a provider split across the whole platform: any AI call an admin/developer triggers (Bez's reasoning, QC auto-flag/fix, quiz bank generation + vetting, interactive editing, workbook generation, finance-close narration, the lesson-editor chat panel) runs on Claude (`ANTHROPIC_API_KEY`). Any AI call a student, teacher, or parent triggers (AI Tutor, grading, support/gmail triage, project feedback) stays on Gemini (`GEMINI_API_KEY`). Migrated 7 routes to Claude in this pass (`qc/generate-bank`, `qc/vet-questions`, `cron/finance-close`, `qc/auto-convert`, `admin/ai/interactive`, `admin/workbook/generate`, `admin/ai` chat) via a new shared `src/lib/anthropic.ts` helper (retry/backoff + a streaming variant), extracted from the pattern already proven in `bezAgent.ts`/`qcAutoflag.ts`. Image generation/editing (Bez's image tools, `ai/generate`, `ai/edit-image`) stays on Gemini regardless of which side triggers it — Claude has no image-gen capability, so that's a hard constraint, not a policy choice.

**Why:** Triggered by discovering the Gemini Developer API's prepaid credits were depleted (`RESOURCE_EXHAUSTED`, 429), which had silently taken down grading, tutor, support triage, and image gen simultaneously — all sharing one billing pool with no isolation. QC auto-flag had already been moved to Claude earlier for a *quality* reason (Gemini mis-flagged truncated block excerpts as "incomplete"), which made the split's fault line obvious in hindsight: dev-tooling and user-facing traffic were already drifting onto different providers organically. Formalizing it gives two independent blast radii instead of one, and sets up clean-by-construction cost accounting: Gemini spend now maps 1:1 to user-facing AI usage, which is the number needed later to price a per-student AI feature fee. Claude spend maps to internal dev-cycle cost, a separate budget question.

**Alternatives considered:** Leaving dev tooling on Gemini and adding Claude only as a failover for user-facing routes when Gemini 429s — rejected for now as a *different, larger* piece of work (real resilience against exactly this outage) rather than the cost-allocation split Shane asked for; still open to do later, tracked as a follow-up, not done here.

**Owner:** Shane (review the diff — especially `admin/ai/route.ts`, the live lesson-editor chat panel — and test in the admin UI before this ships to staging/main; not yet committed).

---

## 2026-07-12 — M-020 rewritten as a step-by-step CAD drawing tutorial, generated without a browser

**Decision:** Rewrote lessons/M-020 (was "Build 3: CAD Analysis of Design Parameters" — Digital Twin/Pareto Frontier/OCV concepts) into "Build 3: Drawing Your Mousetrap Car in CAD" — a 7-step tutorial teaching students to model their real Mark 2.0 car (chassis, front axle, rear axle, lever arm) in the platform's CAD tool. Original content archived to `references/m020-archived-content-2026-07-12.json` (not deleted). Built directly (not via Bez) using Shane's real part measurements (`references/mousetrap-mark2-cad-dimensions.txt`): a Python script generates 7 progressive `ProjectFile` models; the platform's actual `cadCore`/`cadProjection` geometry+projection engine (compiled standalone via `tsc`, run under plain Node — no browser needed) renders true vector engineering-view diagrams per step; `sharp` rasterizes to PNG; images upload to Storage via the GCS JSON API with a `firebaseStorageDownloadTokens` value (same user-OAuth-token pattern as other direct Firestore writes this session — no service-account key involved). `cadConfig.exemplarModelJson` is set to the final assembled model; `cadConfig.rubric` is a new generous, presence-based rubric ("is the part there, roughly right — yes/no", not exact dimensions) for the AI CAD grader.

**Why:** No browser/Playwright tool was available this session to drive the live 3D editor and screenshot it (prior sessions apparently used Playwright and deleted it afterward). Running the platform's own projection math in Node produces genuine CAD output — not a fabricated illustration — and doubles as a live validation of the model against the same code students' work is graded against. Real measurements (not estimates) came directly from Shane and were corrected twice mid-build from his review of the rendered diagrams: (1) rails were sketched on the wrong plane — a hole cut into a "top"-plane sketch bores through the vertical thickness, not left-to-right, so the rail needed to stand on-edge on the "front" plane for the axle hole to bore the correct direction; (2) the mousetrap is flush with the rails' front end, not centered along their length, confirmed against Shane's reference photos of the real car.

**Alternatives considered:** Generating step visuals by having Shane manually screenshot each step in `/admin/cad-lab` — rejected in favor of full automation now that the render pipeline was proven out. Building the lesson via the Bez agent — rejected per Shane's explicit ask to have Claude build this one directly, given the scope (reading the full build-course history, precise real-world measurement reconciliation) suited direct iteration better than a agent's fixed system prompt.

**2026-07-12 follow-up — added sketch-before/extrude-after sub-steps per part:** Shane flagged the 7 milestone images alone did not "connect the dots" between one subassembly-recap image and the next — a step-by-step drawing tutorial needs the actual sketch → operation sequence per PART, not just per subassembly. Expanded to 14 individual parts (deduping mirrored L/R pairs into one taught example each), each getting: a sketch-view diagram (new 2D-only SVG renderer, no cadCore needed — draws the raw add/subtract shapes with dimension lines), a second sketch diagram if the part has a hole (subtract shape added to the same sketch, shown dashed/red), and an after-operation 3D diagram (same cadCore/cadProjection pipeline as before). The 7 original milestone recap images are kept as the concluding image of each subassembly section, per Shane's "keep what we have" instruction. Corrected a real modeling misconception surfaced while building this: our CAD tool cuts holes in the SAME sketch/operation as the base shape — there is no separate "extrude, then cut" two-stage process — so the lesson teaches "sketch the shape, add the hole to that same sketch, then extrude/revolve once," not Shane's originally-pictured 4-step "draw, extrude, draw holes, remove material." Lesson grew from 36 to 125 blocks. Hit and fixed a Windows Python file-encoding bug along the way (`open(path, "w")` defaults to cp1252 on this machine, silently mangling em-dashes — always pass `encoding="utf-8"` explicitly when writing JSON/text from Python scripts on this machine).

**Owner:** Shane (spot-check the 7 diagrams and the exemplar model once more in the admin editor; correct the rubric wording if the AI grader proves too strict/lenient after real student submissions).

---

## 2026-07-11 — Gate reviews are AI-graded lesson blocks; the AI grade is the sign-off

**Decision:** Gate reviews (starting with M-024 Analysis Gate Review) ship as a `gate-review` lesson block, not a standalone assignment object. Students answer per-section questions in the lesson; Gemini grades each section Pass/Not Yet against the authored criteria and the AI grade replaces the paper teacher signature. Pass/fail only — 50 pts awarded on an overall pass (all sections must pass), unlimited attempts, `passed` is sticky, and a Not Yet never counts against the course grade ("a Not Yet is an instruction, not a failure"). Progress at `progress/…/gateReviews/{lessonId}`; passes blend into the records-page grade weighted by points. Bez can create and edit these blocks (propose → approve). Deployed to prod 2026-07-11 (`e13c3ed`, `ee8b5b0`).

**Why:** Blocks are the platform's native unit for in-lesson graded work (quiz, CAD) — reusing the pattern got grading, versioning, QC, autosave (interactiveState), and security rules for free, and makes future gates (Synthesis, final) a block-picker drop-in. AI-as-signature keeps the homeschool parent out of a rubric-grading job while preserving the formal checkpoint. Points-only-on-pass avoids punishing honest early attempts, which the M-024 content explicitly values.

**Alternatives considered:** Unit-level assignment item (like CAD assignments) — rejected: gate content already lives in the lesson, and unit items don't support legacy child accounts. Percentage scoring — rejected: a gate is binary by definition.

**Owner:** Shane (validate AI grading judgment with a real submission; tune criteria text in the block if the grader is too lenient/strict).

---

## 2026-07-08 — Automated support pipeline paused; Ethan handles support directly

**Decision:** Pause the `gmail-support-poll` Cloud Scheduler job (every 5 min, polls shane@'s inbox for mail to team@gk12academy.com, Gemini-triages, auto-replies/creates `supportTickets`). Ethan will respond to support emails directly from the inbox until company growth hits a metric worth revisiting. Code and infra (Gmail OAuth, triage prompt, `/admin/support`, `/support` public form) stay in place, untouched — this is a scheduler pause, not a rollback. Resume with `gcloud scheduler jobs resume gmail-support-poll --location=us-central1`.

**Why:** Ethan wants hands-on with support while volume is low; automation should come back once volume justifies it. Pausing the scheduler (vs. ripping out code or adding a feature flag) is the fastest, fully-reversible lever and requires no deploy.

**Alternatives considered:** Feature-flag gate (like `TUTOR_ENABLED`) to keep ticket creation but skip AI auto-reply — rejected per Ethan's call to stop the whole pipeline, not just the auto-reply step, so support emails go straight to his attention instead of sitting in an admin queue.

**Note:** While pausing, new support emails to team@gk12academy.com will sit unread in shane@'s inbox (incl. spam) with no ticket created — Ethan needs to check that inbox directly, not `/admin/support`. Separately, Shane flagged hourly DMARC aggregate report emails cluttering the inbox — unrelated to this pipeline (DNS/DMARC record issue, not yet investigated).

**Owner:** Shane (execution — local `gcloud` auth was reauth-expired, needs `gcloud auth login` to actually run the pause command). Ethan (support response owner going forward).

---

## 2026-07-08 — DMARC aggregate reports rerouted off team@ to stop inbox clutter

**Decision:** Changed the `_dmarc.gk12academy.com` TXT record's `rua` (aggregate report) recipient from `team@gk12academy.com` (a Google Group that forwards into Shane's inbox, generating frequent report emails) to the existing `gkassistant@gk12academy.com` mailbox. Record now reads `v=DMARC1; p=none; rua=mailto:gkassistant@gk12academy.com`. Verified live via DNS lookup 2026-07-08.

**Why:** DMARC reports were cluttering Shane's inbox multiple times a day. Rerouting keeps deliverability/spoofing monitoring intact (important now that Resend sends real customer email) without disabling it, and reuses an existing mailbox instead of provisioning a new Workspace seat or Google Group.

**Alternatives considered:** New dedicated Workspace user (costs a license seat) or a new no-membership Google Group (free, but extra setup) — both rejected in favor of the already-existing `gkassistant@` mailbox. Also considered just Gmail-filtering the reports (no DNS change) or dropping `rua` entirely (loses monitoring) — rejected.

**Owner:** Shane (DNS edit made manually in Squarespace Domains).

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

## 2026-07-08 — Retire the morning briefing pipeline entirely

**Decision:** Shut down and remove the 8 AM ET Slack morning briefing. Deleted Cloud Scheduler `morning-briefing-8am`, Cloud Run Job `morning-briefing`, the dedicated `morning-briefing@genesis-modularity` service account, and the `bez/morning-briefing` container images. Local pipeline files (`scripts/morning_briefing.py`, `cloud/briefing.Dockerfile`, `cloud/briefing.cloudbuild.yaml`, `cloud/BRIEFING_DEPLOY.md`) moved to `archives/morning-briefing/` per the archive convention.

**Why:** Shane asked to stop the daily Slack briefing and remove the pipeline. The `slack.py dm` command and PM board auto-assign rules it relied on remain in place — only the briefing itself is gone.

**Alternatives considered:** Pausing the scheduler only (keeps dead infra + a stale image around; Shane asked for removal, not a pause).

**Owner:** Shane / AIOS

## 2026-07-08 — Resettable test-account purchase flow (Stripe test mode)

**Decision:** Add a first-class test-account flow to the platform so the full purchase path (store → Stripe Checkout → webhook → claim email → claim → dashboard) can be exercised end-to-end, repeatedly, with fixed credentials (eqondrick1@liberty.edu). Accounts listed in Firestore `testAccounts/{email}` get their checkout session created with a new `STRIPE_TEST_SECRET_KEY` (test cards work, no real charge), with live prices mirrored via inline `price_data`. A test-mode webhook endpoint is auto-provisioned on first use and its signing secret stored in `config/stripeTestWebhooks`; the webhook route verifies live secret first, then test secrets. The claim token/enrollment carry `test: true`; when the dashboard sees an active test enrollment it calls `/api/test-account/reset`, which deletes the enrollment + test claim tokens so the same credentials work again. Claim page also gained a fallback: existing email+password credentials sign in and claim instead of erroring. Admin registry API at `/api/admin/test-accounts`.

**Why:** Shane was creating a new account for every purchase-flow test. This keeps the flow high-fidelity (real Stripe UI, real webhook, real Resend email with [TEST] subject) while making it repeatable and free.

**Alternatives considered:** 100%-off promo codes (skips the card/webhook path); pointing the whole staging backend at test keys (diverges staging from prod and breaks shared-Firestore claim flows); manual Firestore cleanup after each test (the thing being eliminated).

**Note:** STRIPE_TEST_SECRET_KEY currently holds the Stripe CLI's test key, which expires 2026-08-19. Replace with a durable restricted test key from the Stripe dashboard before then if test flow is still needed.

**Owner:** Shane / AIOS

---

## 2026-07-10 - Keep existing lesson IDs; no nomenclature migration

**Decision:** Lesson IDs stay as-is (C-xxx / M-xxx / ad-hoc like CM-9-2-5 for new lessons). No bulk rename to a CM-Module-Unit-Lesson scheme.

**Why:** IDs are machine-internal and deeply persisted: doc IDs + versions subcollections, unit.lessonIds, assessment pools, per-student progress/workbook/interactiveState/CAD data, Storage paths and token URLs embedded in block content, plus external refs (Drive folders, QC sheet, pipeline manifest). The HS course will be produced by duplicate-course from the MS course, which already mints fresh internal IDs - so human-meaningful IDs buy nothing there. Position-encoded IDs (CM-9-2-5) also go stale the moment a lesson is reordered or moved.

**Alternatives considered:** Full ID migration (about a day of careful batch work + re-keying student data; risky, no payoff). Computed display code derived from module/unit/order shown in admin (cheap, always accurate) - available later if board readability ever warrants it.

**Owner:** Shane

## 2026-07-10 — Course videos: animated pipeline, Veo Fast quality bar, business videos standalone

**Decision:** The Dr. Horstemeyer studio shoot (68 videos, "MS Video Summary/Outline 4.26") never happened; the course videos will be generated by the AIOS video pipeline (scripts/video_pipeline + video-studio Remotion project) instead. Scope: 10 module intros + 18 topic intros + 38 lesson videos, Creationeering only. Quality: option D — Veo 3.1 **Fast tier only** for cinematic b-roll; a scene either earns a Fast clip or uses slides/Manim instead (never the Lite tier). Higgsfield dropped; render layer is Remotion + Manim hybrid. Business-module videos (C-BIZ-*) render to their own folder and are never auto-attached — Shane places them in business lessons/activities manually. WTC examples in the outline replaced with the Columbia case study (Topic Intro 5, Lesson Anecdote 25). Dr. H personal anecdotes become third-person case studies.

**Why:** Media team never delivered footage; August launch needs videos. Animated hybrid keeps cost ~$60–90 one-time (vs $1.3k–5k pure text-to-video) while keeping on-screen text accurate. Fast-only bar because low quality isn't worth the ~$100 delta ("selling two courses covers option A"). Columbia teaches the same failure-analysis concepts as WTC without terrorism weight for ages 11–14.

**Alternatives considered:** Pure text-to-video (too expensive, unreliable text); Veo Lite everywhere (~$110–140, quality risk — rejected); slides-only (~$40, not engaging enough for launch); Higgsfield (extra vendor/account, dropped).

**Owner:** Shane (approvals per video via video-plan.json); AIOS runs the pipeline.

## 2026-07-10 — Course videos: own pipeline over market tools; ElevenLabs narration

**Decision:** Scale course-video production on the in-house pipeline (scripts/video_pipeline + Remotion/Manim/Veo). Market comparison ended before testing: Higgsfield's plans don't include enough monthly credits to produce even one ~3-minute video, making it drastically more expensive than our ~$1–3/video marginal cost. Narration upgrades from Google Neural2-J to ElevenLabs (pending Shane's account + ELEVENLABS_API_KEY; A/B on the Module 1 intro first).

**Why:** Pilot v3 met the quality bar after content-rule fixes (no lesson IDs, no ™, clip-tail handoff, live module names from Firestore). Own pipeline gives exact on-screen text, brand lock, versionable storyboards, and platform auto-attach; subscription tools would add recurring cost against the 2026-06-21 self-sustaining rule.

**Alternatives considered:** Higgsfield Long Video Generator (credit economics fail); Synthesia/invideo avatar+template tools (untested — moot once Higgsfield pricing killed the category for us).

**Owner:** Shane (ElevenLabs account + per-video approvals); AIOS runs the pipeline.
