"""
Genesis K-12 — Batch Screenshot Importer

Runs screenshot_import.py for all lessons that have screenshots, mapping
the LW folder names to platform lesson IDs.

Workflow:
  1. Review dry-run output (default — no patching, saves JSON per lesson)
  2. Inspect JSON files in screenshots_import_output/
  3. Patch individual lessons:  python scripts/screenshot_import.py C-007 --patch
  4. Or patch all at once:      python scripts/screenshot_import_batch.py --patch

Usage:
  python scripts/screenshot_import_batch.py              # extract all, save JSON
  python scripts/screenshot_import_batch.py --patch      # extract + patch all (destructive!)
  python scripts/screenshot_import_batch.py --lesson C-007   # single lesson
  python scripts/screenshot_import_batch.py --priority high  # high-priority only
"""

import argparse, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load API keys from .env so subprocesses inherit them
_ENV_PATH = Path(__file__).parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SCREENSHOTS_ROOT = Path(__file__).parent.parent / "screenshots"
OUTPUT_DIR       = Path(__file__).parent.parent / "screenshots_import_output"
SCRIPT           = Path(__file__).parent / "screenshot_import.py"
LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY     = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"

# ── Folder → lesson ID mapping ────────────────────────────────────────────────
# Keys match the actual folder names in screenshots/Creationeering/ and screenshots/Mousetrap/
# Priority: high = replace immediately; medium = replace after review

LESSON_MAP = [
    # Creationeering
    {"folder": "Creationeering/What is Engineering",                   "id": "C-001", "priority": "medium"},
    {"folder": "Creationeering/Entrepreneurship",                      "id": "C-002", "priority": "high"},
    {"folder": "Creationeering/Genesis and Creationeering",            "id": "C-003", "priority": "high"},
    {"folder": "Creationeering/Understanding Math and Science as Tools","id": "C-004", "priority": "medium"},
    {"folder": "Creationeering/Units Conversions and Measurement",     "id": "C-005", "priority": "medium"},
    {"folder": "Creationeering/Intro to Systems Thinking",             "id": "C-006", "priority": "medium"},
    {"folder": "Creationeering/Objectives Constraints and Variables",  "id": "C-007", "priority": "high"},
    {"folder": "Creationeering/Ethics in Engineering and Stewardship", "id": "C-008", "priority": "medium"},
    {"folder": "Creationeering/Process Mapping and Flowcharts",        "id": "C-009", "priority": "medium"},
    {"folder": "Creationeering/Visualization and sketching",           "id": "C-010", "priority": "medium"},
    {"folder": "Creationeering/Design Forces and Influences",          "id": "C-011", "priority": "medium"},
    {"folder": "Creationeering/Design Historical Case Studies",        "id": "C-012", "priority": "medium"},
    {"folder": "Creationeering/Form Function and Aesthetic",           "id": "C-013", "priority": "medium"},
    {"folder": "Creationeering/Design Iteration and Communication",    "id": "C-014", "priority": "medium"},
    {"folder": "Creationeering/Alternatives and Patents",              "id": "C-015", "priority": "medium"},
    {"folder": "Creationeering/Novelty and Innovation in Engineering", "id": "C-016", "priority": "medium"},
    {"folder": "Creationeering/Concept Generation",                    "id": "C-017", "priority": "medium"},
    {"folder": "Creationeering/Fundamentals of Force Motion and Work", "id": "C-018", "priority": "medium"},
    # "Understanding Design" folder present but no lesson ID confirmed — skipped until mapped
    # Mousetrap
    {"folder": "Mousetrap/Mousetrap Course Intro",                     "id": "M-002", "priority": "high"},
    {"folder": "Mousetrap/Kit Overview",                               "id": "M-003", "priority": "high"},
    {"folder": "Mousetrap/OCV",                                        "id": "M-004", "priority": "medium"},
    {"folder": "Mousetrap/Prototyping and Iterative Design",           "id": "M-005", "priority": "medium"},
    {"folder": "Mousetrap/Build 1 Mousetrap Prototype Mark 1.0",      "id": "M-006", "priority": "high"},
    {"folder": "Mousetrap/Design",                                     "id": "M-011", "priority": "high"},
    {"folder": "Mousetrap/Communicating Designs and Testing",          "id": "M-012", "priority": "high"},
    {"folder": "Mousetrap/Power Transmission Mechanics",               "id": "M-014", "priority": "medium"},
    {"folder": "Mousetrap/The Dynamics of Stored Energy",              "id": "M-018", "priority": "medium"},
    {"folder": "Mousetrap/Modeling Resistive Forces",                  "id": "M-019", "priority": "medium"},
]


def count_screenshots(folder_rel: str) -> int:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    folder = SCREENSHOTS_ROOT / folder_rel
    if not folder.exists():
        return 0
    return sum(1 for f in folder.iterdir() if f.suffix.lower() in exts)


