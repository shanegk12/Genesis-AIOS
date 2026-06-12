"""
bez_socket.py — 24/7 Bez over Slack Socket Mode (real-time, no polling).

Slack pushes message events to us over a WebSocket (no public URL, no
conversations.history rate limits). Reuses the agent + guardrails from
bez_agent.py — only the "how it hears you" layer changes.

Env (.env): SLACK_BOT_TOKEN (xoxb), SLACK_APP_TOKEN (xapp), ANTHROPIC_API_KEY.
Run:  python scripts/bez_socket.py
"""

import logging, re, threading
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import bez_agent as bez

APP_TOKEN = bez._env("SLACK_APP_TOKEN")
if not APP_TOKEN or not bez.SLACK_TOKEN:
    raise SystemExit("Missing SLACK_APP_TOKEN or SLACK_BOT_TOKEN in .env")

app = App(token=bez.SLACK_TOKEN, signing_secret="not-used-in-socket-mode")
BOT_ID = bez.slack("auth.test", {}).get("user_id")
_seen = set()


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
    if text.upper() == "BEZ STOP":
        bez.post(ch, "🛑 Stopped.", ts)
        return
    print(f"[msg] {event.get('user')}: {text[:120]}", flush=True)
    threading.Thread(target=_run, args=(text, ch, ts), daemon=True).start()


def _run(text, ch, ts):
    try:
        bez.run_agent(text, ch, ts)
    except Exception as e:
        bez.post(ch, f"⚠️ error: {e}", ts)


@app.event("message")
def on_message(event, logger):
    _handle(event)


@app.event("app_mention")
def on_mention(event, logger):
    _handle(event)  # dedup via _seen handles the double-fire with message


if __name__ == "__main__":
    ch = bez.resolve_channel(bez.CHANNEL_NAME)
    print(f"Bez (Socket Mode) connecting · bot {BOT_ID} · channel {bez.CHANNEL_NAME} · model {bez.MODEL} · cwd {bez.CWD}", flush=True)
    bez.post(ch, "🤖 Bez is online 24/7 (real-time Socket Mode) — message me here. Say 'BEZ STOP' to halt a task.")
    SocketModeHandler(app, APP_TOKEN).start()
