"""
Migrate all lesson blocks with type="tabs" to type="bordered-note".

The old "tabs" block was a stacked bordered card layout, not real tab navigation.
It has been renamed to "bordered-note". A new "tabs" block type now provides
proper interactive tab button navigation.

Usage:
  python scripts/migrate_tabs_to_bordered_note.py               # dry-run
  python scripts/migrate_tabs_to_bordered_note.py --save        # apply
  python scripts/migrate_tabs_to_bordered_note.py --lesson C-002 --save
"""

import argparse, json, os, sys, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ENV_PATH = Path(__file__).parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
def _get_platform_key() -> str:
    """Load platform API key from .env — never hardcode in source."""
    import os as _os
    from pathlib import Path as _Path
    k = _os.environ.get('PIPELINE_KEY') or _os.environ.get('PLATFORM_KEY', '')
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=')) and '=' in _line:
                    return _line.split('=', 1)[1].strip().strip('""')
    return ''
PLATFORM_KEY = _get_platform_key()
HEADERS      = {"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"}

# All lesson IDs to migrate (expand as needed)
ALL_LESSONS = [
    "C-001","C-002","C-003","C-004","C-005","C-006","C-007","C-008","C-009",
    "C-010","C-011","C-012","C-013","C-014","C-015","C-016","C-017","C-018",
    "M-002","M-003","M-004","M-005","M-006","M-011","M-012","M-014","M-018","M-019",
]


def fetch_lesson(lesson_id: str) -> list[dict] | None:
    req = urllib.request.Request(f"{LIVE_URL}/api/admin/lessons/{lesson_id}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("blocks", [])
    except Exception as e:
        print(f"  [FETCH ERR] {lesson_id}: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list[dict]) -> bool:
    payload = json.dumps({"blocks": blocks, "contentSource": "platform"}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload, headers=HEADERS, method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  [PATCH ERR] {lesson_id}: {e}")
        return False


def migrate_lesson(lesson_id: str, save: bool) -> int:
    blocks = fetch_lesson(lesson_id)
    if blocks is None:
        return 0

    count = sum(1 for b in blocks if b.get("type") == "tabs")
    if count == 0:
        return 0

    print(f"  {lesson_id}: {count} tabs block(s) → bordered-note")
    if not save:
        return count

    updated = [
        {**b, "type": "bordered-note"} if b.get("type") == "tabs" else b
        for b in blocks
    ]
    ok = patch_lesson(lesson_id, updated)
    print(f"    {'saved' if ok else 'SAVE FAILED'}")
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save",   action="store_true")
    parser.add_argument("--lesson", help="Single lesson ID")
    args = parser.parse_args()

    lessons = [args.lesson.upper()] if args.lesson else ALL_LESSONS

    total = 0
    for lesson_id in lessons:
        total += migrate_lesson(lesson_id, save=args.save)

    print(f"\nTotal: {total} block(s) {'migrated' if args.save else '(dry run)'}")


if __name__ == "__main__":
    main()
