"""
morning_briefing.py — daily 8 AM (ET) Slack briefing for the Genesis K-12 team.

Replaces the old email "morning briefing" (notify.py --morning), which only ever
fired as a side-effect of the lesson pipeline and went to Shane alone.

Flow (hybrid: deterministic data + Claude voice):
  1. Read open tasks from the platform PM board (Firestore `pm_issues`, project
     genesis-modularity) directly via ADC / service account.
  2. Group by assignee and bucket into overdue / due-this-week / in-progress / queued.
  3. Have Claude write each person's DM in Shane's voice, scoped to their focus:
       Cade  -> QC tasks + updates
       Shane -> full project progress + item list
       Ethan -> his business items
  4. DM each person in Slack (scripts/slack.py cmd_dm — email -> user ID).

Usage:
  python scripts/morning_briefing.py              # dry-run: print, do NOT send
  python scripts/morning_briefing.py --send       # send the DMs (scheduler uses this)
  python scripts/morning_briefing.py --only cade@gk12academy.com [--send]
"""

import os, sys, json
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ID = "genesis-modularity"
COLLECTION = "pm_issues"
BOARD_BASE = "https://gk12academy.com/admin/pm"
MODEL = "claude-haiku-4-5-20251001"
CLOSED = {"done", "canceled"}

# Who gets a briefing, and how it's framed.
RECIPIENTS = [
    {
        "email": "cade@gk12academy.com",
        "name": "Cade",
        "focus": "Cade runs QC. His briefing is about quality-control work: lessons "
                 "and blocks flagged for review or fixing. Keep it task-focused and "
                 "concrete — what to look at today and what's overdue.",
    },
    {
        "email": "shane@gk12academy.com",
        "name": "Shane",
        "focus": "Shane is COO and owns the whole picture. Give him project progress "
                 "(overall task counts) up top, then his own action items. He cares "
                 "most about the August 2026 launch critical path (content).",
    },
    {
        "email": "ethan@gk12academy.com",
        "name": "Ethan",
        "focus": "Ethan handles business items. His briefing is about the operational / "
                 "business tasks assigned to him. If he has nothing on the board yet, "
                 "say so plainly and gently nudge him to add his items.",
    },
]


# ── env ────────────────────────────────────────────────────────────────────────

def _load_env():
    env = {}
    p = Path(__file__).parent.parent / ".env"
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
    return env

_ENV = _load_env()

def _env(key):
    return os.environ.get(key) or _ENV.get(key)


# ── data ─────────────────────────────────────────────────────────────────────

def _today_et() -> date:
    now = datetime.now(ET) if ET else datetime.now()
    return now.date()

def _bucket(issue: dict, today: date) -> str:
    """overdue | this_week | in_progress | queued — for an open issue."""
    due = (issue.get("dueDate") or "").strip()
    due_d = None
    if due:
        try:
            due_d = date.fromisoformat(due[:10])
        except ValueError:
            due_d = None
    if due_d and due_d < today:
        return "overdue"
    if due_d and due_d <= today + timedelta(days=7):
        return "this_week"
    if issue.get("status") == "in_progress":
        return "in_progress"
    return "queued"

def _access_token() -> str:
    """OAuth token for the Firestore REST API. Uses ADC (gcloud locally, the
    service account on Cloud Run). Avoids the Firestore gRPC client, which hangs
    when connecting from off-GCP machines."""
    import google.auth
    import google.auth.transport.requests
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token

