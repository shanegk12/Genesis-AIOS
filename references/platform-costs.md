# Genesis Education Platform — Monthly Costs & Optimization Playbook

> Living doc. Last updated 2026-06-11. Platform = D:\GK12-Platform (Next.js + Firebase App Hosting + Firestore + Cloud Storage + Gemini). Update as usage and architecture change.

## TL;DR
- **Pre-launch today:** ~**$3–5/month** (basically Secret Manager + domain + a little storage). The platform runs inside Google's free tiers.
- **At ~500 students:** ~**$70–160/month** infra. The **AI tutor (Gemini) is the #1 variable cost.**
- **Our edge:** competitors (LearnWorlds etc.) charge flat **per-seat SaaS** ($249+/mo plus per-seat). Our stack is **usage-based** — marginal cost per student is **pennies**, and the optimizations below push it lower. We pay for what we use; they pay for what they might use.

---

## Current monthly cost (pre-launch, `minInstances: 0`)
| Service | Cost | Notes |
|---|---|---|
| App Hosting (request-time only) | ~$0 | within free tier (180k vCPU-s, 360k GiB-s, 2M req) |
| Firestore | ~$0 | within free 50k reads / 20k writes per day |
| Gemini (testing) | ~$0–2 | |
| Cloud Storage (assets at rest) | ~$0.10–0.50 | lesson images/audio |
| Resend email | $0 | free 3,000/mo |
| Secret Manager (~12 secrets) | ~$0.70 | $0.06/secret/mo |
| Cloud Scheduler | $0 | 3 jobs free |
| Domain (Squarespace) | ~$1.67 | ~$20/yr |
| **Total** | **≈ $3–5/mo** | |

## Projected at ~500 active students
| Service | Est. | Main driver |
|---|---|---|
| **Gemini AI tutor** (2.5-flash) | **$30–50** | tutor chat volume — biggest lever |
| App Hosting (traffic; +~$12 if 1 warm instance) | $20–50 | request CPU + optional warm instance |
| Cloud Storage egress | $10–30 | students loading images/audio |
| Resend (weekly digest ~2–4k emails) | $0–20 | free ≤3k/mo, then $20 |
| Firestore | $1–5 | cheap at this scale |
| Fixed (Secret Mgr + Scheduler + domain) | ~$3 | |
| **Total infra** | **≈ $70–160/mo** | |
| Stripe (per sale) | 2.9% + $0.30 | ~$5.49 per $179 enrollment — revenue cost, self-funding |

**Warm-instance caveat:** `minInstances: 1` on the current 2 vCPU / 2 GiB backend costs **~$12/mo if** App Hosting bills idle instances memory-only (Cloud Run default mode) — but **up to ~$130/mo** if it's CPU-always-allocated. Docs are ambiguous; confirm with a 1-day billing test before enabling. Currently off (~$0).

---

## Steady-state operating cost (course in production — no more content generation)
Once lessons are built, the expensive build-phase work — bulk lesson generation, QC pipeline runs, bulk Imagen — drops to **$0**. What remains is **serving students**. Updated 2026-06-11 with the shipped tutor caps (per-child, 150/day) + review-sheet caching.

**Per active student / month:**
| Item | Est. | Basis |
|---|---|---|
| AI tutor | $0.15–0.20 | ~175 short msgs/mo, gemini-2.5-flash + implicit caching, trimmed history |
| Storage egress (lesson images/audio) | $0.03–0.06 | ~0.3–0.5 GB/mo; cache headers make repeats free |
| App Hosting (page serving) | $0.02–0.05 | SSR requests; first ~200 students mostly free-tier |
| Firestore (progress reads/writes) | <$0.01 | mostly free-tier |
| Review sheets (parent) | ~$0.01 | content-cached per student; regen only on rework |
| **Per active student** | **≈ $0.25–0.35/mo** | tutor is ~60–70% of it |

**Fixed monthly (independent of student count):** ~$2.60 (Secret Manager + domain + assets-at-rest + Scheduler). **+$12/mo** only if a warm instance is enabled.

**By scale (concurrently active students):**
| Active students | Monthly operating |
|---|---|
| 50 | ~$10–18 |
| 200 | ~$45–65 |
| 500 | ~$130–155 |

**Unit economics:** a student takes ~18 weeks (~4 months) to finish, so the **all-in cost to fully service one student through the entire course ≈ $1–3**. Against a **$179** enrollment that's **~1–2% of revenue** — i.e. ~98%+ gross margin on the platform itself (before content labor / overhead). The tutor is the only meaningful variable and it's now hard-capped per child.

---

## Optimization playbook (prioritized — quick wins first)

