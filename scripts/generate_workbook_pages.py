"""
generate_workbook_pages.py

Scrubs every Mousetrap (M-) lesson and AI-generates an engineering workbook page
from the lesson's own content (worksheet instructions, data tables, prompts).
Writes workbookPages/{lessonId} so each lesson has a draft to QC in the admin
"Workbook page" tab. Idempotent (re-running re-drafts).

The extraction + validation runs server-side in /api/admin/workbook/generate.

Usage:
  python scripts/generate_workbook_pages.py --dry-run            # generate, report block counts, DON'T write
  python scripts/generate_workbook_pages.py --save               # generate + write workbookPages
  python scripts/generate_workbook_pages.py --save --lesson M-012
  python scripts/generate_workbook_pages.py --save --prod
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_URL = "https://genesis-lms-staging--genesis-modularity.us-central1.hosted.app"
PROD_URL    = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
MANIFEST    = Path(__file__).parent / "lessons_manifest.json"


def _key() -> str:
    for n in ("PIPELINE_KEY", "PLATFORM_KEY", "ADMIN_API_KEY"):
        if os.environ.get(n):
            return os.environ[n]
    for f in (".env", ".env.local"):
        p = Path(__file__).parent.parent / f
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if ln.startswith(("PIPELINE_KEY=", "PLATFORM_KEY=", "ADMIN_API_KEY=")):
                    return ln.split("=", 1)[1].strip().strip("\"'")
    return ""


def generate(base_url: str, key: str, lesson_id: str, save: bool) -> dict | None:
    payload = json.dumps({"lessonId": lesson_id, "save": save}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/admin/workbook/generate", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        print(f"  [{lesson_id}] HTTP {e.code}: {detail}")
        return None
    except Exception as e:
        print(f"  [{lesson_id}] error: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--save",    action="store_true")
    ap.add_argument("--lesson",  help="Single lesson ID (e.g. M-012)")
    ap.add_argument("--url",     default=DEFAULT_URL)
    ap.add_argument("--prod",    action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    base_url = PROD_URL if args.prod else args.url
    key = _key()
    if not key:
        print("ADMIN_API_KEY / PIPELINE_KEY not found"); sys.exit(1)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = [l["id"] for l in manifest["lessons"]]
    # Mousetrap lessons only (M-###).
    ids = [i for i in ids if re.match(r"^M-\d", i, re.I)]
    if args.lesson:
        ids = [args.lesson.upper()]

    mode = "SAVE" if args.save else "DRY RUN"
    print(f"\nWorkbook AI-seed [{mode}] → {base_url}  ({len(ids)} Mousetrap lessons)")
    print("=" * 70)

    totals = {"ok": 0, "empty": 0, "failed": 0, "blocks": 0}
    for i, lid in enumerate(ids, 1):
        r = generate(base_url, key, lid, save=args.save)
        if not r:
            totals["failed"] += 1
        elif r.get("ok"):
            n = r.get("count", 0)
            totals["ok"] += 1; totals["blocks"] += n
            print(f"  [{lid}] {n} blocks{' (saved)' if r.get('saved') else ''}")
        else:
            totals["empty"] += 1
            print(f"  [{lid}] {r.get('error', 'no blocks')}")
        time.sleep(0.2)

    print("=" * 70)
    print(f"OK: {totals['ok']}  empty: {totals['empty']}  failed: {totals['failed']}  total blocks: {totals['blocks']}")
    print("Review each page in the admin lesson editor → Workbook page tab." if args.save else "Dry run — re-run with --save to write.")


if __name__ == "__main__":
    main()