def _decode_value(v: dict):
    """Decode one Firestore REST typed value."""
    if "stringValue" in v: return v["stringValue"]
    if "integerValue" in v: return int(v["integerValue"])
    if "doubleValue" in v: return v["doubleValue"]
    if "booleanValue" in v: return v["booleanValue"]
    if "timestampValue" in v: return v["timestampValue"]
    if "nullValue" in v: return None
    if "arrayValue" in v: return [_decode_value(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v: return {k: _decode_value(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None

def load_issues() -> list[dict]:
    """Read all pm_issues docs via the Firestore REST API (paged)."""
    import urllib.request
    token = _access_token()
    base = (f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}"
            f"/databases/(default)/documents/{COLLECTION}")
    out, page_token = [], None
    while True:
        url = base + "?pageSize=300" + (f"&pageToken={page_token}" if page_token else "")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        for doc in data.get("documents", []):
            fields = {k: _decode_value(v) for k, v in doc.get("fields", {}).items()}
            fields["id"] = doc["name"].rsplit("/", 1)[-1]
            out.append(fields)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return out

def slim(issue: dict) -> dict:
    return {
        "title": issue.get("title", "")[:140],
        "status": issue.get("status", ""),
        "priority": issue.get("priority", "none"),
        "dueDate": issue.get("dueDate") or None,
        "source": issue.get("source", "manual"),
        "url": f"{BOARD_BASE}?issue={issue['id']}",
    }

def build_payloads(issues: list[dict]) -> dict:
    today = _today_et()
    open_issues = [i for i in issues if i.get("status") not in CLOSED]

    # Aggregate stats for Shane's project-progress view.
    by_status: dict[str, int] = {}
    for i in open_issues:
        by_status[i.get("status", "?")] = by_status.get(i.get("status", "?"), 0) + 1
    closed_recently = 0
    cutoff = (datetime.now(ET) if ET else datetime.now()) - timedelta(days=7)
    for i in issues:
        ca = (i.get("closedAt") or "")
        if i.get("status") in CLOSED and ca:
            try:
                if datetime.fromisoformat(ca.replace("Z", "+00:00")).date() >= cutoff.date():
                    closed_recently += 1
            except ValueError:
                pass

    payloads = {}
    for r in RECIPIENTS:
        mine = [i for i in open_issues if (i.get("assignee") or "").lower() == r["email"].lower()]
        buckets: dict[str, list] = {"overdue": [], "this_week": [], "in_progress": [], "queued": []}
        for i in mine:
            buckets[_bucket(i, today)].append(slim(i))
        payloads[r["email"]] = {
            "recipient": r,
            "date": today.isoformat(),
            "buckets": buckets,
            "total_open": len(mine),
            "project_stats": {"open_by_status": by_status, "closed_last_7d": closed_recently}
                              if r["focus"].startswith("Shane") else None,
        }
    return payloads


# ── voice (Claude) ─────────────────────────────────────────────────────────────

SYSTEM = (
    "You write a short daily team briefing as a Slack DM, in the voice of Shane "
    "Reynolds, COO of Genesis K-12 Academy (a faith-based homeschool engineering "
    "curriculum company launching August 2026). Voice rules: warm but professional, "
    "short sentences, NO em dashes, bullet points over paragraphs, faith-present but "
    "never forced. Lead with what's overdue or launch-critical. Be specific and brief "
    "— this is a working briefing, not a pep talk. Use Slack markdown: *bold*, and "
    "<url|label> links. Keep it under ~180 words. If there are no tasks, say so in one "
    "or two friendly lines. Do not invent tasks; only use what you're given."
)

def voice_dm(payload: dict) -> str:
    import anthropic
    key = _env("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found")
    client = anthropic.Anthropic(api_key=key)
    r = payload["recipient"]
    user = (
        f"Write {r['name']}'s briefing for {payload['date']}.\n\n"
        f"Context for this person: {r['focus']}\n\n"
        f"Their open tasks, bucketed (each has title, status, priority, dueDate, source, url):\n"
        f"{json.dumps(payload['buckets'], indent=2)}\n\n"
        f"Total open assigned to them: {payload['total_open']}\n"
    )
    if payload.get("project_stats"):
        user += f"\nProject-wide stats (for the progress line): {json.dumps(payload['project_stats'])}\n"
    user += (
        f"\nGreet them by first name ({r['name']}). Link each task with <url|title>. "
        f"Group under bold headers only for buckets that have items "
        f"(Overdue, This week, In progress, Queued)."
    )
    msg = client.messages.create(
        model=MODEL, max_tokens=700,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()


# ── send ─────────────────────────────────────────────────────────────────────

def send_dm(email: str, text: str):
    sys.path.insert(0, str(Path(__file__).parent))
    import slack
    slack.cmd_dm(email, text)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    send = "--send" in args
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = args[i + 1].lower() if i + 1 < len(args) else None

    issues = load_issues()
    payloads = build_payloads(issues)

    for email, payload in payloads.items():
        if only and email.lower() != only:
            continue
        text = voice_dm(payload)
        print(f"\n===== {email} ({payload['total_open']} open) =====\n{text}\n")
        if send:
            try:
                send_dm(email, text)
            except SystemExit:
                print(f"  (slack send failed for {email})")
            except Exception as e:
                print(f"  (slack send error for {email}: {e})")

    if not send:
        print("\n[dry-run] nothing sent. Re-run with --send to deliver.")


if __name__ == "__main__":
    main()
