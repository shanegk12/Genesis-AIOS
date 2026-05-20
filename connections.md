# Connections

Registry of every system your AIOS can reach. Filled by `/onboard` from Q4-Q7 answers; expanded over time as you wire new tools. `/audit` checks this file for domain coverage and freshness.

| # | Domain | Tool | Mechanism | Auth | Last checked |
|---|---|---|---|---|---|
| 1 | Revenue / Financials | QuickBooks (planned) + business bank account | not yet connected | — | — |
| 2 | Course platform | LearnWorlds (Pro Trainer) | not yet connected via API (API requires Learning Center plan) | — | 2026-05-16 |
| 3 | Calendar | Google Calendar | MCP (claude_ai_Google_Calendar) + ADC | ADC via oauth-client.json | 2026-05-16 |
| 4 | Email | Gmail | MCP (claude_ai_Gmail) + ADC | ADC via oauth-client.json | 2026-05-16 |
| 5 | Project / task tracking | None yet | not yet connected | — | — |
| 6 | Meeting intelligence | None yet | not yet connected | — | — |
| 7 | Knowledge / files | Google Drive | google-api-python-client (scripts/image_agent.py) | ADC via oauth-client.json | 2026-05-16 |
| 8 | Lesson drafting | Gemini 2.5 Flash | scripts/lesson_agent.py → generativelanguage API | GEMINI_API_KEY in Secret Manager | 2026-05-16 |
| 9 | Image generation | gemini-2.5-flash-image | scripts/image_agent.py → generativelanguage API | GEMINI_API_KEY in Secret Manager | 2026-05-16 |
| 10 | Assessment generation | Gemini 2.5 Flash | scripts/assessment_agent.py → generativelanguage API | GEMINI_API_KEY in Secret Manager | 2026-05-16 |
| 11 | Interactive generation | Claude claude-opus-4-7 | scripts/interactive_agent.py → Anthropic API | ANTHROPIC_API_KEY in Secret Manager | 2026-05-16 |
| 12 | Push notifications | Gmail | scripts/notify_gmail.py | GMAIL_REFRESH_TOKEN in Secret Manager | 2026-05-16 |
| 13 | Pipeline runner | Google Cloud Run | Cloud Run job: gk12-pipeline (project: genesis-aios) | ADC / service account | 2026-05-16 |
| 14 | Secrets | Google Secret Manager | python-google-cloud-secretmanager | ADC | 2026-05-16 |
| 15 | Source control | GitHub | git push via Cloud Run | GITHUB_TOKEN in Secret Manager | 2026-05-16 |
| 16 | Google Docs (curriculum) | Google Docs API | google-api-python-client | ADC via oauth-client.json | 2026-05-16 |

## ADC Auth (go-forward standard)

All Google API calls use Application Default Credentials via a custom Desktop OAuth client:

```bash
# Re-auth when needed (gcloud --scopes is broken on GK12 domain):
python scripts/reauth_adc.py
# Credentials file: D:\AIOS\oauth-client.json
# ADC stored at: %APPDATA%\gcloud\application_default_credentials.json
```

## Cloud Run Pipeline

- **Job:** `gk12-pipeline` in project `genesis-aios`, region `us-central1`
- **Schedule:** 8:00am daily briefing email; 8:05am nightly batch (20 lessons, all agents including interactives + assessments + SCORM)
- **Entrypoint:** `entrypoint.sh` → `pm_agent.py --course both --batch 20 --type all --generate-images --generate-interactives --generate-assessments --generate-scorm`
- **Manifest:** auto-pushed to GitHub after each run

## LearnWorlds Notes

- Plan: Pro Trainer ($99/mo) — no API, no bulk SCORM import, 20-SCORM cap
- API requires Learning Center ($249/mo annual) — pending Ethan approval (agenda: Wednesday 2026-05-20 Weekly Update)
- Manual import is the fallback until plan decision made
