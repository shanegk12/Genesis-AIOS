"""
Merge Mousetrap course into Creationeering course.

Calls POST /api/admin/merge-courses on the live platform.

Usage:
  python scripts/merge_courses.py --dry-run    # preview changes, no writes
  python scripts/merge_courses.py --run        # execute migration

The migration is idempotent — units already moved are skipped.
Run --dry-run first and verify the log before --run.
"""

import argparse, json, os, sys, urllib.request, urllib.error

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL     = os.environ.get("MERGE_URL", "http://localhost:3001")
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


PLATFORM_KEY = _get_platform_key()


def call_merge(dry_run: bool) -> dict:
    payload = json.dumps({"dryRun": dry_run}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/merge-courses",
        data=payload,
        headers={
            "Authorization": f"Bearer {PLATFORM_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code}: {body[:500]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview only — no Firestore writes")
    group.add_argument("--run",     action="store_true", help="Execute the migration")
    args = parser.parse_args()

    dry_run = args.dry_run
    mode = "DRY RUN" if dry_run else "LIVE"

    print(f"\nMerge Courses [{mode}]")
    print("=" * 60)

    if not dry_run:
        confirm = input("This will modify Firestore. Type 'yes' to continue: ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            sys.exit(0)

    result = call_merge(dry_run=dry_run)

    if not result.get("ok"):
        print(f"\nERROR: {result.get('error', 'unknown')}")
        sys.exit(1)

    # Print the log
    for line in result.get("log", []):
        print(line)

    print("\n" + "=" * 60)
    print(f"Units re-parented : {result.get('unitsReParented', 0)}")
    print(f"Lessons updated   : {result.get('lessonsUpdated', 0)}")
    print(f"Dry run           : {result.get('dryRun')}")

    if dry_run:
        print("\nRun with --run to apply these changes.")


if __name__ == "__main__":
    main()
