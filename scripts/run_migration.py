"""
Call the platform's server-side migration endpoint.

Usage:
  python scripts/run_migration.py --dry-run          # preview only
  python scripts/run_migration.py                    # live write
  python scripts/run_migration.py --lesson C-001     # single lesson

The endpoint runs inside App Hosting where ADC has Firestore scopes,
so no local service account needed.
"""

import argparse
import json
import urllib.request
import urllib.error

PLATFORM_URL = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
ADMIN_API_KEY = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lesson", default=None)
    args = parser.parse_args()

    payload: dict = {}
    if args.dry_run:
        payload["dryRun"] = True
    if args.lesson:
        payload["lessonId"] = args.lesson

    url = f"{PLATFORM_URL}/api/admin/migrate"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {ADMIN_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    print(f"POST {url}")
    print(f"Body: {json.dumps(payload)}\n")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        return

    print(f"dryRun   : {result.get('dryRun')}")
    print(f"total    : {result.get('total')}")
    print(f"migrated : {result.get('migrated')}")
    print(f"skipped  : {result.get('skipped')}  (already had blocks)")
    print(f"empty    : {result.get('empty')}   (no content to parse)")
    print(f"errors   : {result.get('errors')}")
    print()
    for line in result.get("log", []):
        print(f"  {line}")


if __name__ == "__main__":
    main()
