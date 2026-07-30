#!/usr/bin/env python3
"""
AIOS cadence and discipline hooks.

Four modes, wired in .claude/settings.json:

  --mode sessionstart : surface AIOS drift at the top of a session (days since
                        last audit, missing daily plan, stale decisions log,
                        aging memory).

  --mode prompt       : on UserPromptSubmit, detect build intent ("we should
                        build this") and nudge toward /proveit BEFORE the work,
                        not a justification after it.

  --mode wrote        : on PostToolUse for Write|Edit, tally files touched this
                        session. Cheap; no output.

  --mode stop         : once past LONG_SESSION_HOURS, remind to run
                        /session-handoff. Separately, if files were written and
                        nothing was verified, nudge toward /verify. Each fires
                        at most once per session.

Why: the 2026-07-30 audits found no hooks anywhere, and the same session produced
two live examples of the gap - seven files edited before any model call was
tested, and a claim reported settled off a probe of the wrong layer.

Pure stdlib. No network. Fails silent: a hook must never break a session.
"""

from __future__ import annotations

import argparse
import json
import re
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
VERIFY_NUDGE_AFTER_WRITES = 3

# Explicit build intent only. Questions ("how would we build X?") and reports
# ("I built X") must not match - a nudge that fires on everything gets ignored.
BUILD_INTENT = re.compile(
    r"\b("
    r"(we|you|i|let'?s)\s+(should|could|need to|want to|ought to|will)\s+"
    r"(build|make|create|add|write|set ?up|implement|automate|wire up)"
    r"|let'?s\s+(build|make|create|add|implement|automate|wire up)"
    r"|(can|should)\s+(we|you)\s+(build|make|create|add|implement|automate)"
    r"|(build|create|set ?up)\s+(a|an|the)\s+\w+\s+(system|pipeline|agent|script|tool|hook|workflow)"
    r")\b",
    re.IGNORECASE,
)


def _state_path(sid: str) -> Path:
    return Path(tempfile.gettempdir()) / f"aios-session-{sid}.json"


def _load_state(sid: str) -> dict:
    p = _state_path(sid)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {"start": time.time(), "writes": 0,
            "reminded_handoff": False, "reminded_verify": False}


def _save_state(sid: str, state: dict) -> None:
    try:
        _state_path(sid).write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _days_since(ts: float) -> int:
    return int((time.time() - ts) / 86400)


def _newest(globbed):
    files = [p for p in globbed if p.is_file()]
    if not files:
        return None
    n = max(files, key=lambda p: p.stat().st_mtime)
    return n.name, _days_since(n.stat().st_mtime)


def check_drift() -> list[str]:
    out: list[str] = []

    audits = ROOT / "audits"
    newest = _newest(audits.glob("*.md")) if audits.is_dir() else None
    if newest is None:
        out.append("No audit has ever run. `/os-audit` checks whether the setup is still true; `/audit` scores how it is built.")
    elif newest[1] > AUDIT_STALE_DAYS:
        out.append(f"Last audit was {newest[1]} days ago ({newest[0]}). Consider `/os-audit`.")

    plans = ROOT / "context" / "shane" / "daily-plans"
    if plans.is_dir():
        today = date.today().isoformat()
        if not (plans / f"{today}.md").exists():
            latest = _newest(plans.glob("*.md"))
            tail = f" Most recent is {latest[0]} ({latest[1]}d ago)." if latest else ""
            out.append(f"No daily plan for {today}.{tail} Template: `templates/daily-plan.md`.")

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
                out.append(f"Newest decision logged {age} days ago ({newest_entry}). Decisions since then are unrecorded.")

    slug = str(ROOT).replace(":", "-").replace("\\", "-").replace("/", "-").lstrip("-")
    mem = Path.home() / ".claude" / "projects" / slug / "memory"
    if mem.is_dir():
        files = [p for p in mem.glob("*.md") if p.name != "MEMORY.md"]
        stale = [p for p in files if _days_since(p.stat().st_mtime) > MEMORY_STALE_DAYS]
        if files and len(stale) > len(files) // 2:
            out.append(f"{len(stale)} of {len(files)} memory files are over {MEMORY_STALE_DAYS} days old. Verify before trusting.")

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
                body + "\n\nSurface these only if relevant to what Shane asks for. "
                "Do not open the session by reciting this list."
            ),
        },
    }


def mode_prompt(payload: dict) -> dict:
    text = str(payload.get("prompt") or "")
    if not text or not BUILD_INTENT.search(text):
        return {"suppressOutput": True}
    return {
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (
                "Build intent detected in Shane's message. Before building, run the /proveit "
                "discipline:\n"
                "- State the concept as one claim that could turn out false.\n"
                "- Name the load-bearing assumption, the one that changes everything if wrong.\n"
                "- Prove it with the cheapest probe, or give the rebuttal and say how a different "
                "approach would work better.\n"
                "- Then ask whether to keep going.\n"
                "This is a quick reply, not /roast. No council, no subagents. Proof first, build "
                "second, rather than a build followed by an explanation of why it works. If the "
                "task is genuinely trivial, skip it and say so in one line."
            ),
        },
    }


def mode_wrote(payload: dict) -> dict:
    sid = str(payload.get("session_id") or "unknown")
    state = _load_state(sid)
    state["writes"] = int(state.get("writes", 0)) + 1
    _save_state(sid, state)
    return {"suppressOutput": True}


def mode_stop(payload: dict) -> dict:
    sid = str(payload.get("session_id") or "unknown")
    if not _state_path(sid).exists():
        _save_state(sid, {"start": time.time(), "writes": 0,
                          "reminded_handoff": False, "reminded_verify": False})
        return {"suppressOutput": True}

    state = _load_state(sid)
    msgs: list[str] = []

    writes = int(state.get("writes", 0))
    if writes >= VERIFY_NUDGE_AFTER_WRITES and not state.get("reminded_verify"):
        state["reminded_verify"] = True
        msgs.append(
            f"{writes} files written this session. Has any of it been verified at the layer of "
            "the claim, not the layer below it? /verify checks that the thing works, then tries "
            "to break it. \"It compiled\" and \"no errors\" are not verification."
        )

    hours = (time.time() - float(state.get("start", time.time()))) / 3600
    if hours >= LONG_SESSION_HOURS and not state.get("reminded_handoff"):
        state["reminded_handoff"] = True
        msgs.append(
            f"This session has run {hours:.1f} hours. Context degrades well before the window "
            "fills. Run /session-handoff, then /clear, and paste the handoff into a fresh session."
        )

    _save_state(sid, state)
    return {"systemMessage": "  ".join(msgs)} if msgs else {"suppressOutput": True}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sessionstart", "prompt", "wrote", "stop"], required=True)
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
        result = {
            "sessionstart": lambda: mode_sessionstart(),
            "prompt": lambda: mode_prompt(payload),
            "wrote": lambda: mode_wrote(payload),
            "stop": lambda: mode_stop(payload),
        }[args.mode]()
    except Exception:
        result = {"suppressOutput": True}

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