### 🤖 AI tutor (Gemini) — the biggest lever
1. **Lean on implicit caching (free, already on for 2.5 models).** Put the LARGE, STABLE context first in every request — system prompt → lesson content → rubric — and the dynamic student turn LAST. Implicit cache then hits and bills repeated context at **~25% of normal**. Audit `lib/genkit.ts` / the tutor route to ensure stable context is front-loaded and identical across turns.
2. **Trim conversation history.** Don't resend the whole transcript each turn — cap to the last ~6–8 messages (or summarize older turns). Output/inputs both shrink. (Check the tutor route's `history` payload.)
3. **Cap `maxOutputTokens`.** Output is the expensive half ($2.50/M on 2.5-flash, $9/M on 3.5-flash). A tutor reply rarely needs >~600 tokens.
4. **A/B test `gemini-2.5-flash-lite` (or `gemini-3.1-flash-lite`) for the tutor.** Flash-Lite is **$0.10/$0.40 vs $0.30/$2.50** — ~3–6× cheaper. If tutor quality holds for our Socratic style, this alone could cut tutor cost 60–80%. Keep flash for QC/analysis where quality matters. (Note: old 2.5-flash-lite-preview 404'd — use the current GA lite ids.)
5. **Batch mode (50% off) for everything non-realtime:** QC pipeline runs, weekly-digest AI intros, bulk image generation. Tutor stays real-time (can't batch). The QC/import pipeline is the obvious candidate.
6. **Keep `thinkingBudget: 0`** for short structured outputs (already done in QC). Don't pay for thinking tokens on JSON tasks.
7. **Explicit context cache for lesson content** if many students tutor on the same lesson — cache the lesson text once, reuse across students (up to ~90% off that chunk). Higher effort; revisit at scale.

### 🖼 Storage & egress
1. **Set long `Cache-Control` on every uploaded asset** (`public, max-age=31536000, immutable`). Lesson images/audio rarely change → browser + CDN cache them, so egress drops to near-zero on repeat loads. Add `cacheControl` metadata in the upload paths (`uploadLessonImageSecure`, the AI upload route, audio generation). **Highest-leverage storage win, low effort.**
2. **Convert images to WebP** (50%+ smaller). Use the Firebase Image Processing extension or run through `next/image` (App Hosting auto-optimizes). Apply to lesson images at upload.
3. **Compress lesson audio** (narration is the heaviest egress). Target a lower bitrate (e.g., 64–96 kbps mono for speech) — often 2–3× smaller with no perceptible quality loss.
4. **Serve through the CDN, not raw Storage.** With long cache headers, the App Hosting/Firebase CDN serves repeats from the edge — far cheaper than Storage egress.
5. **Lifecycle cleanup:** delete orphaned/old generated images (the AI assistant + Imagen create many); a Storage lifecycle rule or periodic prune keeps at-rest cost down.

### 🏗 Infrastructure (App Hosting / Cloud Run)
1. **Stay at `minInstances: 0` until revenue** (done). When you want speed, run the 1-day warm-instance billing test; if it's the pricey CPU-always mode, drop the min instance to **1 vCPU / 512–1024 MiB** to cut the warm cost ~4×.
2. **Make marketing pages static/ISR.** `/`, `/courses`, `/about` are currently `force-dynamic` → SSR + cold-start on every hit. Switch to static or ISR (`revalidate`) so the CDN serves them instantly with **no instance cost**. Biggest free perf+cost win for public pages.
3. **Set `Cache-Control` on cacheable routes** so the CDN caches at the edge (`s-maxage` + `stale-while-revalidate`). Fewer requests reach an instance → less CPU billing (CPU is ~80–90% of the bill).
4. **Right-size + concurrency:** current `cpu: 2, memoryMiB: 2048, concurrency: 80`. Reducing request latency (via the caching above) cuts vCPU-seconds more than any knob. Profile before lowering cpu/memory.
5. **maxInstances: 10** already caps spike cost — good.

---

## "Cheaper than the competition" framing
- **LearnWorlds / Teachable / Thinkific:** flat SaaS + per-seat/transaction fees regardless of usage — $250–$500+/mo tiers before you sell a seat.
- **Us:** ~$0 until students arrive, then **pennies per active student** in usage-based infra, with the AI tutor being the only meaningful variable — and that's tunable 60–90% down with the levers above.
- **Result:** our cost scales with revenue, not with our ambitions. That's a structural margin advantage to put in the pitch.

## Sources
[Cloud Run pricing](https://cloud.google.com/run/pricing) · [App Hosting costs](https://firebase.google.com/docs/app-hosting/costs) · [Cloud Run cost-optimization best practices](https://docs.cloud.google.com/run/docs/tips/services-cost-optimization) · [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) · [Gemini batch vs caching](https://yingtu.ai/en/blog/gemini-api-batch-vs-caching) · [Firestore pricing](https://firebase.google.com/docs/firestore/pricing) · [Firebase Storage cost optimization](https://flamesshield.com/blog/optimising-firebase-storage-costs/) · [App Hosting image optimization](https://firebase.google.com/docs/app-hosting/optimize-image-loading) · [Resend pricing](https://resend.com/pricing)
