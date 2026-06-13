"""
bez_socket.py — 24/7 Bez over Slack Socket Mode (real-time, no polling).

Slack pushes message events to us over a WebSocket (no public URL, no
conversations.history rate limits). Reuses the agent + guardrails from
bez_agent.py — only the "how it hears you" layer changes.

Env (.env): SLACK_BOT_TOKEN (xoxb), SLACK_APP_TOKEN (xapp), ANTHROPIC_API_KEY.
Run:  python scripts/bez_socket.py
"""

import logging, os, re, threading
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import bez_agent as bez


def _start_health_server():
    """Cloud Run requires an HTTP listener on $PORT. The socket client isn't one,
    so serve a tiny health endpoint in a thread when PORT is set (cloud)."""
    port = os.environ.get("PORT")
    if not port:
        return
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"bez ok")
        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("0.0.0.0", int(port)), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"health server on :{port}", flush=True)

APP_TOKEN = bez._env("SLACK_APP_TOKEN")
if not APP_TOKEN or not bez.SLACK_TOKEN:
    raise SystemExit("Missing SLACK_APP_TOKEN or SLACK_BOT_TOKEN in .env")

app = App(token=bez.SLACK_TOKEN, signing_secret="not-used-in-socket-mode")
BOT_ID = bez.slack("auth.test", {}).get("user_id")
_seen = set()

ONLINE_MARKER = "Bez is online"


def _recently_announced(channel, within_seconds=600):
    """True if Bez already posted an 'online' message in this channel within the
    window. A crash-loop or rapid redeploy boots repeatedly; without this guard
    each boot floods #aios with 'online' posts (and the noise hides real replies).
    Caps announcements to ~1 per window regardless of restart frequency."""
    import time
    out = bez.slack("conversations.history", {"channel": channel, "limit": 10})
    now = time.time()
    for m in out.get("messages", []):
        if ONLINE_MARKER in (m.get("text") or "") and now - float(m.get("ts", 0)) < within_seconds:
            return True
    return False


def _handle(event):
    if event.get("bot_id") or event.get("subtype"):
        return
    if event.get("user") not in bez.ALLOWED_USERS:
        return
    ts = event.get("ts")
    if not ts or ts in _seen:
        return
    _seen.add(ts)
    text = re.sub(r"<@[A-Z0-9]+>", "", event.get("text") or "").strip()
    if not text:
        return
    ch = event.get("channel")
    thread_root = event.get("thread_ts") or ts  # conversation = one Slack thread
    if text.upper() == "BEZ STOP":
        bez.post(ch, "🛑 Stopped.", thread_root)
        return
    print(f"[msg] {event.get('user')}: {text[:120]}", flush=True)
    threading.Thread(target=_run, args=(text, ch, thread_root), daemon=True).start()


def _run(text, ch, thread_root):
    try:
        bez.run_agent(text, ch, thread_root, thread_key=thread_root)
    except Exception as e:
        bez.post(ch, f"⚠️ error: {e}", thread_root)


@app.event("message")
def on_message(event, logger):
    _handle(event)


@app.event("app_mention")
def on_mention(event, logger):
    _handle(event)  # dedup via _seen handles the double-fire with message


if __name__ == "__main__":
    _start_health_server()
    ch = bez.resolve_channel(bez.CHANNEL_NAME)
    print(f"Bez (Socket Mode) connecting · bot {BOT_ID} · channel {bez.CHANNEL_NAME} · model {bez.MODEL} · cwd {bez.CWD}", flush=True)
    if _recently_announced(ch):
        print("skipping 'online' post (announced recently — likely a restart)", flush=True)
    else:
        bez.post(ch, f"🤖 {ONLINE_MARKER} 24/7 (real-time Socket Mode) — message me here. Say 'BEZ STOP' to halt a task.")
    SocketModeHandler(app, APP_TOKEN).start()
