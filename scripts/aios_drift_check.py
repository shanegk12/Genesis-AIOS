#!/usr/bin/env python3
"""
AIOS cadence hooks.

Two modes, both driven by Claude Code hooks (see .claude/settings.json):

  --mode sessionstart : surface AIOS drift at the top of a session (days since
                        last audit, missing daily plan, stale decisions log,
                        aging memory). Emits hookSpecificOutput.additionalContext
                        so the facts land in the model's context, not just on
                        screen.

  --mode stop         : after a session has run past LONG_SESSION_HOURS, remind
                        once to run /session-handoff before clearing. Fires at
                        most one time per session id.

Why this exists: the 2026-07-30 os-audit found no hooks and no scheduled tasks
anywhere in this AIOS. Every recurring process was manual, which is why the
daily-plan habit lapsed and the previous audit sat 76 days stale.

Pure stdlib. No network. Must stay fast - SessionStart blocks the session.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AUDIT_STALE_DAYS = 30
DECISIONS_STALE_DAYS = 14
MEMORY_STALE_DAYS = 60
LONG_SESSION_HOURS = 3.0


def _days_since(ts: float) -> int:
    return int((time.time() - ts) / 86400)


def _newest(globbed) -> tuple[str, int] | None:
    files = [p for p in globbed if p.is_file()]
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return newest.name, _days_since(newest.stat().st_mtime)


def check_drift() -> list[str]:
    """Return a list of drift lines. Empty list means nothing to report."""
    out: list[str] = []

    # 1. Audits
    audits = ROOT / "audits"
    newest = _newest(audits.glob("*.md")) if audits.is_dir() else None
    if newest is None:
        out.append("No audit has ever run. `/os-audit` checks whether the setup is still true; `/audit` scores how it is built.")
    elif newest[1] > AUDIT_STALE_DAYS:
        out.append(f"Last audit was {newest[1]} days ago ({newest[0]}). Consider `/os-audit`.")

    # 2. Today's daily plan
    plans = ROOT / "context" / "shane" / "daily-plans"
    if plans.is_dir():
        today = date.today().isoformat()
        if not (plans / f"{today}.md").exists():
            latest = _newest(plans.glob("*.md"))
            tail = f" Most recent is {latest[0]} ({latest[1]}d ago)." if latest else ""
            out.append(f"No daily plan for {today}.{tail}")

    # 3. Decisions log
    log = ROOT / "decisions" / "log.md"
    if log.is_file():
        newest_entry = None
        with log.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("## 20"):
                    try:
                        newest_entry = datetime.strptime(line[3:13], "%Y-%m-%d").date()
                    except ValueError:
                        pass
                    break
        if newest_entry:
            age = (date.today() - newest_entry).days
            if age > DECISIONS_STALE_DAYS:
                out.append(f"Newest decision logged {age} days ago ({newest_entry}). Decisions made since then are unrecorded.")

    # 4. Memory age (per-project, outside the repo)
    slug = str(ROOT).replace(":", "-").replace("\\", "-").replace("/", "-").lstrip("-")
    mem = Path.home() / ".claude" / "projects" / slug / "memory"
    if mem.is_dir():
        files = [p for p in mem.glob("*.md") if p.name != "MEMORY.md"]
        stale = [p for p in files if _days_since(p.stat().st_mtime) > MEMORY_STALE_DAYS]
        if files and len(stale) > len(files) // 2:
            out.append(f"{len(stale)} of {len(files)} memory files are over {MEMORY_STALE_DAYS} days old. Verify before trusting; `/audit` proposes a sweep.")

    return out


def mode_sessionstart() -> dict:
    lines = check_drift()
    if not lines:
        return {"suppressOutput": True}
    body = "AIOS drift check:\n" + "\n".join(f"- {l}" for l in lines)
    return {
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                body + "\n\nSurface these to Shane only if they are relevant to what he asks for. "
                "Do not open the session by reciting this list."
            ),
        },
    }


def mode_stop(payload: dict) -> dict:
    sid = str(payload.get("session_id") or "unknown")
    marker = Path(tempfile.gettempdir()) / f"aios-session-{sid}.json"

    now = time.time()
    if not marker.exists():
        marker.write_text(json.dumps({"start": now, "reminded": False}), encoding="utf-8")
        return {"suppressOutput": True}

    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"suppressOutput": True}

    if state.get("reminded"):
        return {"suppressOutput": True}

    hours = (now - state.get("start", now)) / 3600
    if hours < LONG_SESSION_HOURS:
        return {"suppressOutput": True}

    state["reminded"] = True
    try:
        marker.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return {
        "systemMessage": (
            f"This session has run {hours:.1f} hours. Context degrades well before the window fills. "
            "Run /session-handoff, then /clear, and paste the handoff into a fresh session."
        )
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sessionstart", "stop"], required=True)
    args = ap.parse_args()

    payload = {}
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {}

    try:
        result = mode_sessionstart() if args.mode == "sessionstart" else mode_stop(payload)
    except Exception:
        # A hook must never break a session. Fail silent.
        result = {"suppressOutput": True}

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