def run_qc_split(lesson_id: str) -> bool:
    """Run qc_split_headings.py for a single lesson."""
    split_script = Path(__file__).parent / "qc_split_headings.py"
    try:
        result = subprocess.run(
            [sys.executable, str(split_script), "--lesson-id", lesson_id, "--save"],
            capture_output=True, text=True, timeout=60,
        )
        output = (result.stdout + result.stderr)[-300:]
        ok = result.returncode == 0
        print(f"  [QC split-headings] {lesson_id}: {'ok' if ok else 'ERR'} — {output.strip()[-120:]}")
        return ok
    except Exception as e:
        print(f"  [QC split-headings ERR] {lesson_id}: {e}")
        return False


def run_qc_autoconvert(lesson_id: str) -> bool:
    """Call qc_auto_convert for a single lesson via the platform API."""
    try:
        payload = json.dumps({"lessonId": lesson_id, "dryRun": False, "save": True}).encode()
        req = urllib.request.Request(
            f"{LIVE_URL}/api/admin/qc/auto-convert",
            data=payload,
            headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
            ok = result.get("ok", False)
            changes = len(result.get("changes", []))
            print(f"  [QC auto-convert] {lesson_id}: {changes} conversion(s)")
            return ok
    except Exception as e:
        print(f"  [QC auto-convert ERR] {lesson_id}: {e}")
        return False


def run_import(entry: dict, patch: bool, qc: bool, yes: bool = False) -> dict:
    """Run screenshot_import.py for one lesson, then optionally re-run QC."""
    lesson_id  = entry["id"]
    folder_abs = SCREENSHOTS_ROOT / entry["folder"]
    out_path   = OUTPUT_DIR / f"{lesson_id}.json"

    n = count_screenshots(entry["folder"])
    print(f"\n{'='*60}")
    print(f"  {lesson_id} — {entry['folder']} ({n} screenshots)")

    if n == 0:
        print(f"  [SKIP] No screenshots found")
        return {"id": lesson_id, "status": "no_screenshots"}

    # M-006 has 53 screenshots — give it more time
    timeout = 600 if n > 30 else 300

    cmd = [
        sys.executable, str(SCRIPT),
        lesson_id,
        "--folder", str(folder_abs),
        "--out", str(out_path),
    ]
    if patch:
        cmd.extend(["--patch", "--yes"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            print(f"  [ERR] Exit {result.returncode}")
            print(result.stderr[-500:] if result.stderr else "(no stderr)")
            return {"id": lesson_id, "status": "error", "stderr": result.stderr[-200:]}
        print(result.stdout[-600:])
        status = "patched" if patch else "extracted"

        # QC re-pass: split headings then auto-convert
        if patch and qc:
            print(f"\n  Running QC pass for {lesson_id}...")
            time.sleep(1)
            run_qc_split(lesson_id)
            time.sleep(2)
            run_qc_autoconvert(lesson_id)
            status = "patched+qc"

        return {"id": lesson_id, "status": status, "out": str(out_path)}
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {lesson_id}")
        return {"id": lesson_id, "status": "timeout"}
    except Exception as e:
        print(f"  [EXCEPTION] {e}")
        return {"id": lesson_id, "status": "exception", "error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch",    action="store_true", help="Patch all lessons after extraction (destructive)")
    parser.add_argument("--qc",       action="store_true", help="Run split-headings + auto-convert after each patch")
    parser.add_argument("--yes",      action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--lesson",   help="Run for a single lesson ID only, e.g. C-007")
    parser.add_argument("--priority", choices=["high", "medium", "all"], default="all",
                        help="Filter by priority level (default: all)")
    args = parser.parse_args()

    if args.qc and not args.patch:
        print("--qc requires --patch (QC only runs on lessons that were just patched)")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Filter lesson list
    lessons = LESSON_MAP
    if args.lesson:
        lessons = [e for e in lessons if e["id"].upper() == args.lesson.upper()]
        if not lessons:
            print(f"Lesson {args.lesson} not found in LESSON_MAP")
            sys.exit(1)
    elif args.priority != "all":
        lessons = [e for e in lessons if e["priority"] == args.priority]

    print(f"\nBatch Screenshot Import")
    print(f"Lessons: {len(lessons)} | Patch: {args.patch} | QC: {args.qc} | Priority: {args.priority}")
    print(f"Output:  {OUTPUT_DIR}")

    if args.patch and not args.yes:
        confirm = input(f"\n  ⚠ This will REPLACE blocks for {len(lessons)} lesson(s) on the LIVE platform. Continue? [y/N] ")
        if confirm.strip().lower() != "y":
            print("  Aborted.")
            sys.exit(0)

    results = []
    for entry in lessons:
        result = run_import(entry, patch=args.patch, qc=args.qc, yes=args.yes)
        results.append(result)
        time.sleep(1)  # avoid API rate limits

    # Summary
    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE")
    status_counts = {}
    for r in results:
        s = r["status"]
        status_counts[s] = status_counts.get(s, 0) + 1
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    errors = [r for r in results if r["status"] in ("error", "timeout", "exception")]
    if errors:
        print(f"\n  Failed lessons:")
        for r in errors:
            print(f"    {r['id']}: {r.get('stderr','')[:100]}")

    # Save summary
    summary_path = OUTPUT_DIR / "_batch_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Summary saved to {summary_path}")
    print(f"  Review JSON files in {OUTPUT_DIR} before patching")


if __name__ == "__main__":
    main()
