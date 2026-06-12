"""
set_estimated_times.py

Fetches every lesson, calculates estimatedMinutes from its block types
using the same weights as src/lib/estimateTime.ts, and PATCHes the value
to Firestore via the platform API.

Skips lessons that already have estimatedMinutes set (use --force to overwrite).

Usage:
  python scripts/set_estimated_times.py --dry-run
  python scripts/set_estimated_times.py --save
  python scripts/set_estimated_times.py --lesson C-011 --save
  python scripts/set_estimated_times.py --save --force
"""

import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

# Must mirror src/lib/estimateTime.ts
BLOCK_MINUTES: dict[str, float] = {
    "text":           3,
    "image":          0.5,
    "video":          4,
    "embed":          5,
    "code-embed":     5,
    "quiz":           6,
    "vocab":          2,
    "callout":        1,
    "accordion":      1.5,
    "tabs":           1.5,
    "bordered-note":  1.5,
    "carousel":       2,
    "columns":        1.5,
    "column-grid":    1.5,
    "accordion-grid": 2,
    "code-snippet":   1.5,
    "math":           1,
    "divider":        0,
}


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


def estimate_minutes(blocks: list) -> int:
    total = sum(BLOCK_MINUTES.get(b.get("type", ""), 1) for b in blocks)
    return max(5, round(total / 5) * 5)


def format_time(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h} hr {m} min" if m else f"{h} hr"


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


def patch_lesson(lesson_id: str, estimated_minutes: int, key: str) -> bool:
    payload = json.dumps({"estimatedMinutes": estimated_minutes}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error {lesson_id}: {e}")
        return False


def process_lesson(lesson_id: str, key: str, dry_run: bool, force: bool) -> str:
    lesson = fetch_lesson(lesson_id, key)
    if lesson is None:
        return "not_found"

    existing = lesson.get("estimatedMinutes")
    if existing and not force:
        return "already_set"

    blocks = lesson.get("blocks", [])
    if not blocks:
        return "no_blocks"

    minutes = estimate_minutes(blocks)
    action = "would set" if dry_run else "set"
    changed = f" (was {existing})" if existing and force else ""
    print(f"  [{lesson_id}] {action} {minutes} min ({format_time(minutes)}){changed}  [{len(blocks)} blocks]")

    if dry_run:
        return "would_set"

    ok = patch_lesson(lesson_id, minutes, key)
    return "set" if ok else "patch_failed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--lesson",  help="Single lesson ID")
    parser.add_argument("--force",   action="store_true", help="Overwrite existing values")
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
    print(f"\nSet Estimated Times [{mode}] — {len(lesson_ids)} lesson(s) | force={args.force}")
    print("=" * 60)

    counts: dict[str, int] = {}
    for lid in lesson_ids:
        status = process_lesson(lid, key, dry_run=args.dry_run, force=args.force)
        counts[status] = counts.get(status, 0) + 1
        time.sleep(0.05)

    print("=" * 60)
    print("SUMMARY:", counts)
    if counts.get("patch_failed"):
        print(f"WARNING: {counts['patch_failed']} lessons failed to patch")


if __name__ == "__main__":
    main()
