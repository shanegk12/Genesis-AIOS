"""
fix_embed_fields.py

Scans every lesson via the platform API, finds embed blocks that use the
legacy "src"/"label" field names instead of the correct "url"/"title",
and patches them in Firestore via PATCH /api/admin/lessons/{id}.

Usage:
  python scripts/fix_embed_fields.py --dry-run
  python scripts/fix_embed_fields.py --save
  python scripts/fix_embed_fields.py --lesson C-001 --save
"""

import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"


def _get_platform_key() -> str:
    k = os.environ.get("PIPELINE_KEY") or os.environ.get("PLATFORM_KEY", "")
    if k:
        return k
    for name in [".env", ".env.local"]:
        p = Path(__file__).parent.parent / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(("PIPELINE_KEY=", "PLATFORM_KEY=")) and "=" in line:
                    return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def fetch_lesson(lesson_id: str, key: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"  Fetch HTTP {e.code}: {lesson_id}")
        return None
    except Exception as e:
        print(f"  Fetch error {lesson_id}: {e}")
        return None


def patch_blocks(lesson_id: str, blocks: list, key: str) -> bool:
    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error {lesson_id}: {e}")
        return False


def fix_embed_block(block: dict) -> tuple[dict, bool]:
    """Return (fixed_block, was_changed)."""
    if block.get("type") != "embed":
        return block, False

    data = dict(block.get("data", {}))
    changed = False

    # Fix src → url
    if "src" in data and data["src"] and not data.get("url"):
        data["url"] = data.pop("src")
        changed = True
    elif "src" in data:
        del data["src"]
        changed = True

    # Fix label → title
    if "label" in data and data["label"] and not data.get("title"):
        data["title"] = data.pop("label")
        changed = True
    elif "label" in data:
        del data["label"]
        changed = True

    if not changed:
        return block, False

    return {**block, "data": data}, True


def process_lesson(lesson_id: str, key: str, dry_run: bool) -> str:
    lesson = fetch_lesson(lesson_id, key)
    if lesson is None:
        return "not_found"

    blocks = lesson.get("blocks", [])
    if not blocks:
        return "no_blocks"

    fixed_blocks = []
    changes = []
    for block in blocks:
        fixed, changed = fix_embed_block(block)
        fixed_blocks.append(fixed)
        if changed:
            url = fixed["data"].get("url", "")
            title = fixed["data"].get("title", "")
            changes.append(f"    embed → url={url[:60]} title={title}")

    if not changes:
        return "clean"

    print(f"  [{lesson_id}] {len(changes)} embed block(s) to fix:")
    for c in changes:
        print(c)

    if dry_run:
        return "would_fix"

    ok = patch_blocks(lesson_id, fixed_blocks, key)
    if ok:
        print(f"  [{lesson_id}] PATCHED OK")
        return "fixed"
    else:
        print(f"  [{lesson_id}] PATCH FAILED")
        return "patch_failed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--lesson",  help="Single lesson ID")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    key = _get_platform_key()
    if not key:
        print("PIPELINE_KEY not found"); sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lesson_ids = [l["id"] for l in manifest["lessons"]]

    if args.lesson:
        lesson_ids = [args.lesson.upper()]

    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"\nFix Embed Fields [{mode}] — {len(lesson_ids)} lesson(s)")
    print("=" * 60)

    counts: dict[str, int] = {}
    for i, lid in enumerate(lesson_ids, 1):
        status = process_lesson(lid, key, dry_run=args.dry_run)
        counts[status] = counts.get(status, 0) + 1
        if status not in ("clean", "no_blocks", "not_found"):
            print()
        time.sleep(0.05)

    print("=" * 60)
    print("SUMMARY:", counts)
    if counts.get("patch_failed"):
        print("FAILED:", counts["patch_failed"], "lessons — check output above")


if __name__ == "__main__":
    main()
