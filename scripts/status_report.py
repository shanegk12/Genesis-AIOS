"""
Genesis K-12 Status Report

Sends a combined pipeline progress + Google Calendar snapshot to your phone via ntfy.
Run manually or schedule via Windows Task Scheduler for a daily briefing.

Usage:
  python status_report.py              # send to phone
  python status_report.py --print      # print only, no notification
  python status_report.py --days 3     # show calendar events for next N days (default 7)
"""

import argparse, json, os, shutil, subprocess, sys, tempfile, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
NOTIFY_SCRIPT = os.path.join(os.path.dirname(__file__), "notify.py")

NTFY_TOPIC = "gk12-pipeline"
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"

_BASH = shutil.which("bash") or r"C:\Program Files\Git\usr\bin\bash.exe"


def gws_run_bash(cmd):
    result = subprocess.run([_BASH, "-c", cmd], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    output = "\n".join(l for l in (result.stdout or "").splitlines()
                       if not l.startswith("Using keyring"))
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or output)
    return json.loads(output) if output.strip() else {}


def pipeline_summary(data):
    lines = []
    total_done = total_pending = total_failed = total_flagged = 0

    for doc in ["creationeering", "mousetrap"]:
        lessons = [l for l in data["lessons"] if l["doc"] == doc]
        done    = sum(1 for l in lessons if l["status"] == "done")
        pending = sum(1 for l in lessons if l["status"] == "pending")
        failed  = sum(1 for l in lessons if l["status"] == "failed")
        flagged = sum(1 for l in lessons if l.get("qc_status") == "flagged")
        total   = len(lessons)
        pct     = int(done / total * 100) if total else 0
        label   = "Creationeering" if doc == "creationeering" else "Mousetrap"
        lines.append(f"{label}: {done}/{total} ({pct}%)  fail={failed}  flagged={flagged}")
        total_done    += done
        total_pending += pending
        total_failed  += failed
        total_flagged += flagged

    total = total_done + total_pending + total_failed
    pct   = int(total_done / total * 100) if total else 0
    lines.insert(0, f"PIPELINE: {total_done}/{total} ({pct}%) | pending={total_pending} | fail={total_failed} | qc-flagged={total_flagged}")
    return "\n".join(lines)


def calendar_summary(days=7):
    now     = datetime.now(timezone.utc)
    end     = now + timedelta(days=days)
    time_min = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    time_max = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    tmp        = tempfile.gettempdir()
    params_path = os.path.join(tmp, "cal_params.json")
    with open(params_path, "w") as f:
        json.dump({
            "calendarId":   "primary",
            "maxResults":   8,
            "orderBy":      "startTime",
            "singleEvents": True,
            "timeMin":      time_min,
            "timeMax":      time_max,
        }, f)

    params_unix = params_path.replace("\\", "/")
    cmd = f"gws calendar events list --params \"$(cat '{params_unix}')\""

    try:
        data   = gws_run_bash(cmd)
        events = data.get("items", [])
        if not events:
            return f"CALENDAR: no events in next {days} days"

        lines = [f"CALENDAR (next {days} days):"]
        for ev in events:
            start = ev.get("start", {})
            dt    = start.get("dateTime", start.get("date", ""))
            if "T" in dt:
                # Convert to local-ish display (just show date + time)
                dt_obj = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                label  = dt_obj.strftime("%a %b %d %I:%M%p").lstrip("0")
            else:
                label = dt
            title = ev.get("summary", "(no title)")
            lines.append(f"  {label}: {title}")
        return "\n".join(lines)
    except Exception as e:
        return f"CALENDAR: error fetching events — {e}"


def send_ntfy(message, title="GK12 Daily Status"):
    data = message.encode("utf-8")
    req  = urllib.request.Request(NTFY_URL, data=data, method="POST")
    req.add_header("Title",    title)
    req.add_header("Priority", "default")
    req.add_header("Tags",     "bar_chart")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"Notification sent (HTTP {resp.status})")
    except Exception as e:
        print(f"Notification failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="GK12 Status Report")
    parser.add_argument("--print", action="store_true", dest="print_only",
                        help="Print report without sending to phone")
    parser.add_argument("--days", type=int, default=7,
                        help="Calendar lookahead in days (default 7)")
    args = parser.parse_args()

    if not os.path.exists(MANIFEST_PATH):
        print("No manifest found. Run pm_agent.py first.")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    today  = datetime.now().strftime("%a %b %d")
    report = f"=== GK12 Status — {today} ===\n"
    report += pipeline_summary(data) + "\n\n"
    report += calendar_summary(args.days)

    print(report)

    if not args.print_only:
        send_ntfy(report)


if __name__ == "__main__":
    main()
