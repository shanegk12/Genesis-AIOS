"""
qc_scan_missing_interactives.py

Scans all lessons to find interactive files that exist locally but have no
corresponding embed block pointing to them. Outputs a clean report and an
optional fix that adds the missing embed blocks with the correct proxy URLs.

Usage:
  python scripts/qc_scan_missing_interactives.py           # scan + report only
  python scripts/qc_scan_missing_interactives.py --fix     # scan + add missing blocks
  python scripts/qc_scan_missing_interactives.py --lesson C-025  # single lesson
"""

import argparse, json, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
INTERACTIVES_DIR = Path(__file__).parent / "interactives"
MANIFEST_PATH    = Path(__file__).parent / "lessons_manifest.json"
REPORT_PATH      = Path(__file__).parent / "missing_interactives_report.json"

FILE_LABELS = {
    "flashcards.html":  "Vocabulary Flashcards",
    "concept.html":     "Interactive Activity",
    "simulation.html":  "Interactive Simulation",
    "physics.html":     "Physics Sandbox",
    "model.html":       "3D System Viewer",
    "ocv.html":         "OCV Explorer",
    "vocab.html":       "Vocabulary Review",
}

# accordion.html retired — skip it
SKIP_FILES = {"accordion.html"}


def load_api_key() -> str:
    import os
    key = os.environ.get("PIPELINE_KEY") or os.environ.get("PLATFORM_KEY", "")
    if key:
        return key
    env = Path(__file__).parent.parent / ".env"
    for line in env.read_text().splitlines():
        if line.startswith(("PIPELINE_KEY=", "PLATFORM_KEY=")) and "=" in line:
            return line.split("=", 1)[1].strip()
    raise RuntimeError("PIPELINE_KEY not found in .env")


def load_manifest() -> list[str]:
    data = json.loads(MANIFEST_PATH.read_text())
    entries = data["lessons"] if isinstance(data, dict) else data
    return [entry["id"] if isinstance(entry, dict) else entry for entry in entries]


def fetch_lesson(lesson_id: str, key: str) -> dict | None:
    url = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [{lesson_id}] fetch error: {e}")
        return None


def patch_blocks(lesson_id: str, blocks: list, key: str) -> bool:
    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        method="PATCH",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 204)
    except Exception as e:
        print(f"  [{lesson_id}] PATCH error: {e}")
        return False


def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def scan_lesson(lesson_id: str, key: str) -> dict:
    """
    Returns { "missing": [filename, ...], "has_embed": [filename, ...] }
    missing = local file exists but no filled embed block points to it
    """
    local_dir = INTERACTIVES_DIR / lesson_id
    if not local_dir.exists():
        return {"missing": [], "has_embed": []}

    local_files = [
        f.name for f in sorted(local_dir.iterdir())
        if f.suffix == ".html" and f.name not in SKIP_FILES
    ]
    if not local_files:
        return {"missing": [], "has_embed": []}

    lesson = fetch_lesson(lesson_id, key)
    if not lesson:
        return {"missing": [], "has_embed": [], "error": True}

    blocks = lesson.get("blocks", [])
    # Build set of filenames referenced by filled embed blocks
    linked = set()
    for b in blocks:
        if b.get("type") != "embed":
            continue
        src = (b.get("data") or {}).get("src", "").strip()
        if not src:
            continue
        # src is /api/interactive/{lessonId}/{filename}
        fname = src.split("/")[-1]
        linked.add(fname)

    missing = [f for f in local_files if f not in linked]
    has_embed = [f for f in local_files if f in linked]
    return {"missing": missing, "has_embed": has_embed}


def fix_lesson(lesson_id: str, missing_files: list, key: str) -> bool:
    """Add embed blocks for each missing file. Only touches embed blocks."""
    lesson = fetch_lesson(lesson_id, key)
    if not lesson:
        return False

    blocks = list(lesson.get("blocks", []))
    added = 0
    for fname in missing_files:
        proxy_url = f"/api/interactive/{lesson_id}/{fname}"
        label = FILE_LABELS.get(fname, fname.replace(".html", "").replace("-", " ").title())
        blocks.append({
            "id": gen_id(),
            "type": "embed",
            "data": {"src": proxy_url, "height": 500, "title": label},
            "meta": {"spacing": "md", "qcStatus": "pending"},
        })
        added += 1

    if added == 0:
        return True

    ok = patch_blocks(lesson_id, blocks, key)
    if ok:
        print(f"  [{lesson_id}] Added {added} embed block(s): {missing_files}")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix",    action="store_true", help="Add missing embed blocks")
    parser.add_argument("--lesson", nargs="+", help="One or more lesson IDs (e.g. C-001 C-025)")
    args = parser.parse_args()

    key = load_api_key()
    lesson_ids = args.lesson if args.lesson else load_manifest()

    report: dict[str, dict] = {}
    total_missing = 0
    missing_by_type: dict[str, int] = {}

    print(f"{'FIX' if args.fix else 'SCAN'} — {len(lesson_ids)} lesson(s)\n{'='*60}")

    for i, lid in enumerate(lesson_ids, 1):
        result = scan_lesson(lid, key)
        missing = result.get("missing", [])
        has = result.get("has_embed", [])

        if missing or result.get("error"):
            status = "ERROR" if result.get("error") else f"MISSING {missing}"
            print(f"[{i}/{len(lesson_ids)}] {lid}: {status}")
            for f in missing:
                missing_by_type[f] = missing_by_type.get(f, 0) + 1

        report[lid] = result
        total_missing += len(missing)

        if args.fix and missing:
            fix_lesson(lid, missing, key)
            time.sleep(0.3)
        elif not missing and not result.get("error"):
            pass  # clean — no output

    # Summary
    print(f"\n{'='*60}")
    print(f"Total lessons scanned:  {len(lesson_ids)}")
    print(f"Lessons with gaps:      {sum(1 for r in report.values() if r.get('missing'))}")
    print(f"Total missing blocks:   {total_missing}")
    if missing_by_type:
        print("\nMissing by interactive type:")
        for fname, count in sorted(missing_by_type.items(), key=lambda x: -x[1]):
            print(f"  {fname:<25} {count} lessons")

    # Save report
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nFull report saved → {REPORT_PATH}")

    if total_missing > 0 and not args.fix:
        print("\nRun with --fix to add the missing embed blocks.")


if __name__ == "__main__":
    main()
