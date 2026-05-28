"""
fix_embed_src_to_url.py

Fixes embed blocks written by qc_gen_platform_interactives.py that used
`data.src` + `data.label` instead of the correct `data.url` + `data.title`.

For every lesson with embed blocks that have `data.src`, this script:
  1. Renames `src` → `url`
  2. Renames `label` → `title`
  3. PATCHes the lesson (other blocks untouched)

Run:
  python scripts/fix_embed_src_to_url.py --dry-run   # preview only
  python scripts/fix_embed_src_to_url.py --save       # apply fixes
"""

import argparse, json, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"


def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  fetch error: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list) -> bool:
    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


def fix_blocks(blocks: list) -> tuple[list, int]:
    """Return (fixed_blocks, count_fixed). Mutates nothing — returns new list."""
    fixed = []
    count = 0
    for block in blocks:
        if block.get("type") == "embed":
            data = dict(block.get("data", {}))
            changed = False
            if "src" in data and "url" not in data:
                data["url"] = data.pop("src")
                changed = True
            if "label" in data and "title" not in data:
                data["title"] = data.pop("label")
                changed = True
            if changed:
                block = {**block, "data": data}
                count += 1
        fixed.append(block)
    return fixed, count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--lesson-id", help="Fix a single lesson")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    # Build lesson ID list
    if args.lesson_id:
        lesson_ids = [args.lesson_id]
    elif MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        lesson_ids = [l["id"] for l in manifest["lessons"]]
    else:
        print("No manifest found and no --lesson-id given"); sys.exit(1)

    print(f"{'DRY RUN — ' if args.dry_run else ''}Scanning {len(lesson_ids)} lessons...\n")

    results = {"fixed": 0, "clean": 0, "fetch_error": 0, "patch_error": 0}

    for i, lesson_id in enumerate(lesson_ids, 1):
        lesson = fetch_lesson(lesson_id)
        if not lesson:
            print(f"[{i}/{len(lesson_ids)}] {lesson_id}: FETCH ERROR")
            results["fetch_error"] += 1
            continue

        blocks = lesson.get("blocks", [])
        bad_count = sum(
            1 for b in blocks
            if b.get("type") == "embed" and "src" in b.get("data", {})
        )

        if bad_count == 0:
            print(f"[{i}/{len(lesson_ids)}] {lesson_id}: clean (no bad embeds)")
            results["clean"] += 1
            continue

        fixed_blocks, count = fix_blocks(blocks)
        print(f"[{i}/{len(lesson_ids)}] {lesson_id}: {count} embed block(s) to fix", end="")

        if args.dry_run:
            print(" [DRY RUN — skipping patch]")
            results["fixed"] += 1
            continue

        ok = patch_lesson(lesson_id, fixed_blocks)
        if ok:
            print(" ✓")
            results["fixed"] += 1
        else:
            print(" PATCH FAILED")
            results["patch_error"] += 1

        time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"Results: {results}")
    if args.dry_run:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
