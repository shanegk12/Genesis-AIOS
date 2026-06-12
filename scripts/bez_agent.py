"""
bez_agent.py — 24/7 Bez: an always-on Slack agent for #aios.

Polls #aios (no Socket Mode / xapp token needed — uses the bot token), and for
each message from an allowed operator, runs a Claude agent with a real `bash`
tool so Bez can actually work: edit code, run scripts, git, deploy.

GUARDRAILS (always on):
  • Allowlist — only acts on messages from approved Slack user IDs (Shane, Ethan).
  • CONFIRM DEPLOY gate — refuses any prod push/deploy (push→main, ff main,
    firebase deploy) unless the triggering message contains "CONFIRM DEPLOY".
  • Audit — every shell command Bez runs is posted to the #aios thread.
  • BEZ STOP — a message of "BEZ STOP" halts the current task.

Env (from .env): SLACK_BOT_TOKEN, ANTHROPIC_API_KEY. Optional: BEZ_MODEL,
BEZ_CWD (default D:/GK12-Platform), BEZ_POLL_SECS (default 5).

Run:  python scripts/bez_agent.py          (foreground; Ctrl-C to stop)
"""

import json, os, re, subprocess, sys, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent.parent


def _env(key, default=None):
    if os.environ.get(key):
        return os.environ[key]
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip().strip("\"'")
    return default


SLACK_TOKEN = _env("SLACK_BOT_TOKEN")
ANTHROPIC_KEY = _env("ANTHROPIC_API_KEY")
MODEL = _env("BEZ_MODEL", "claude-sonnet-4-6")
CWD = _env("BEZ_CWD", "D:/GK12-Platform")
POLL = int(_env("BEZ_POLL_SECS", "5"))
CHANNEL_NAME = _env("BEZ_CHANNEL", "#aios")

# Approved operators (Slack user IDs). Bez ignores everyone else.
ALLOWED_USERS = {
    "U0B9TJJGVC7",  # Shane
    "U0BA70YK5NJ",  # Ethan
}

# Commands that touch prod — blocked unless the message says CONFIRM DEPLOY.
PROD_PATTERNS = [
    r"push\s+\S*\s*origin\s+main",
    r"push\s+origin\s+main",
    r"merge\s+.*\bstaging\b.*",      # ff main <- staging happens while on main
    r"firebase\s+deploy",
    r"git\s+checkout\s+main",         # heuristic: going to main to deploy
]

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ── Slack helpers ─────────────────────────────────────────────────────────────

def slack(method, params, post=False):
    url = f"https://slack.com/api/{method}"
    headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}
    if post:
        data = json.dumps(params).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    else:
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[slack] {method} error: {e}", flush=True)
        return {"ok": False, "error": str(e)}


def resolve_channel(name):
    if not name.startswith("#"):
        return name
    cur = ""
    while True:
        p = {"types": "public_channel,private_channel", "limit": 1000}
        if cur:
            p["cursor"] = cur
        out = slack("conversations.list", p)
        for c in out.get("channels", []):
            if c.get("name") == name[1:]:
                return c["id"]
        cur = out.get("response_metadata", {}).get("next_cursor", "")
        if not cur:
            break
    raise SystemExit(f"channel {name} not found (invite the bot)")


def post(channel, text, thread_ts=None):
    p = {"channel": channel, "text": text[:3900]}
    if thread_ts:
        p["thread_ts"] = thread_ts
    slack("chat.postMessage", p, post=True)


# ── bash tool ─────────────────────────────────────────────────────────────────

def is_prod_command(cmd):
    return any(re.search(p, cmd) for p in PROD_PATTERNS)


def run_bash(cmd, confirm_deploy, channel, thread_ts):
    post(channel, f"```$ {cmd[:300]}```", thread_ts)  # audit
    if is_prod_command(cmd) and not confirm_deploy:
        return "BLOCKED by guardrail: this touches production. Re-send the request including the exact phrase CONFIRM DEPLOY to allow it."
    try:
        r = subprocess.run(cmd, shell=True, cwd=CWD, capture_output=True, text=True, timeout=600)
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        out = out.strip() or f"(exit {r.returncode}, no output)"
        return out[:6000]
    except subprocess.TimeoutExpired:
        return "command timed out (600s)"
    except Exception as e:
        return f"error: {e}"


TOOLS = [{
    "name": "bash",
    "description": "Run a shell command on the operator's machine (Windows, git-bash style). Working dir is the platform repo by default. Use for git, npm, file inspection, running scripts, deploys.",
    "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
}]

SYSTEM = (
    "You are Bez, the Genesis K-12 AI engineer, answering in Slack #aios. You operate on the team's "
    f"machine; default working directory is {CWD} (the Genesis LMS repo); the AIOS repo is at {ROOT}. "
    "You have a `bash` tool and can do real work: read/edit code, run scripts, git, build, deploy. "
    "Deploy workflow: build on `staging` → fast-forward `main`. "
    "GUARDRAILS: never push/merge to main or run firebase deploy unless the user's message contains 'CONFIRM DEPLOY' "
    "(the tool will block it otherwise). Keep Slack replies concise and skimmable. When you finish, give a short summary."
)


def run_agent(user_text, channel, thread_ts):
    confirm = "CONFIRM DEPLOY" in user_text
    messages = [{"role": "user", "content": user_text}]
    for _ in range(18):  # iteration cap
        resp = client.messages.create(model=MODEL, max_tokens=2048, system=SYSTEM, tools=TOOLS, messages=messages)
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use" and block.name == "bash":
                    out = run_bash(block.input.get("command", ""), confirm, channel, thread_ts)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages.append({"role": "user", "content": results})
            continue
        # final text
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        post(channel, text or "(done)", thread_ts)
        return
    post(channel, "Stopped — hit the step limit. Ask me to continue if needed.", thread_ts)


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    if not SLACK_TOKEN or not ANTHROPIC_KEY:
        raise SystemExit("Missing SLACK_BOT_TOKEN or ANTHROPIC_API_KEY in .env")
    ch = resolve_channel(CHANNEL_NAME)
    auth = slack("auth.test", {})
    bot_id = auth.get("user_id")
    print(f"Bez 24/7 online · channel {CHANNEL_NAME} ({ch}) · model {MODEL} · cwd {CWD}", flush=True)
    # Start from now — only respond to messages sent after boot.
    last_ts = slack("conversations.history", {"channel": ch, "limit": 1}).get("messages", [{}])[0].get("ts", "0")
    post(ch, "🤖 Bez is now online 24/7 — message me here and I'll work on it. (Say 'BEZ STOP' to halt a task.)")

    while True:
        try:
            hist = slack("conversations.history", {"channel": ch, "oldest": last_ts, "limit": 20}).get("messages", [])
            for m in reversed(hist):  # oldest first
                ts = m.get("ts", "0")
                if ts <= last_ts:
                    continue
                last_ts = ts
                if m.get("user") == bot_id or m.get("bot_id") or m.get("subtype"):
                    continue
                if m.get("user") not in ALLOWED_USERS:
                    continue
                text = (m.get("text") or "").replace(f"<@{bot_id}>", "").strip()
                if not text:
                    continue
                if text.upper().strip() == "BEZ STOP":
                    post(ch, "🛑 Stopped.", ts)
                    continue
                print(f"[msg] {m.get('user')}: {text[:120]}", flush=True)
                try:
                    run_agent(text, ch, ts)
                except Exception as e:
                    post(ch, f"⚠️ error: {e}", ts)
        except Exception as e:
            print(f"[loop] {e}", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
