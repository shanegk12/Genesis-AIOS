"""
Genesis K-12 Push Notification via ntfy.sh

Setup (one-time):
  1. Install the ntfy app on your phone (iOS/Android)
  2. Subscribe to the topic: gk12-pipeline
  3. ntfy.sh is free — no account needed for basic use

Usage:
  python notify.py "message here"
  python notify.py  (sends a default "Pipeline complete" message)
"""

import sys, urllib.request, urllib.error

NTFY_TOPIC = "gk12-pipeline"
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"


def notify(message: str, title: str = "Genesis K-12 Pipeline"):
    data = message.encode("utf-8")
    req  = urllib.request.Request(NTFY_URL, data=data, method="POST")
    req.add_header("Title",    title)
    req.add_header("Priority", "default")
    req.add_header("Tags",     "books")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"Notification sent (HTTP {resp.status}): {message}")
    except urllib.error.HTTPError as e:
        print(f"Notification failed (HTTP {e.code}): {e.read().decode()}")
    except Exception as e:
        print(f"Notification failed: {e}")


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Pipeline complete."
    notify(msg)
