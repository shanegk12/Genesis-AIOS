"""
slack.py — minimal two-way Slack for the AIOS (Genesis AIOS bot, #aios).

Uses the Slack Web API directly (no MCP, no deps) with SLACK_BOT_TOKEN from .env.
The AIOS calls this via Bash to read + post in Slack.

Usage:
  python scripts/slack.py whoami
  python scripts/slack.py read [#channel] [limit]        # recent messages (default #aios, 15)
  python scripts/slack.py post "<text>" [#channel]        # post a message (default #aios)
  python scripts/slack.py reply <thread_ts> "<text>" [#channel]   # reply in a thread
"""

import json, os, sys, urllib.request, urllib.parse, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_CHANNEL = "#aios"


def _token() -> str:
    if os.environ.get("SLACK_BOT_TOKEN"):
        return os.environ["SLACK_BOT_TOKEN"]
    env = Path(__file__).parent.parent / ".env"
    if env.exists():
        for ln in env.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("SLACK_BOT_TOKEN="):
                return ln.split("=", 1)[1].strip().strip("\"'")
    print("SLACK_BOT_TOKEN not found in env or .env"); sys.exit(1)


def call(method: str, params: dict, post: bool = False) -> dict:
    tok = _token()
    url = f"https://slack.com/api/{method}"
    headers = {"Authorization": f"Bearer {tok}"}
    if post:
        data = json.dumps(params).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    else:
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"); sys.exit(1)
    if not out.get("ok"):
        print(f"Slack error: {out.get('error')}"); sys.exit(1)
    return out


def _resolve(channel: str) -> str:
    """Slack history needs a channel ID. Resolve '#name' -> Cxxxx; pass IDs through."""
    if not channel.startswith("#"):
        return channel
    name = channel[1:]
    cursor = ""
    while True:
        params = {"types": "public_channel,private_channel", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        out = call("conversations.list", params)
        for c in out.get("channels", []):
            if c.get("name") == name:
                return c["id"]
        cursor = out.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break
    print(f"channel {channel} not found (is the bot invited to it?)"); sys.exit(1)


def _user_names(ids):
    names = {}
    for uid in set(filter(None, ids)):
        try:
            u = call("users.info", {"user": uid})
            p = u["user"]
            names[uid] = p.get("profile", {}).get("display_name") or p.get("real_name") or uid
        except SystemExit:
            names[uid] = uid
    return names


def cmd_whoami():
    a = call("auth.test", {})
    print(f"Bot @{a['user']} in workspace {a['team']} ({a['team_id']})  url={a['url']}")


def cmd_read(channel=DEFAULT_CHANNEL, limit=15):
    cid = _resolve(channel)
    msgs = call("conversations.history", {"channel": cid, "limit": int(limit)}).get("messages", [])
    msgs = list(reversed(msgs))  # oldest -> newest
    names = _user_names([m.get("user") for m in msgs])
    print(f"--- last {len(msgs)} in {channel} (ts = message id for replies) ---")
    for m in msgs:
        who = m.get("username") or names.get(m.get("user", ""), m.get("bot_id", "?"))
        text = (m.get("text") or "").replace("\n", " ")
        print(f"[{m.get('ts')}] {who}: {text}")


def cmd_post(text, channel=DEFAULT_CHANNEL):
    r = call("chat.postMessage", {"channel": channel, "text": text}, post=True)
    print(f"posted to {channel} (ts={r['ts']})")


def cmd_reply(thread_ts, text, channel=DEFAULT_CHANNEL):
    r = call("chat.postMessage", {"channel": channel, "text": text, "thread_ts": thread_ts}, post=True)
    print(f"replied in {channel} thread {thread_ts} (ts={r['ts']})")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    cmd = a[0]
    if cmd == "whoami":
        cmd_whoami()
    elif cmd == "read":
        ch = a[1] if len(a) > 1 else DEFAULT_CHANNEL
        lim = a[2] if len(a) > 2 else 15
        cmd_read(ch, lim)
    elif cmd == "post":
        if len(a) < 2: print('usage: post "<text>" [#channel]'); sys.exit(1)
        cmd_post(a[1], a[2] if len(a) > 2 else DEFAULT_CHANNEL)
    elif cmd == "reply":
        if len(a) < 3: print('usage: reply <thread_ts> "<text>" [#channel]'); sys.exit(1)
        cmd_reply(a[1], a[2], a[3] if len(a) > 3 else DEFAULT_CHANNEL)
    else:
        print(f"unknown command: {cmd}\n{__doc__}"); sys.exit(1)


if __name__ == "__main__":
    main()
