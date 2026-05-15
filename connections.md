# Connections

Registry of every system your AIOS can reach. Filled by `/onboard` from Q4-Q7 answers; expanded over time as you wire new tools. `/audit` checks this file for domain coverage and freshness.

| # | Domain | Tool | Mechanism | Auth | Last checked |
|---|---|---|---|---|---|
| 1 | Revenue / Financials | QuickBooks (planned) + business bank account | not yet connected | — | — |
| 2 | Customer interactions / Storefront | LearnWorlds | not yet connected | — | — |
| 3 | Calendar | Google Calendar (Google Workspace) | gws CLI (`gws calendar`) | OAuth via gws | 2026-05-14 |
| 4 | Communication | Gmail (Google Workspace) | gws CLI (`gws gmail`) | OAuth via gws | 2026-05-14 |
| 5 | Project / task tracking | None yet | not yet connected | — | — |
| 6 | Meeting intelligence | None yet | not yet connected | — | — |
| 7 | Knowledge / files | Google Drive (Google Workspace) | gws CLI (`gws drive`) | OAuth via gws | 2026-05-14 |
| 8 | AI drafting | Gemini 2.5 Flash (lesson drafts) | `scripts/lesson_pipeline.py` | `GEMINI_API_KEY` in `.env` | 2026-05-14 |
| 9 | AI image generation | gemini-2.5-flash-image (replaces Imagen 4, deprecated June 30 2026) | `scripts/image_agent.py` | `GEMINI_API_KEY` in `.env` | 2026-05-14 |
| 10 | Push notifications | ntfy.sh — topic: `gk12-pipeline` | `scripts/notify.py` | none (public topic) | 2026-05-14 |
| 11 | Google Cloud | gcloud CLI — project: `genesis-aios` | `gcloud` at `%LOCALAPPDATA%\Google\Cloud SDK\...` | `gcloud auth login` | 2026-05-14 |
| 12 | Status reports | Pipeline + calendar status to ntfy | `scripts/status_report.py` | inherits gws + ntfy | 2026-05-14 |

**Mechanism options:** `mcp` (MCP server), `script` (Python/Bash hitting an API), `export` (CSV/JSON dump), `key+ref` (`.env` key + `references/{tool}-api.md`), `not yet connected`.

## ntfy Phone Setup (one-time)
1. Install **ntfy** app on iPhone — App Store, free
2. Open ntfy → tap **+** → Subscribe to topic: `gk12-pipeline`
3. Enable notifications for the app
4. Test: `python scripts/notify.py "test from AIOS"`

## Calendar Access
```bash
# Upcoming 7 days
gws calendar events list --params '{"calendarId":"primary","maxResults":10,"orderBy":"startTime","singleEvents":true,"timeMin":"<ISO_NOW>","timeMax":"<ISO_7_DAYS>"}'
```
See `scripts/status_report.py` for formatted calendar + pipeline combined report.
