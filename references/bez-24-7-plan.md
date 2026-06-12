# Bez 24/7 — always-on autonomous Slack agent (plan, 2026-06-12)

Goal: message **#aios** from anywhere (phone) and Bez — an AI agent — responds and does real work while Shane is away from the computer.

## Decisions (Shane, 2026-06-12)
- **Capability: FULL** — Bez can do anything Shane can, including editing code and **deploying to prod**.
- **Hosting: Cloud** — runs independent of Shane's PC (works when it's off).

## Guardrails (baked in even at "full")
1. **Shane-only:** act only on messages from Shane's Slack `user_id` (`U0B9TJJGVC7` per #aios join). Ignore everyone else.
2. **Prod-deploy confirmation:** any ff→`main` / prod deploy requires Bez to ask and Shane to reply a typed `CONFIRM DEPLOY`. Staging is free.
3. **Audit trail:** every action (commands run, files changed, commits, deploys) is posted to #aios in-thread.
4. **Kill switch:** `BEZ STOP` aborts the current run; a global pause flag.
5. Secrets in Secret Manager; least-privilege service account.

## Architecture
- **Listener:** `slack_bolt` (Python) in **Socket Mode** (no public URL; outbound WS to Slack). Subscribes to `message.channels` + `app_mention` in #aios. Needs **App-Level token `xapp-…`** (`connections:write`) + the existing bot token `xoxb-…`.
- **Agent:** Anthropic SDK (`anthropic` 0.103.1, already present) tool-use loop OR install Claude Code CLI in the image and drive it headless. Tools (full): `bash`, read/write files, git, gh, firebase. Working dirs: `D:\AIOS` clone + `D:\GK12-Platform` clone. Reuse the deploy workflow (staging→main) + the platform admin scripts.
- **Reply:** stream/post results back to the #aios thread via `scripts/slack.py` logic (chat.postMessage with `thread_ts`).
- **Host:** Socket Mode needs a long-lived process → **small VM (e2-micro) or Cloud Run with `min-instances=1` + CPU always-allocated**. VM is simpler for a persistent WS + git working trees. Container clones both repos on boot (GitHub token), installs node/python/firebase/gh.
- **Secrets (Secret Manager):** `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `GITHUB_TOKEN`, Firebase deploy creds.

## Build steps (when xapp token is in hand)
1. `pip install slack_bolt` locally; prototype the listener (echo) against #aios to confirm Socket Mode.
2. Agent loop: anthropic tool-use with the curated/full tool set + the 4 guardrails; system prompt = Bez persona + repo/deploy context.
3. Dockerfile: python+node, firebase-tools, gh, git; clone repos on boot; run the listener.
4. Deploy to a VM (or Cloud Run min-1); wire Secret Manager.
5. Test: phone → #aios → "what's the deploy status?" → builds up to a staging commit → CONFIRM DEPLOY gate for prod.

## Status: PLANNED. Blocked on Slack **App-Level token (`xapp-…`)** + Socket Mode + `message.channels` event subscription. This is the biggest single build to date — do it as a focused session. Session-based two-way already works today via `scripts/slack.py`.
