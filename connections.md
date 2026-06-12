# Connections

Registry of every system your AIOS can reach. `/audit` checks this file for domain coverage and freshness.

> **Major shift since the original registry (2026-05):** Genesis built its **own custom LMS** — *Genesis Education Solutions* (`D:\GK12-Platform`, Next.js + Firebase, live at **gk12academy.com**). It **supersedes LearnWorlds** as the course platform. The old `genesis-aios` Cloud Run nightly pipeline is retired in favor of on-demand Python agent scripts in `D:\AIOS\scripts` that call the platform's admin APIs.

| # | Domain | Tool | Mechanism | Auth | Last checked |
|---|---|---|---|---|---|
| 1 | **Course platform (LMS)** | **Genesis Education Solutions** (custom, `D:\GK12-Platform`) | Next.js on Firebase App Hosting; admin APIs under `/api/admin/*` | `ADMIN_API_KEY` bearer (scripts) / Firebase admin ID token (UI) | 2026-06-12 |
| 2 | Hosting / infra | Firebase App Hosting (project `genesis-modularity`) | backends: `genesis-lms` (prod) + `genesis-lms-staging`; deploy = push `staging` → ff `main` | gcloud/firebase ADC | 2026-06-12 |
| 3 | Database + files | Firestore + Firebase Storage (shared prod/staging) | client SDK + Admin SDK; rules in `firestore.rules` | Firebase | 2026-06-12 |
| 4 | Payments | Stripe | Checkout + webhooks; `STRIPE_*` secrets | App Hosting secrets | 2026-06-12 |
| 5 | Transactional email | Resend | `lib/email.ts`; weekly digest cron; `RESEND_*` | App Hosting secrets | 2026-06-12 |
| 6 | Analytics | GA4 (`G-33KHYVFZQ5`) + Firestore `conversions` | `lib/analytics.ts` dual-write | — | 2026-06-12 |
| 7 | Domain / DNS | gk12academy.com | Squarespace Domains → Firebase App Hosting | — | 2026-06-12 |
| 8 | AI — content/tutor/Bez | Gemini 2.5 Flash (Genkit) | `lib/genkit.ts`; admin assistant **"Bez"**, tutor, QC, workbook AI-seed | `GEMINI_API_KEY` (App Hosting + Secret Manager) | 2026-06-12 |
| 9 | AI — images | Imagen 4.0 (`imagen-4.0-fast-generate-001`) | admin AI image gen + pipeline | `GEMINI_API_KEY` | 2026-06-12 |
| 10 | AI — heavy interactives | Claude (Anthropic API) | `scripts/qc_generate_simulations.py` etc. | `ANTHROPIC_API_KEY` | 2026-06-12 |
| 11 | Email (read/draft/labels) | Gmail | MCP `claude_ai_Gmail` | Claude managed connector | 2026-06-12 |
| 12 | Calendar | Google Calendar | MCP `claude_ai_Google_Calendar` | Claude managed connector | 2026-06-12 |
| 13 | Curriculum source | Google Drive + Docs | `google-api-python-client` (scripts) | ADC via `oauth-client.json` | 2026-06-12 |
| 14 | Content pipeline (agents) | Python scripts in `D:\AIOS\scripts` | call platform admin APIs (`/api/admin/lessons`, `/interactives/library`, `/workbook/generate`, …) | `ADMIN_API_KEY` (a.k.a. `PIPELINE_KEY`) in `.env` | 2026-06-12 |
| 15 | Google API auth (DwD) | pipeline-runner service account | `scripts/_gws_auth.py` impersonates shane@gk12academy.com | `gk12-sa-key.json` (DwD) | 2026-06-12 |
| 16 | Source control | GitHub (`shanegk12/genesis-education-solutions`) | local git; `gh` CLI | — | 2026-06-12 |
| 17 | **Team chat** | **Slack** | **two-way MCP — SETUP IN PROGRESS** (see below) | TBD | — |
| 18 | Bookkeeping | QuickBooks (planned) | not yet connected | — | — |
| 19 | Task tracking | None yet | not yet connected | — | — |

## Platform deploy workflow
Build on `staging` branch → validate → fast-forward `main` (prod). App Hosting auto-builds on push. Firestore rules are **shared** prod+staging (`firebase deploy --only firestore:rules`). App Hosting secrets: `firebase apphosting:secrets:grantaccess` on **both** backends. Prod URL `genesis-lms--genesis-modularity.us-central1.hosted.app`; staging `genesis-lms-staging--…`. Note: App Hosting builds occasionally fail on transient `npm ECONNRESET` — just re-trigger (empty commit).

## Slack — two-way linking (in progress, 2026-06-12)
Goal: talk to the AIOS from a Slack channel (read history, post, respond on command). **Needs a Slack app + token from Shane.**

**Path A — Claude managed connector (easiest if available):** in Claude (desktop/Code) integrations, authorize the **Slack** connector (same as Gmail/Calendar). Its `mcp__claude_ai_Slack__*` tools then appear; allowlist them in `.claude/settings.json`.

**Path B — self-hosted Slack MCP (fallback):**
1. api.slack.com → **Create New App** (from scratch) in the GK12 workspace.
2. **OAuth & Permissions** → Bot scopes: `channels:history`, `channels:read`, `chat:write`, `groups:history`, `users:read`, `search:read`. Install to workspace → copy the **Bot token** `xoxb-…`.
3. (For socket/event listening) **Basic Information** → App-Level Token with `connections:write` → `xapp-…`.
4. Paste the tokens to me; I register a Slack MCP server (`claude mcp add`) + allowlist its tools, and update this row to "connected."

Once connected: AIOS posts updates (deploy/pipeline/briefing) AND responds to messages in the chosen channel.

## ADC Auth (Google APIs)
All Google API calls use ADC via a custom Desktop OAuth client. Re-auth: `python scripts/reauth_adc.py` (gcloud `--scopes` is broken on the GK12 domain). Credentials: `D:\AIOS\oauth-client.json`; DwD service-account key: `D:\AIOS\gk12-sa-key.json` (gitignored).

## Retired
- **LearnWorlds** (Pro Trainer) — replaced by the custom platform. No longer the course host.
- **`genesis-aios` Cloud Run nightly pipeline** — replaced by on-demand `scripts/*` agents calling the platform admin APIs.
