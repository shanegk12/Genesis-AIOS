"""
Genesis K-12 Gmail Notifier

Sends pipeline status emails to shane@gk12academy.com via Gmail API.
Uses a stored OAuth refresh token — no browser flow needed at runtime.

Usage:
  python notify.py "message"          # run summary
  python notify.py --morning          # morning briefing (start of run)
  python notify.py --failure "text"   # crash report
"""

import base64, email.mime.multipart, email.mime.text
import json, os, sys, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

TO_EMAIL   = "shane@gk12academy.com"
FROM_EMAIL = "shane@gk12academy.com"

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")


# ── Auth ─────────────────────────────────────────────────────────────────────

def _load_env():
    env = {}
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def _load_oauth_credentials():
    env = _load_env()
    client_id     = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")     or env.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or env.get("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")        or env.get("GMAIL_REFRESH_TOKEN")
    # Local fallback: read refresh token from ADC file
    if not refresh_token:
        adc = os.path.join(os.environ.get("APPDATA", ""), "gcloud", "application_default_credentials.json")
        if os.path.exists(adc):
            with open(adc) as f:
                data = json.load(f)
            refresh_token = data.get("refresh_token")
    return client_id, client_secret, refresh_token


def _get_access_token(client_id, client_secret, refresh_token):
    data = urllib.parse.urlencode({
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


# ── Manifest stats ────────────────────────────────────────────────────────────

def _load_stats():
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        lessons = data["lessons"]
        total   = len(lessons)
        done    = sum(1 for l in lessons if l["status"] == "done")
        pending = sum(1 for l in lessons if l["status"] == "pending")
        failed  = sum(1 for l in lessons if l["status"] == "failed")
        passed  = sum(1 for l in lessons if l.get("qc_status") == "passed")
        flagged = [l for l in lessons if l.get("qc_status") == "flagged"]
        return dict(total=total, done=done, pending=pending, failed=failed,
                    passed=passed, flagged=flagged, lessons=lessons)
    except Exception:
        return None


# ── HTML builder ──────────────────────────────────────────────────────────────

_CSS = """
body{font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:20px}
.card{background:#fff;border-radius:8px;padding:24px;max-width:600px;margin:0 auto;box-shadow:0 2px 6px rgba(0,0,0,.1)}
h2{color:#1a3c5e;margin-top:0}
.stat{display:inline-block;text-align:center;margin:8px 16px 8px 0}
.stat .num{font-size:2em;font-weight:bold;color:#1a3c5e}
.stat .lbl{font-size:.8em;color:#666;text-transform:uppercase}
.bar-wrap{background:#e0e0e0;border-radius:4px;height:12px;margin:12px 0}
.bar{background:#2e7d32;height:12px;border-radius:4px}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:.9em}
th{background:#1a3c5e;color:#fff;padding:6px 10px;text-align:left}
td{padding:6px 10px;border-bottom:1px solid #eee}
.footer{font-size:.75em;color:#999;margin-top:16px;text-align:center}
.crash{background:#fff3e0;border-left:4px solid #e65100;padding:12px;border-radius:4px;margin-top:12px}
pre{font-size:.8em;white-space:pre-wrap;word-break:break-all}
"""


def _progress_bar(done, total):
    pct = int(done / total * 100) if total else 0
    return (f'<div class="bar-wrap"><div class="bar" style="width:{pct}%"></div></div>'
            f'<p style="font-size:.85em;color:#666">{done}/{total} lessons complete ({pct}%)</p>')


def _stats_block(stats):
    bar = _progress_bar(stats["done"], stats["total"])
    return f"""
    <div>
      <span class="stat"><div class="num">{stats['done']}</div><div class="lbl">Done</div></span>
      <span class="stat"><div class="num">{stats['pending']}</div><div class="lbl">Pending</div></span>
      <span class="stat"><div class="num">{stats['passed']}</div><div class="lbl">QC Passed</div></span>
      <span class="stat"><div class="num">{len(stats['flagged'])}</div><div class="lbl">Flagged</div></span>
    </div>
    {bar}"""


def _flagged_table(flagged):
    if not flagged:
        return ""
    rows = "".join(f"<tr><td>{l['id']}</td><td>{l['tab']}</td><td>{l.get('qc_score','?')}</td></tr>"
                   for l in flagged)
    return (f"<p><strong>QC-Flagged Lessons:</strong></p>"
            f"<table><tr><th>ID</th><th>Lesson</th><th>Score</th></tr>{rows}</table>")


def _build_html(headline, body_html, stats=None):
    stats_html   = _stats_block(stats) if stats else ""
    flagged_html = _flagged_table(stats["flagged"]) if stats else ""
    now = datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    return f"""<!DOCTYPE html><html><head><style>{_CSS}</style></head><body>
<div class="card">
  <h2>Genesis K-12 — {headline}</h2>
  {stats_html}
  {body_html}
  {flagged_html}
  <div class="footer">Sent {now} · Genesis K-12 Pipeline</div>
</div></body></html>"""


# ── Send ─────────────────────────────────────────────────────────────────────

def send_email(subject, html):
    client_id, client_secret, refresh_token = _load_oauth_credentials()
    if not all([client_id, client_secret, refresh_token]):
        print("Notify: missing OAuth credentials — skipping email")
        return
    try:
        access_token = _get_access_token(client_id, client_secret, refresh_token)
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["To"]      = TO_EMAIL
        msg["From"]    = FROM_EMAIL
        msg.attach(email.mime.text.MIMEText(html, "html"))
        raw     = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = json.dumps({"raw": raw}).encode()
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=payload,
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Notify: email failed — {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def notify(summary_line: str):
    stats = _load_stats()
    html  = _build_html(
        headline = "Pipeline Run Complete",
        body_html= f"<p>{summary_line}</p>",
        stats    = stats,
    )
    send_email(f"GK12 Pipeline — {summary_line}", html)


def notify_morning(pending_count: int, batch_size: int):
    stats = _load_stats()
    html  = _build_html(
        headline = "Morning Briefing",
        body_html= (f"<p>Pipeline starting now. Processing up to <strong>{batch_size}</strong> of "
                    f"<strong>{pending_count}</strong> pending lessons.</p>"),
        stats    = stats,
    )
    send_email("GK12 Morning Briefing — Pipeline Starting", html)


def notify_failure(error_text: str):
    stats = _load_stats()
    body  = f'<div class="crash"><strong>Pipeline crashed:</strong><pre>{error_text[:3000]}</pre></div>'
    html  = _build_html(
        headline = "Pipeline Crashed",
        body_html= body,
        stats    = stats,
    )
    send_email("GK12 Pipeline FAILED — Action Required", html)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--morning" in args:
        stats = _load_stats()
        pending = stats["pending"] if stats else 0
        notify_morning(pending, 20)
    elif "--failure" in args:
        idx = args.index("--failure")
        msg = args[idx + 1] if idx + 1 < len(args) else "Unknown error"
        notify_failure(msg)
    else:
        msg = " ".join(args) if args else "Pipeline complete."
        notify(msg)
