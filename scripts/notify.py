"""
Genesis K-12 Push Notification via ntfy.sh

Usage:
  python notify.py "message here"
  python notify.py  (sends a default "Pipeline complete" message)
"""

import os, sys, urllib.request, urllib.error

NTFY_TOPIC = "gk12-pipeline"
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"


def load_token():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("NTFY_TOKEN="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("NTFY_TOKEN")


def notify(message: str, title: str = "Genesis K-12 Pipeline"):
    token = load_token()
    data = message.encode("utf-8")
    req  = urllib.request.Request(NTFY_URL, data=data, method="POST")
    req.add_header("Title",    title)
    req.add_header("Priority", "default")
    req.add_header("Tags",     "books")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
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
