"""
build_interactive_library.py

Triggers the platform's interactive-library backfill. Scans every lesson,
deduplicates identical embed/code-embed interactives into one
`interactiveLibrary` Firestore doc each, and links every lesson block to its
entry via `data.libraryId`. Idempotent — safe to re-run.

The heavy lifting runs server-side in /api/admin/interactives/library (action:
"backfill") with the Admin SDK; this script just calls it and prints the report.

Usage:
  python scripts/build_interactive_library.py --dry-run
  python scripts/build_interactive_library.py --save
  python scripts/build_interactive_library.py --save --url https://genesis-lms-staging--genesis-modularity.us-central1.hosted.app
"""

import argparse, json, os, sys, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Default to staging — validate there first, then re-run against prod (per deploy workflow).
DEFAULT_URL = "https://genesis-lms-staging--genesis-modularity.us-central1.hosted.app"
PROD_URL    = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"


def _get_platform_key() -> str:
    k = os.environ.get("PIPELINE_KEY") or os.environ.get("PLATFORM_KEY") or os.environ.get("ADMIN_API_KEY", "")
    if k:
        return k
    for name in [".env", ".env.local"]:
        p = Path(__file__).parent.parent / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(("PIPELINE_KEY=", "PLATFORM_KEY=", "ADMIN_API_KEY=")) and "=" in line:
                    return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def call_backfill(base_url: str, key: str, dry_run: bool) -> dict | None:
    payload = json.dumps({"action": "backfill", "dryRun": dry_run}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/admin/interactives/library", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--url",     default=DEFAULT_URL, help="Platform base URL (default: staging)")
    parser.add_argument("--prod",    action="store_true", help="Shortcut for the prod URL")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    base_url = PROD_URL if args.prod else args.url
    key = _get_platform_key()
    if not key:
        print("ADMIN_API_KEY / PIPELINE_KEY not found in env or .env"); sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"\nInteractive Library Backfill [{mode}] → {base_url}")
    print("=" * 70)

    result = call_backfill(base_url, key, dry_run=args.dry_run)
    if not result or not result.get("ok"):
        print("FAILED:", result); sys.exit(1)

    r = result["report"]
    print(f"Lessons scanned:        {r['lessons']}")
    print(f"Total interactives:     {r['totalInteractives']}")
    print(f"Distinct library entries: {r['distinctEntries']}")
    print(f"Redundant (used >1x):   {r['redundant']}")
    if not args.dry_run:
        print(f"Blocks linked:          {r.get('linked')}")
        print(f"Lessons touched:        {r.get('lessonsTouched')}")
    print("\nMost-reused interactives:")
    for g in r["groups"][:15]:
        if g["usageCount"] > 1:
            print(f"  [{g['usageCount']:>3}x] {g['name'][:50]:<50} ({g['type']})  e.g. {', '.join(g['lessons'][:5])}")
    print("=" * 70)
    print("Done." if not args.dry_run else "Dry run only — re-run with --save to write.")


if __name__ == "__main__":
    main()
