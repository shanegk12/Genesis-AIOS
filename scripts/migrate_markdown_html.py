"""
Genesis K-12 — Markdown-in-HTML Migration

Fixes lessons stuck in 1-block state where the pipeline produced markdown
headings inside <p> tags (e.g. <p>## Lesson Overview</p>).

Steps per lesson:
  1. Detect: 1 block, no contentSource, markdown artifacts present
  2. Preprocess: convert markdown → proper HTML (<h2>, <strong>, etc.)
  3. POST parse-html → re-splits into proper multi-block structure
  4. PATCH contentSource: "platform" → locks lesson so pipeline can't overwrite

Usage:
  python scripts/migrate_markdown_html.py --dry-run         # preview only
  python scripts/migrate_markdown_html.py                   # migrate all
  python scripts/migrate_markdown_html.py --lesson-id C-025 # single lesson
  python scripts/migrate_markdown_html.py --course C        # Creationeering only
  python scripts/migrate_markdown_html.py --course M        # Mousetrap only
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY  = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
LOG_PATH      = os.path.join(os.path.dirname(__file__), "migrate_markdown_log.json")

# Known section headings that appear as plain <p> tags in M-course lessons
KNOWN_H2_HEADINGS = {
    "lesson overview", "learning objectives", "key vocabulary",
    "summary", "conclusion", "sources", "engineering journal task",
    "technical documentation requirements", "faith connection",
    "biblical understanding", "check for understanding", "review",
    "the beginning", "introduction", "materials needed",
}

# Preamble patterns the pipeline sometimes prepends — strip these
PREAMBLE_RE = re.compile(
    r'<p>(?:Here is (?:a |your )?lesson(?: for[^<]*?)?'
    r'|This lesson (?:is )?for[^<]*?'
    r'|Welcome to[^<]*?Genesis K-12[^<]*?'
    r')</p>\s*',
    re.IGNORECASE,
)


def _needs_migration(blocks: list, content_source: str | None) -> bool:
    """Return True if the lesson is in the broken 1-block markdown state."""
    if content_source == "platform":
        return False
    if len(blocks) != 1:
        return False
    html = blocks[0].get("data", {}).get("html", "") or ""
    # Has markdown heading artifacts or plain-paragraph heading structure
    return bool(
        re.search(r'<p>#{1,3}\s', html) or           # ## or ### prefix
        re.search(r'<p>\d+\.\s+[A-Z]', html) or      # 1. Section Name
        re.search(r'\*\*[^*]+\*\*', html) or          # **bold**
        re.search(r'<p>Lesson Overview</p>', html) or  # plain known headings
        re.search(r'<p>Learning Objectives</p>', html)
    )


def preprocess_html(html: str) -> str:
    """Convert markdown-in-HTML artifacts to proper HTML tags."""

    # ── Strip pipeline preamble lines ────────────────────────────────────────
    html = PREAMBLE_RE.sub("", html)

    # ── Convert ## / ### heading paragraphs ──────────────────────────────────
    # <p>### Subheading</p> before <p>## Heading</p> so the longer match runs first
    html = re.sub(r'<p>#{3,}\s+(.+?)</p>', r'<h3>\1</h3>', html)
    html = re.sub(r'<p>#{2}\s+(.+?)</p>',  r'<h2>\1</h2>', html)
    html = re.sub(r'<p>#\s+(.+?)</p>',     r'<h2>\1</h2>', html)

    # ── Convert numbered section headings: <p>1. Section Name</p> ────────────
    # Only convert if: starts with capital, ≤ 70 chars, does NOT end with colon
    # (colon-ending = intro line, not a heading)
    def _num_heading(m: re.Match) -> str:
        text = m.group(1).strip()
        # Skip: too long, colon-ending intros, period-ending sentences, or dollar amounts
        if text.endswith(":") or len(text) > 70 or text.endswith(".") or "$" in text:
            return m.group(0)
        return f"<h2>{text}</h2>"

    html = re.sub(r'<p>\d+\.\s+([A-Z][^<]{2,}?)</p>', _num_heading, html)

    # ── Convert known plain section heading paragraphs ────────────────────────
    def _known_heading(m: re.Match) -> str:
        text = m.group(1)
        if text.lower().strip() in KNOWN_H2_HEADINGS:
            return f"<h2>{text}</h2>"
        return m.group(0)

    html = re.sub(r'<p>([^<]{3,60})</p>', _known_heading, html)

    # ── Convert inline markdown bold / italic ─────────────────────────────────
    # Bold first (double asterisk), then italic (single)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<em>\1</em>', html)

    return html.strip()


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


def _parse_html(lesson_id: str, html: str) -> int | None:
    """POST parse-html action. Returns block count on success, None on error."""
    payload = json.dumps({"action": "parse-html", "html": html}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("blockCount") if result.get("ok") else None
    except Exception as e:
        print(f"    parse-html error: {e}")
        return None


def _lock_content_source(lesson_id: str) -> bool:
    """PATCH contentSource: platform so pipeline won't overwrite."""
    payload = json.dumps({"contentSource": "platform"}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"    lock error: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lesson-id", help="Migrate a single lesson")
    parser.add_argument("--course", choices=["C", "M"])
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview preprocessing output without saving")
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
    print(f"\nMarkdown-HTML Migration [{mode}]: checking {len(lessons)} lessons\n")

    log = {}
    counts = {"migrated": 0, "skipped": 0, "no_change": 0, "error": 0}

    for lesson in lessons:
        lid = lesson["id"]
        data = _fetch_lesson(lid)
        if not data:
            counts["error"] += 1
            continue

        blocks = data.get("blocks", [])
        cs     = data.get("contentSource")

        if not _needs_migration(blocks, cs):
            counts["skipped"] += 1
            continue

        original_html = blocks[0].get("data", {}).get("html", "") if blocks else ""
        processed_html = preprocess_html(original_html)

        if processed_html == original_html:
            print(f"  [{lid}] no preprocessing changes")
            counts["no_change"] += 1
            continue

        if args.dry_run:
            # Show a preview of what would change
            orig_lines = original_html.split("\n")
            proc_lines = processed_html.split("\n")
            changed = [(o, p) for o, p in zip(orig_lines, proc_lines) if o != p]
            print(f"  [{lid}] {len(changed)} line(s) would change:")
            for orig, proc in changed[:4]:
                print(f"    - {orig[:80]!r}")
                print(f"    + {proc[:80]!r}")
            if len(changed) > 4:
                print(f"    ... ({len(changed) - 4} more)")
            counts["migrated"] += 1
            continue

        # Live: re-parse HTML → blocks
        block_count = _parse_html(lid, processed_html)
        if block_count is None:
            print(f"  [{lid}] ERROR during parse-html")
            counts["error"] += 1
            continue

        # Lock so pipeline won't overwrite
        locked = _lock_content_source(lid)

        print(f"  [{lid}] {block_count} blocks (was 1) {'✓ locked' if locked else '⚠ lock failed'}")
        counts["migrated"] += 1
        log[lid] = {
            "blockCount": block_count,
            "locked": locked,
            "at": datetime.now(timezone.utc).isoformat(),
        }

        time.sleep(0.3)

    print(f"\n=== Migration {'Dry Run ' if args.dry_run else ''}Complete ===")
    print(f"  Migrated    : {counts['migrated']}")
    print(f"  No change   : {counts['no_change']}")
    print(f"  Skipped     : {counts['skipped']} (already multi-block or platform-locked)")
    print(f"  Errors      : {counts['error']}")

    if not args.dry_run and counts["migrated"] > 0:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
        print(f"\nNext step: python scripts/qc_auto_convert.py --save")

    if args.dry_run:
        print(f"\nRun without --dry-run to apply.")


if __name__ == "__main__":
    main()
