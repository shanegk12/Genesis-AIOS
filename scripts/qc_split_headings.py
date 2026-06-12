"""
Genesis K-12 QC — Split Headings into Separate Text Blocks

Any text block that contains an h2/h3/h4 heading mixed with body content
gets split so each heading is its own block and body text follows separately.

Before:
  text block: <h2>Lesson Overview</h2><p>Welcome back...</p><p>Today...</p>

After:
  text block: <h2>Lesson Overview</h2>
  text block: <p>Welcome back...</p><p>Today...</p>

This ensures:
  - Heading blocks render in Playfair Display, body blocks in Lato
  - Each block has its own QC status and spacing control
  - No mixed-purpose blocks

Usage:
  python scripts/qc_split_headings.py --dry-run
  python scripts/qc_split_headings.py --save
  python scripts/qc_split_headings.py --lesson-id C-025 --save
  python scripts/qc_split_headings.py --course C --save
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

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
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

# Only split on h2 and h3 — h4 is used as vocab term markers, leave alone
HEADING_RE = re.compile(r'(?=<h[23][\s>])', re.IGNORECASE)
HEADING_TAG_RE = re.compile(r'^(<h[23][^>]*>.*?</h[23]>)', re.IGNORECASE | re.DOTALL)


def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def split_block(block: dict) -> list[dict]:
    """
    Split a text block on h2/h3 headings.
    Returns a list of replacement blocks (1 item = no change needed).
    """
    html = block.get("data", {}).get("html", "").strip()
    if not html:
        return [block]

    # Only split if there's actually a heading AND other content
    has_heading = bool(re.search(r'<h[23][\s>]', html, re.IGNORECASE))
    if not has_heading:
        return [block]

    # Check if it's JUST a heading (nothing to split)
    stripped = re.sub(r'<h[23][^>]*>.*?</h[23]>', '', html, flags=re.IGNORECASE | re.DOTALL).strip()
    if not stripped:
        return [block]  # Already just a heading, nothing to do

    meta = block.get("meta", {"spacing": "md", "qcStatus": "pending"})

    # Split at each h2/h3 opening tag
    segments = HEADING_RE.split(html)
    result_blocks = []

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        m = HEADING_TAG_RE.match(seg)
        if m:
            heading_html = m.group(1).strip()
            rest = seg[len(heading_html):].strip()

            # Heading block (larger spacing above, tight below)
            result_blocks.append({
                "id": gen_id(),
                "type": "text",
                "data": {"html": heading_html},
                "meta": {"spacing": "lg", "qcStatus": meta.get("qcStatus", "pending")},
            })

            # Body content that follows this heading
            if rest:
                result_blocks.append({
                    "id": gen_id(),
                    "type": "text",
                    "data": {"html": rest},
                    "meta": {"spacing": "sm", "qcStatus": meta.get("qcStatus", "pending")},
                })
        else:
            # Content before the first heading (intro text)
            result_blocks.append({
                "id": gen_id(),
                "type": "text",
                "data": {"html": seg},
                "meta": meta,
            })

    return result_blocks if len(result_blocks) > 1 else [block]


def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [ERR] {lesson_id}: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list) -> bool:
    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={
            "Authorization": f"Bearer {PLATFORM_KEY}",
            "Content-Type": "application/json",
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  [PATCH ERR] {lesson_id}: {e}")
        return False


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lessons", data) if isinstance(data, dict) else data


def process_lesson(lesson_id: str, dry_run: bool) -> dict:
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return {"lessonId": lesson_id, "status": "fetch_error"}

    title = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    new_blocks = []
    splits = 0
    offset = 0

    for i, block in enumerate(blocks):
        if block.get("type") != "text":
            new_blocks.append(block)
            continue

        replacements = split_block(block)
        if len(replacements) > 1:
            splits += len(replacements) - 1
            if not dry_run:
                new_blocks.extend(replacements)
            else:
                new_blocks.append(block)
                html = block.get("data", {}).get("html", "")
                headings = re.findall(r'<h[23][^>]*>(.*?)</h[23]>', html, re.IGNORECASE | re.DOTALL)
                print(f"    Block {i}: split into {len(replacements)} blocks — headings: {[h[:40] for h in headings]}")
        else:
            new_blocks.append(block)

    if splits == 0:
        return {"lessonId": lesson_id, "status": "clean"}

    if not dry_run:
        ok = patch_lesson(lesson_id, new_blocks)
        status = "split" if ok else "patch_failed"
        print(f"  {lesson_id} — {title}: {splits} split(s) → {status}")
    else:
        print(f"  {lesson_id} — {title}: would split {splits} heading(s)")
        status = "would_split"

    return {"lessonId": lesson_id, "title": title, "status": status, "splits": splits}


def main():
    parser = argparse.ArgumentParser(description="Split headings into separate text blocks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--lesson-id", help="Single lesson")
    parser.add_argument("--course",    choices=["C", "M"])
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run")
    dry_run = not args.save

    if args.lesson_id:
        lessons = [args.lesson_id]
    elif args.course:
        manifest = load_manifest()
        lessons = [l["id"] for l in manifest if l["id"].startswith(args.course + "-")]
    else:
        manifest = load_manifest()
        lessons = [l["id"] for l in manifest]

    print(f"\nQC Split Headings — {len(lessons)} lessons {'(DRY RUN)' if dry_run else '(SAVING)'}")
    print("=" * 60)

    results = []
    split_count = clean = errors = 0

    for lid in lessons:
        r = process_lesson(lid, dry_run)
        results.append(r)
        s = r.get("status")
        if s in ("split", "would_split"):
            split_count += 1
        elif s == "clean":
            clean += 1
        else:
            errors += 1
        time.sleep(0.2)

    print(f"\n{'='*60}")
    action = "Would split" if dry_run else "Split"
    print(f"Done. {clean} clean, {split_count} {action.lower()}, {errors} errors.")
    if dry_run and split_count > 0:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
