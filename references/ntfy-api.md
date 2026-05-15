# ntfy.sh API Reference

Source: https://docs.ntfy.sh/publish/ and https://docs.ntfy.sh/subscribe/api/
Logged: 2026-05-15

## Auth

```python
req.add_header("Authorization", "Bearer <token>")
```

Token stored in `.env` as `NTFY_TOKEN`. Topic: `gk12-pipeline`.

---

## Publishing — Key Headers

| Header | Aliases | Values |
|---|---|---|
| Title | `X-Title`, `ti`, `t` | Any string |
| Priority | `X-Priority`, `prio`, `p` | 1 (min) / 2 (low) / 3 (default) / 4 (high) / 5 (max/urgent) |
| Tags | `X-Tags`, `tag`, `ta` | Comma-separated emoji short codes or labels |
| Click | `X-Click` | URL to open on tap (http, mailto, geo, ntfy://) |
| Icon | `X-Icon` | Image URL (JPEG/PNG, cached 24h) |
| Attach | `X-Attach` | External file URL to attach |
| Delay | `X-Delay`, `At`, `In` | Unix ts / duration (`30m`, `3h`) / natural language (`tomorrow, 10am`) |
| Markdown | `X-Markdown` | `yes` — enables markdown rendering (web app only) |
| Actions | `X-Actions` | Up to 3 buttons (see below) |

### Priority Reference

- **5 max** — Extended vibration, pop-over (use for urgent alerts)
- **4 high** — Long vibration, pop-over
- **3 default** — Standard notification
- **2 low** — Silent, shows in drawer
- **1 min** — Silent, below fold

### Common Emoji Tags

`warning`, `tada`, `books`, `rocket`, `bar_chart`, `sun`, `white_check_mark`, `rotating_light`, `x`

---

## Action Buttons (up to 3)

```
X-Actions: view, Open Doc, https://docs.google.com/...
X-Actions: http, Retry Pipeline, https://..., method=POST; view, Status, https://...
```

Types: `view` (open URL), `http` (make HTTP request), `copy` (copy to clipboard), `broadcast` (Android intent)

---

## Scheduling / Delay

```python
req.add_header("X-Delay", "tomorrow, 8am")
req.add_header("X-Delay", "30m")
req.add_header("X-Delay", "1639194738")  # unix timestamp
```

- Min delay: 10 seconds. Max: 3 days.
- Cancel a scheduled message: DELETE to `/<topic>/<sequence_id>`

---

## Markdown Messages

```python
req.add_header("Content-Type", "text/markdown")
# or
req.add_header("X-Markdown", "yes")
```

Supports bold, links, code blocks, lists, headings. Web app only (not mobile push).

---

## Publish as JSON (alternative to headers)

```python
import json, urllib.request

payload = json.dumps({
    "topic": "gk12-pipeline",
    "title": "GK12 Alert",
    "message": "Pipeline failed on C-037",
    "priority": 4,
    "tags": ["warning"],
    "actions": [{"action": "view", "label": "Open Doc", "url": "https://docs.google.com/..."}]
}).encode("utf-8")

req = urllib.request.Request("https://ntfy.sh/", data=payload,
      headers={"Content-Type": "application/json",
               "Authorization": "Bearer <token>"})
```

---

## Subscribing / Polling

```
GET https://ntfy.sh/gk12-pipeline/json           # streaming (keep-alive)
GET https://ntfy.sh/gk12-pipeline/json?poll=1    # one-shot poll, returns cached + closes
GET https://ntfy.sh/gk12-pipeline/json?since=10m # messages from last 10 minutes
GET https://ntfy.sh/gk12-pipeline/json?since=all # full cache
```

Filter params: `id`, `message`, `title`, `priority`, `tags`

---

## Limits

- Max message size: 4,096 bytes (larger → auto attachment)
- Max attachment: 15 MB per file, 100 MB total per visitor
- Attachment expiry: 3 hours
- Scheduled message cache: 12 hours post-delivery

---

## Ideas for AIOS use

- **Action buttons on pipeline failures** — "Retry" button that hits a webhook, or "View Doc" linking to the lesson
- **Scheduled reminders** — use `X-Delay` to send a nudge at a specific time (e.g., pre-camp checklist reminder May 19)
- **Priority escalation** — failed lessons get priority 4 (high), normal completion stays at 3
- **Markdown briefings** — richer morning report formatting in the web app
