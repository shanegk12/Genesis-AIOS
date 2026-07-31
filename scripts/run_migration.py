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
def _get_platform_key() -> str:
    """Load platform API key from env or .env - never hardcode in source."""
    import os as _os
    from pathlib import Path as _Path
    k = (_os.environ.get('PIPELINE_KEY')
         or _os.environ.get('PLATFORM_KEY')
         or _os.environ.get('ADMIN_API_KEY', ''))
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=', 'ADMIN_API_KEY=')):
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


ADMIN_API_KEY = _get_platform_key()


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
