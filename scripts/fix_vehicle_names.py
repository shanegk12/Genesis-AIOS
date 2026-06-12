"""
fix_vehicle_names.py

Find-and-replace vehicle name corrections across all lesson blocks in Firestore.

Replacements (applied in order):
  1. "Little Moe"  -> "Mousetrap Mark 1.0"
  2. "Lil Moe"     -> "Mousetrap Mark 1.0"
  3. "Mark 1"      -> "Mark 1.1"  (only when NOT followed by .0 / .1 / any digit)

Usage:
  python scripts/fix_vehicle_names.py --dry-run     # show changes, no writes
  python scripts/fix_vehicle_names.py --save        # apply changes
  python scripts/fix_vehicle_names.py --save --course M   # Mousetrap only
"""

import argparse, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

LIVE_URL = "https://gk12academy.com"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

# ── Replacement rules ─────────────────────────────────────────────────────────
# Order matters: do the nickname→canonical replacements before the Mark-1 bump,
# so "Mousetrap Mark 1.0" (just created) is protected by the negative lookahead.

REPLACEMENTS = [
    # Step 1: bump "Mark 1" references first, before any new "Mark 1.0" instances exist
    # Negative lookahead protects "Mark 1.0", "Mark 1.1", etc. from double-replacement
    (re.compile(r"Mark 1(?!\.\d)"), "Mark 1.1"),
    # Step 2: rename nicknames to the canonical vehicle name
    (re.compile(r"Little Moe",   re.IGNORECASE), "Mousetrap Mark 1.0"),
    (re.compile(r"Lil Moe",      re.IGNORECASE), "Mousetrap Mark 1.0"),
]


def load_env() -> dict:
    env = {}
    for name in [".env", ".env.local"]:
        p = Path(__file__).parent.parent / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
    return env


def get_key(env: dict) -> str:
    return env.get("PIPELINE_KEY") or env.get("PLATFORM_KEY", "")


def fetch_lesson(lesson_id: str, key: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [WARN] fetch failed for {lesson_id}: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list, key: str) -> bool:
    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload, method="PATCH",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as e:
        print(f"  [ERROR] PATCH {lesson_id}: HTTP {e.code} {e.read().decode()[:100]}")
        return False
    except Exception as e:
        print(f"  [ERROR] PATCH {lesson_id}: {e}")
        return False


def apply_replacements(text: str) -> tuple[str, int]:
    """Apply all replacement rules to a string. Returns (new_text, change_count)."""
    changes = 0
    for pattern, replacement in REPLACEMENTS:
        new_text, n = pattern.subn(replacement, text)
        changes += n
        text = new_text
    return text, changes


def fix_block(block: dict) -> tuple[dict, int]:
    """Apply replacements to all text fields in a block. Returns (updated_block, total_changes)."""
    total = 0
    btype = block.get("type", "")
    data  = block.get("data", {})

    def fix(s: str) -> tuple[str, int]:
        return apply_replacements(s) if isinstance(s, str) else (s, 0)

    if btype in ("text", "callout"):
        new_html, n = fix(data.get("html", ""))
        if n:
            data = {**data, "html": new_html}
            total += n

    elif btype in ("accordion",):
        new_html, n1 = fix(data.get("html", ""))
        new_title, n2 = fix(data.get("title", ""))
        if n1 or n2:
            data = {**data, "html": new_html, "title": new_title}
            total += n1 + n2

    elif btype in ("tabs", "bordered-note"):
        new_tabs = []
        for tab in data.get("tabs", []):
            new_html, n1 = fix(tab.get("html", ""))
            new_title, n2 = fix(tab.get("title", ""))
            new_tabs.append({**tab, "html": new_html, "title": new_title})
            total += n1 + n2
        if total:
            data = {**data, "tabs": new_tabs}

    elif btype == "carousel":
        new_slides = []
        for slide in data.get("slides", []):
            new_html, n1  = fix(slide.get("html", ""))
            new_title, n2 = fix(slide.get("title", ""))
            new_cap, n3   = fix(slide.get("imageCaption", ""))
            new_slides.append({**slide, "html": new_html, "title": new_title, "imageCaption": new_cap})
            total += n1 + n2 + n3
        if total:
            data = {**data, "slides": new_slides}

    elif btype == "accordion-grid":
        new_items = []
        for item in data.get("items", []):
            new_html, n1  = fix(item.get("html", ""))
            new_title, n2 = fix(item.get("title", ""))
            new_items.append({**item, "html": new_html, "title": new_title})
            total += n1 + n2
        if total:
            data = {**data, "items": new_items}

    elif btype == "vocab":
        new_items = []
        for item in data.get("items", []):
            new_term, n1  = fix(item.get("term", ""))
            new_def, n2   = fix(item.get("definition", ""))
            new_items.append({**item, "term": new_term, "definition": new_def})
            total += n1 + n2
        if total:
            data = {**data, "items": new_items}

    elif btype == "image":
        new_cap, n = fix(data.get("caption", ""))
        if n:
            data = {**data, "caption": new_cap}
            total += n

    return {**block, "data": data}, total


def process_lesson(lesson_id: str, key: str, save: bool) -> tuple[int, bool]:
    """Returns (total_changes, success)."""
    lesson = fetch_lesson(lesson_id, key)
    if not lesson:
        return 0, False

    blocks = lesson.get("blocks", [])
    if not blocks:
        return 0, True

    new_blocks = []
    total_changes = 0
    for block in blocks:
        new_block, n = fix_block(block)
        new_blocks.append(new_block)
        total_changes += n

    if total_changes == 0:
        return 0, True

    print(f"  {lesson_id}: {total_changes} replacement(s)")
    if save:
        ok = patch_lesson(lesson_id, new_blocks, key)
        return total_changes, ok
    return total_changes, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save",    action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--course",  choices=["C", "M"], help="Limit to one course")
    args = parser.parse_args()

    save = args.save and not args.dry_run

    env = load_env()
    key = get_key(env)
    if not key:
        print("Error: PIPELINE_KEY not set in .env")
        sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lessons = manifest["lessons"]

    if args.course:
        lessons = [l for l in lessons if l["id"].startswith(args.course + "-")]

    print(f"{'[DRY RUN] ' if not save else ''}Scanning {len(lessons)} lessons for vehicle name fixes...\n")

    total_lessons_changed = 0
    total_replacements = 0
    failed = 0

    for i, lesson in enumerate(lessons, 1):
        lid = lesson["id"]
        n, ok = process_lesson(lid, key, save)
        if n:
            total_lessons_changed += 1
            total_replacements += n
        if not ok:
            failed += 1
        if save and i < len(lessons):
            time.sleep(0.2)

    print(f"\n{'[DRY RUN] ' if not save else ''}=== Done: {total_replacements} replacement(s) across {total_lessons_changed} lesson(s) | {failed} errors ===")
    if not save:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
