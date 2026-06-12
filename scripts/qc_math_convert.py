"""
Genesis K-12 — Math Block Extractor

Scans lesson text blocks for display-math patterns ($$...$$) and extracts
them into dedicated `math` blocks, preserving surrounding prose.

Pattern handled:
  <p>$$F = m \\cdot a$$</p>     →  math block  { latex, display: true }

Any text BEFORE the $$ line stays in the preceding text block.
Any text AFTER  the $$ line goes into a new text block after the math block.
Inline $...$ is left in text blocks (rendered client-side by LessonRenderer).

Usage:
  python scripts/qc_math_convert.py --dry-run         # preview only
  python scripts/qc_math_convert.py                   # migrate all
  python scripts/qc_math_convert.py --lesson-id C-033 # single lesson
  python scripts/qc_math_convert.py --course C        # Creationeering only
  python scripts/qc_math_convert.py --course M        # Mousetrap only
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error, uuid
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
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
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
LOG_PATH      = os.path.join(os.path.dirname(__file__), "qc_math_log.json")

# Matches a standalone display-math paragraph: <p>$$expression$$</p>
# Handles optional whitespace and multi-line LaTeX
DISPLAY_MATH_RE = re.compile(
    r'<p[^>]*>\s*\$\$([\s\S]+?)\$\$\s*</p>',
    re.DOTALL,
)


def _default_meta() -> dict:
    return {"spacing": "md", "qcStatus": "pending"}


def _split_math(block: dict) -> list[dict]:
    """
    Split a text block at $$...$$ paragraphs into:
      [text?, math, text?, math, text?, ...]
    Returns original single-item list if no display math found.
    """
    html = block.get("data", {}).get("html", "")
    if "$$" not in html:
        return [block]

    parts: list[dict] = []
    last_end = 0

    for m in DISPLAY_MATH_RE.finditer(html):
        before = html[last_end : m.start()].strip()
        if before:
            parts.append({
                "id":   str(uuid.uuid4()),
                "type": "text",
                "data": {"html": before},
                "meta": block.get("meta", _default_meta()).copy(),
            })

        latex = m.group(1).strip()
        parts.append({
            "id":   str(uuid.uuid4()),
            "type": "math",
            "data": {"latex": latex, "display": True},
            "meta": {"spacing": "md", "qcStatus": "pending"},
        })
        last_end = m.end()

    after = html[last_end:].strip()
    if after:
        parts.append({
            "id":   str(uuid.uuid4()),
            "type": "text",
            "data": {"html": after},
            "meta": block.get("meta", _default_meta()).copy(),
        })

    return parts if parts else [block]


def _has_display_math(blocks: list) -> bool:
    for b in blocks:
        if b.get("type") == "text":
            html = b.get("data", {}).get("html", "")
            if "$$" in html and DISPLAY_MATH_RE.search(html):
                return True
    return False


# ── Platform API helpers ──────────────────────────────────────────────────────

def _fetch_lesson(lesson_id: str) -> dict | None:
    url = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {PLATFORM_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"    Fetch error: {e}")
        return None


def _patch_blocks(lesson_id: str, blocks: list) -> bool:
    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"    PATCH error: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lesson-id", help="Process a single lesson")
    parser.add_argument("--course", choices=["C", "M"])
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without saving")
    args = parser.parse_args()

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    lessons = [l for l in manifest["lessons"] if l["status"] == "done"]
    if args.lesson_id:
        lessons = [l for l in lessons if l["id"] == args.lesson_id]
    elif args.course == "C":
        lessons = [l for l in lessons if l["id"].startswith("C-")]
    elif args.course == "M":
        lessons = [l for l in lessons if l["id"].startswith("M-")]

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\nMath Block Extractor [{mode}]: checking {len(lessons)} lessons\n")

    log: dict = {}
    counts = {"converted": 0, "skipped": 0, "error": 0}

    for lesson in lessons:
        lid = lesson["id"]
        data = _fetch_lesson(lid)
        if not data:
            counts["error"] += 1
            continue

        blocks = data.get("blocks", [])
        if not _has_display_math(blocks):
            counts["skipped"] += 1
            continue

        # Expand blocks: split text blocks at $$ boundaries
        new_blocks: list[dict] = []
        math_count = 0
        for b in blocks:
            if b.get("type") == "text":
                parts = _split_math(b)
                new_blocks.extend(parts)
                math_count += sum(1 for p in parts if p["type"] == "math")
            else:
                new_blocks.append(b)

        if args.dry_run:
            print(f"  [{lid}] would extract {math_count} math block(s) "
                  f"({len(blocks)} → {len(new_blocks)} blocks)")
            # Show each extracted equation
            for b in new_blocks:
                if b["type"] == "math":
                    latex = b["data"]["latex"]
                    print(f"    ∑  {latex[:70]!r}")
            counts["converted"] += 1
            continue

        ok = _patch_blocks(lid, new_blocks)
        if not ok:
            print(f"  [{lid}] ERROR saving blocks")
            counts["error"] += 1
            continue

        print(f"  [{lid}] {math_count} math block(s) extracted "
              f"({len(blocks)} → {len(new_blocks)} blocks)")
        counts["converted"] += 1
        log[lid] = {
            "mathBlocks": math_count,
            "blocksBefore": len(blocks),
            "blocksAfter": len(new_blocks),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        time.sleep(0.3)

    print(f"\n=== Math Extraction {'Dry Run ' if args.dry_run else ''}Complete ===")
    print(f"  Converted : {counts['converted']}")
    print(f"  Skipped   : {counts['skipped']} (no display math found)")
    print(f"  Errors    : {counts['error']}")

    if not args.dry_run and counts["converted"] > 0:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        print(f"\nLog saved to scripts/qc_math_log.json")
        print(f"Next step: python scripts/qc_auto_convert.py --save")

    if args.dry_run:
        print(f"\nRun without --dry-run to apply.")


if __name__ == "__main__":
    main()
