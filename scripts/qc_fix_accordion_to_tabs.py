"""
Fix accordion blocks that should be tabs.

After the screenshot import + QC pass, some multi-section text blocks were
converted to accordion instead of tabs. This script:
  1. Fetches each lesson's blocks via the platform API
  2. Finds accordion blocks whose HTML contains 2–5 parseable h3/h4 sections
  3. Converts them to tabs (or accordion-grid if 6+ sections)
  4. PATCHes the lesson back — image block src URLs are NOT touched

Usage:
  python scripts/qc_fix_accordion_to_tabs.py               # dry-run, show what would change
  python scripts/qc_fix_accordion_to_tabs.py --save        # apply changes
  python scripts/qc_fix_accordion_to_tabs.py --lesson C-002 --save
"""

import argparse, json, os, re, sys, urllib.request, urllib.error, uuid
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

HIGH_PRIORITY_LESSONS = [
    "C-002", "C-003", "C-007",
    "M-002", "M-003", "M-006", "M-011", "M-012",
]

H_RE = re.compile(r"<h[34][^>]*>([^<]+)</h[34]>", re.IGNORECASE)


def parse_sections(html: str) -> list[dict]:
    """Split HTML on h3/h4 headings into titled sections."""
    items = []
    parts = re.split(r"(?=<h[34][\s>])", html, flags=re.IGNORECASE)
    for part in parts:
        m = re.match(r"<h[34][^>]*>([^<]+)</h[34]>(.*)", part, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()
            body  = m.group(2).strip()
            items.append({"title": title, "html": body})
    return items


def fetch_lesson(lesson_id: str) -> list[dict] | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers=HEADERS,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("blocks", [])
    except Exception as e:
        print(f"  [FETCH ERR] {lesson_id}: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list[dict]) -> bool:
    payload = json.dumps({"blocks": blocks, "contentSource": "platform"}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers=HEADERS,
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"  [PATCH ERR] {lesson_id}: {e}")
        return False


def fix_lesson(lesson_id: str, save: bool) -> int:
    blocks = fetch_lesson(lesson_id)
    if blocks is None:
        return 0

    changes = 0
    updated = list(blocks)

    for i, block in enumerate(blocks):
        if block.get("type") != "accordion":
            continue

        html = block.get("data", {}).get("html", "")
        sections = parse_sections(html)

        if len(sections) < 2:
            continue  # Single-section accordion is fine

        new_type = "tabs" if len(sections) <= 5 else "accordion-grid"

        if new_type == "tabs":
            new_block = {
                "id":   block["id"],
                "type": "tabs",
                "data": {"tabs": sections},
                "meta": {**block.get("meta", {}), "qcStatus": "pending"},
            }
        else:
            new_block = {
                "id":   block["id"],
                "type": "accordion-grid",
                "data": {"columns": 2, "items": sections},
                "meta": {**block.get("meta", {}), "qcStatus": "pending"},
            }

        title_preview = sections[0]["title"][:40] if sections else "?"
        print(f"  Block {i}: accordion({len(sections)} sections) → {new_type}  [{title_preview}...]")
        updated[i] = new_block
        changes += 1

    if changes == 0:
        print(f"  {lesson_id}: no accordion→tabs conversions needed")
    elif save:
        ok = patch_lesson(lesson_id, updated)
        print(f"  {lesson_id}: {'saved' if ok else 'SAVE FAILED'} ({changes} conversion(s))")
    else:
        print(f"  {lesson_id}: {changes} conversion(s) — dry run, use --save to apply")

    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save",   action="store_true", help="Apply changes (default: dry run)")
    parser.add_argument("--lesson", help="Single lesson ID, e.g. C-002")
    args = parser.parse_args()

    lessons = [args.lesson.upper()] if args.lesson else HIGH_PRIORITY_LESSONS

    total = 0
    for lesson_id in lessons:
        print(f"\n{lesson_id}")
        total += fix_lesson(lesson_id, save=args.save)

    print(f"\nTotal: {total} conversion(s) {'applied' if args.save else '(dry run)'}")


if __name__ == "__main__":
    main()
