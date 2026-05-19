"""
Genesis K-12 QC Auto-Convert Agent

Calls the platform's /api/admin/qc/auto-convert endpoint for each lesson.
Gemini analyzes each lesson's blocks and converts text blocks that are
clearly better represented as vocab, callout, accordion-grid, or accordion.

Usage:
  python scripts/qc_auto_convert.py --dry-run             # preview only
  python scripts/qc_auto_convert.py --save                # analyze + save changes
  python scripts/qc_auto_convert.py --lesson-id C-025     # single lesson
  python scripts/qc_auto_convert.py --course C --save     # all Creationeering
  python scripts/qc_auto_convert.py --course M --save     # all Mousetrap
"""

import argparse, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
LOG_PATH      = os.path.join(os.path.dirname(__file__), "qc_auto_convert_log.json")


def call_auto_convert(lesson_id: str, dry_run: bool, save: bool) -> dict:
    payload = json.dumps({
        "lessonId": lesson_id,
        "dryRun": dry_run,
        "save": save,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/qc/auto-convert",
        data=payload,
        headers={
            "Authorization": f"Bearer {PLATFORM_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code}: {body[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lesson-id", help="Process a single lesson")
    parser.add_argument("--course", choices=["C", "M"], help="C=Creationeering, M=Mousetrap")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without saving")
    parser.add_argument("--save",    action="store_true", help="Apply and save changes to Firestore")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Specify --dry-run (preview) or --save (apply changes).")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    lessons = [l for l in manifest["lessons"] if l["status"] == "done"]

    if args.lesson_id:
        lessons = [l for l in lessons if l["id"] == args.lesson_id]
    elif args.course == "C":
        lessons = [l for l in lessons if l["id"].startswith("C-")]
    elif args.course == "M":
        lessons = [l for l in lessons if l["id"].startswith("M-")]

    mode = "DRY RUN" if args.dry_run else "LIVE (saving)"
    print(f"\nQC Auto-Convert [{mode}]: {len(lessons)} lessons\n")

    log = {}
    total_changes = 0
    counts = {"changed": 0, "no_change": 0, "error": 0}

    for lesson in lessons:
        lid = lesson["id"]
        result = call_auto_convert(lid, dry_run=args.dry_run, save=args.save)

        if not result.get("ok"):
            print(f"  [{lid}] ERROR: {result.get('error', 'unknown')}")
            counts["error"] += 1
            continue

        changes = result.get("changes", [])

        if changes:
            print(f"  [{lid}] {len(changes)} conversion(s):")
            for c in changes:
                saved_marker = " ✓ saved" if result.get("saved") else (" (dry run)" if args.dry_run else "")
                print(f"    block {c['index']} ({c['from']} → {c['to']}): {c['reason']}{saved_marker}")
            total_changes += len(changes)
            counts["changed"] += 1
            log[lid] = {
                "changes": changes,
                "saved": result.get("saved", False),
                "at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            print(f"  [{lid}] no changes needed")
            counts["no_change"] += 1

        time.sleep(0.3)  # avoid hammering the endpoint

    # Save log
    if not args.dry_run and counts["changed"] > 0:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)

    print(f"\n=== QC Auto-Convert {'Dry Run ' if args.dry_run else ''}Complete ===")
    print(f"  Lessons with changes : {counts['changed']}")
    print(f"  Lessons unchanged    : {counts['no_change']}")
    print(f"  Errors               : {counts['error']}")
    print(f"  Total conversions    : {total_changes}")
    if args.dry_run:
        print("\nRun with --save to apply these changes.")


if __name__ == "__main__":
    main()
