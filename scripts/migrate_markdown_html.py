"""
Genesis K-12 — Markdown-in-HTML → Block[] Migration Script

Detects lessons stuck in the "1-block markdown-in-HTML" state and migrates
them to properly typed Block[] entries, then PATCHes the live platform API.

Usage:
  python scripts/migrate_markdown_html.py --dry-run            # show changes, no writes
  python scripts/migrate_markdown_html.py --save               # patch all matching lessons
  python scripts/migrate_markdown_html.py --lesson-id C-005    # single lesson, dry-run
  python scripts/migrate_markdown_html.py --lesson-id C-005 --save
  python scripts/migrate_markdown_html.py --limit 10 --save    # cap for testing
"""

import argparse
import json
import re
import sys
import time
import uuid
import urllib.request
import urllib.error
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
def _get_platform_key() -> str:
    """Load platform API key from env or .env - never hardcode in source."""
    import os as _os
    from pathlib import Path as _Path
    k = (_os.environ.get('PIPELINE_KEY')
         or _os.environ.get('PLATFORM_KEY')
         or _os.environ.get('ADMIN_API_KEY', ''))
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=', 'ADMIN_API_KEY=')):
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


API_KEY  = _get_platform_key()
LOG_PATH = Path(r"D:\AIOS\scripts\migrate_markdown_log.json")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# Scripture book names used to detect biblical callout variant
SCRIPTURE_BOOKS = {
    "genesis", "exodus", "leviticus", "numbers", "deuteronomy",
    "joshua", "judges", "ruth", "samuel", "kings", "chronicles",
    "ezra", "nehemiah", "esther", "job", "psalms", "psalm",
    "proverbs", "ecclesiastes", "isaiah", "jeremiah", "lamentations",
    "ezekiel", "daniel", "hosea", "joel", "amos", "obadiah",
    "jonah", "micah", "nahum", "habakkuk", "zephaniah", "haggai",
    "zechariah", "malachi", "matthew", "mark", "luke", "john",
    "acts", "romans", "corinthians", "galatians", "ephesians",
    "philippians", "colossians", "thessalonians", "timothy", "titus",
    "philemon", "hebrews", "james", "peter", "jude", "revelation",
}

CHAPTER_VERSE_RE = re.compile(r"\d+:\d+")

# Markdown indicators used for detection
MARKDOWN_INDICATORS_RE = re.compile(
    r"(^#{1,6}\s)"          # ATX headings
    r"|(^\*\*[^*])"         # bold at line start
    r"|(\*\*[^*]+\*\*)"     # bold anywhere
    r"|(^-\s)"              # bullet list
    r"|(^---\s*$)"          # horizontal rule
    r"|(\$\$)"              # math
    r"|(^\s*>\s)",          # blockquote
    re.MULTILINE,
)


# ── API helpers ───────────────────────────────────────────────────────────────

def api_request(method: str, path: str, body=None):
    """Make an authenticated API request. Returns parsed JSON."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {body_text}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error {method} {path}: {e.reason}") from e


MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

def get_all_lessons():
    """Load lesson IDs from manifest, fetch each individually."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}. Run the pipeline to generate it.")
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("lessons", data) if isinstance(data, dict) else data
    lesson_ids = [e["id"] for e in entries if "id" in e]
    lessons = []
    for lid in lesson_ids:
        try:
            lesson = api_request("GET", f"/api/admin/lessons/{lid}")
            if lesson:
                lessons.append(lesson)
        except RuntimeError as e:
            print(f"  [WARN] Could not fetch {lid}: {e}")
        time.sleep(0.05)
    return lessons


def get_lesson(lesson_id: str):
    return api_request("GET", f"/api/admin/lessons/{lesson_id}")


def patch_lesson(lesson_id: str, payload: dict):
    return api_request("PATCH", f"/api/admin/lessons/{lesson_id}", payload)


# ── Detection ─────────────────────────────────────────────────────────────────

def has_markdown(html: str) -> bool:
    """Return True if the string contains Markdown indicators."""
    return bool(MARKDOWN_INDICATORS_RE.search(html))


def classify_lesson(lesson: dict) -> str:
    """
    Return one of:
      'full'    -- needs full Markdown parse-and-replace
      'source'  -- already clean HTML, only contentSource patch needed
      'skip'    -- already done or not a match
    """
    blocks = lesson.get("blocks") or []
    content_source = lesson.get("contentSource")

    if content_source == "platform":
        return "skip"

    if len(blocks) == 1 and blocks[0].get("type") == "text":
        raw = blocks[0].get("data", {}).get("html", "")
        if has_markdown(raw):
            return "full"
        # Single clean block, no markdown -- just fix contentSource
        return "source"

    if len(blocks) == 1 and content_source in (None, ""):
        # Single block of any type, missing contentSource
        return "source"

    return "skip"


# ── Block factory helpers ─────────────────────────────────────────────────────

def new_id() -> str:
    return str(uuid.uuid4())


def make_meta() -> dict:
    return {"spacing": "md", "qcStatus": "pending"}


def make_text(html: str) -> dict:
    return {
        "id": new_id(),
        "type": "text",
        "data": {"html": html.strip()},
        "meta": make_meta(),
    }


def make_callout(variant: str, html: str) -> dict:
    return {
        "id": new_id(),
        "type": "callout",
        "data": {"variant": variant, "html": html.strip()},
        "meta": make_meta(),
    }


def make_vocab(items: list) -> dict:
    return {
        "id": new_id(),
        "type": "vocab",
        "data": {"columns": 2, "items": items},
        "meta": make_meta(),
    }


def make_divider() -> dict:
    return {
        "id": new_id(),
        "type": "divider",
        "data": {"style": "solid"},
        "meta": make_meta(),
    }


def make_math(latex: str) -> dict:
    return {
        "id": new_id(),
        "type": "math",
        "data": {"latex": latex.strip(), "display": True},
        "meta": make_meta(),
    }


# ── Inline Markdown → HTML ────────────────────────────────────────────────────

def inline_md(text: str) -> str:
    """Convert inline Markdown to HTML (bold, italic, inline code)."""
    # Bold+italic before bold before italic to avoid partial matches
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


# ── Callout variant detection ─────────────────────────────────────────────────

def detect_callout_variant(text: str) -> str:
    lower = text.lower()
    if CHAPTER_VERSE_RE.search(text):
        return "biblical"
    for book in SCRIPTURE_BOOKS:
        if book in lower:
            return "biblical"
    if any(w in lower for w in ("warning", "caution", "danger")):
        return "warning"
    if any(w in lower for w in ("tip", "hint", "pro tip")):
        return "tip"
    return "info"


# ── Vocab pattern detection ───────────────────────────────────────────────────

# **Term** -- definition  OR  **Term** - definition  OR  **Term**: definition
VOCAB_BOLD_RE   = re.compile(r"^\*\*(.+?)\*\*\s*[—\-:]\s*(.+)$")
# Term: definition  (capitalized, no bold, short key)
VOCAB_SIMPLE_RE = re.compile(r"^([A-Z][^:]{1,50}):\s+(.{10,})$")


def try_parse_vocab(line: str):
    """Return (term, definition) tuple or None."""
    m = VOCAB_BOLD_RE.match(line.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = VOCAB_SIMPLE_RE.match(line.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None


# ── Buffer flush helpers ──────────────────────────────────────────────────────

def flush_text(buf: list, blocks: list):
    """Flush accumulated HTML buffer into a text block (if non-empty)."""
    html = "".join(buf).strip()
    if html:
        blocks.append(make_text(html))
    buf.clear()


def flush_list(items: list, buf: list):
    """Flush accumulated bullet items into buf as a <ul> element."""
    if items:
        inner = "".join(f"<li>{inline_md(item)}</li>" for item in items)
        buf.append(f"<ul>{inner}</ul>")
        items.clear()


def flush_vocab(vocab_items: list, blocks: list, text_buf: list):
    """Flush accumulated vocab items into a vocab block."""
    if vocab_items:
        flush_text(text_buf, blocks)
        blocks.append(make_vocab([{"term": t, "definition": d} for t, d in vocab_items]))
        vocab_items.clear()


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_markdown_to_blocks(raw: str) -> list:
    """
    Parse a raw Markdown / mixed-HTML string into a list of typed Block dicts.

    Splitting strategy:
      - Each ## heading starts a new text block (after flushing the previous one)
      - Bullet/numbered lists are accumulated into <ul>/<ol> inside the current block
      - Blockquotes and Note/Tip/Warning lines become callout blocks
      - --- becomes a divider block
      - $$ or \\[ blocks become math blocks
      - **Term** - definition and Term: definition patterns become vocab blocks
      - Everything else is a paragraph in the current text block
    """
    blocks: list     = []
    text_buf: list   = []   # accumulates HTML fragments for current text block
    list_items: list = []   # pending bullet-list items
    vocab_items: list = []  # pending (term, definition) pairs

    lines = raw.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── Empty line: skip ──────────────────────────────────────────────────
        if not stripped:
            i += 1
            continue

        # ── Math block: $$...$$ ───────────────────────────────────────────────
        if stripped.startswith("$$"):
            flush_list(list_items, text_buf)
            flush_vocab(vocab_items, blocks, text_buf)
            flush_text(text_buf, blocks)
            # Single-line: $$latex$$
            if stripped.endswith("$$") and len(stripped) > 4:
                blocks.append(make_math(stripped[2:-2]))
            else:
                math_lines = [stripped[2:]]
                i += 1
                while i < len(lines):
                    l = lines[i].strip()
                    if l.endswith("$$"):
                        math_lines.append(l[:-2])
                        break
                    math_lines.append(l)
                    i += 1
                blocks.append(make_math("\n".join(math_lines)))
            i += 1
            continue

        # ── Math block: \[...\] ───────────────────────────────────────────────
        if stripped.startswith(r"\["):
            flush_list(list_items, text_buf)
            flush_vocab(vocab_items, blocks, text_buf)
            flush_text(text_buf, blocks)
            if stripped.endswith(r"\]") and len(stripped) > 4:
                blocks.append(make_math(stripped[2:-2]))
            else:
                math_lines = [stripped[2:]]
                i += 1
                while i < len(lines):
                    l = lines[i].strip()
                    if l.endswith(r"\]"):
                        math_lines.append(l[:-2])
                        break
                    math_lines.append(l)
                    i += 1
                blocks.append(make_math("\n".join(math_lines)))
            i += 1
            continue

        # ── Horizontal rule: --- ──────────────────────────────────────────────
        if re.match(r"^-{3,}\s*$", stripped):
            flush_list(list_items, text_buf)
            flush_vocab(vocab_items, blocks, text_buf)
            flush_text(text_buf, blocks)
            blocks.append(make_divider())
            i += 1
            continue

        # ── ATX Heading (# or ##) — starts a new text block ──────────────────
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_list(list_items, text_buf)
            flush_vocab(vocab_items, blocks, text_buf)
            flush_text(text_buf, blocks)
            level = min(len(heading_match.group(1)), 4)
            text_buf.append(f"<h{level}>{inline_md(heading_match.group(2))}</h{level}>")
            i += 1
            continue

        # ── Blockquote lines → callout ────────────────────────────────────────
        if stripped.startswith(">"):
            flush_list(list_items, text_buf)
            flush_vocab(vocab_items, blocks, text_buf)
            flush_text(text_buf, blocks)
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            quote_text = " ".join(quote_lines)
            variant = detect_callout_variant(quote_text)
            blocks.append(make_callout(variant, f"<p>{inline_md(quote_text)}</p>"))
            continue

        # ── Inline Note/Tip/Warning prefix → callout ──────────────────────────
        callout_match = re.match(
            r"^(Note|Tip|Warning|Caution):\s+(.+)$", stripped, re.IGNORECASE
        )
        if callout_match:
            flush_list(list_items, text_buf)
            flush_vocab(vocab_items, blocks, text_buf)
            flush_text(text_buf, blocks)
            kw = callout_match.group(1).lower()
            content = callout_match.group(2)
            variant_map = {
                "note": "info", "tip": "tip", "warning": "warning", "caution": "warning"
            }
            blocks.append(
                make_callout(variant_map[kw], f"<p>{inline_md(content)}</p>")
            )
            i += 1
            continue

        # ── Bullet list item ──────────────────────────────────────────────────
        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet_match:
            if vocab_items:
                flush_vocab(vocab_items, blocks, text_buf)
            list_items.append(bullet_match.group(1))
            i += 1
            continue

        # ── Numbered list: collect consecutive items as <ol> ─────────────────
        num_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if num_match:
            flush_list(list_items, text_buf)
            if vocab_items:
                flush_vocab(vocab_items, blocks, text_buf)
            ol_items = [num_match.group(1)]
            i += 1
            while i < len(lines):
                nm2 = re.match(r"^\d+\.\s+(.+)$", lines[i].strip())
                if nm2:
                    ol_items.append(nm2.group(1))
                    i += 1
                else:
                    break
            inner = "".join(f"<li>{inline_md(it)}</li>" for it in ol_items)
            text_buf.append(f"<ol>{inner}</ol>")
            continue

        # ── Vocab pair ────────────────────────────────────────────────────────
        vocab_pair = try_parse_vocab(stripped)
        if vocab_pair:
            flush_list(list_items, text_buf)
            vocab_items.append((vocab_pair[0], inline_md(vocab_pair[1])))
            i += 1
            continue

        # ── Plain text / pass-through HTML ───────────────────────────────────
        flush_list(list_items, text_buf)
        if vocab_items:
            flush_vocab(vocab_items, blocks, text_buf)
        # If the line already looks like an HTML tag, pass through unmodified
        if stripped.startswith("<") and not stripped.startswith("<strong") \
                and not stripped.startswith("<em"):
            text_buf.append(stripped)
        else:
            text_buf.append(f"<p>{inline_md(stripped)}</p>")
        i += 1

    # ── Flush remaining buffers ───────────────────────────────────────────────
    flush_list(list_items, text_buf)
    if vocab_items:
        flush_vocab(vocab_items, blocks, text_buf)
    flush_text(text_buf, blocks)

    return blocks


# ── Utilities ─────────────────────────────────────────────────────────────────

def type_summary(blocks: list) -> str:
    counts = Counter(b.get("type", "?") for b in blocks)
    return ", ".join(f"{t}x{n}" for t, n in sorted(counts.items()))


# ── Main ──────────────────────────────────────────────────────────────────────

def run(args):
    dry_run   = not args.save
    limit     = args.limit
    target_id = args.lesson_id

    mode_label = "[DRY RUN] " if dry_run else ""
    print(f"{mode_label}Fetching lessons from platform...")

    if target_id:
        try:
            lessons = [get_lesson(target_id)]
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            sys.exit(1)
    else:
        try:
            lessons = get_all_lessons()
        except RuntimeError as e:
            print(f"  ERROR: {e}")
            sys.exit(1)

    print(f"  {len(lessons)} lesson(s) fetched.")

    log_entries   = []
    n_full        = 0
    n_source_only = 0
    n_skipped     = 0
    n_errors      = 0

    for lesson in lessons:
        if limit is not None and n_full >= limit:
            print(f"\n[LIMIT] Reached --limit {limit}, stopping.")
            break

        lesson_id = lesson.get("id") or lesson.get("lessonId") or "?"
        title     = lesson.get("title") or "(no title)"
        blocks_before = lesson.get("blocks") or []
        action = classify_lesson(lesson)

        # ── Skip ─────────────────────────────────────────────────────────────
        if action == "skip":
            n_skipped += 1
            continue

        # ── Source-only patch ─────────────────────────────────────────────────
        if action == "source":
            print(f"\n  [{lesson_id}] {title}")
            print(f"    contentSource-only patch "
                  f"(clean HTML, {len(blocks_before)} block(s))")
            entry = {
                "lessonId":    lesson_id,
                "title":       title,
                "action":      "source_only",
                "blocksBefore": len(blocks_before),
                "blocksAfter":  len(blocks_before),
                "dryRun":      dry_run,
                "timestamp":   datetime.now(timezone.utc).isoformat(),
            }
            log_entries.append(entry)
            if not dry_run:
                try:
                    patch_lesson(lesson_id, {"contentSource": "platform"})
                    time.sleep(0.5)
                except RuntimeError as e:
                    print(f"    ERROR: {e}")
                    n_errors += 1
                    continue
            n_source_only += 1
            continue

        # ── Full migration ────────────────────────────────────────────────────
        raw_html = blocks_before[0].get("data", {}).get("html", "") \
                   if blocks_before else ""
        try:
            new_blocks = parse_markdown_to_blocks(raw_html)
        except Exception as e:
            print(f"\n  [{lesson_id}] PARSE ERROR: {e}")
            n_errors += 1
            continue

        print(f"\n  [{lesson_id}] {title}")
        print(f"    Before: {len(blocks_before)} block(s)")
        print(f"    After:  {len(new_blocks)} block(s)  [{type_summary(new_blocks)}]")

        entry = {
            "lessonId":    lesson_id,
            "title":       title,
            "action":      "full_migration",
            "blocksBefore": len(blocks_before),
            "blocksAfter":  len(new_blocks),
            "blockTypes":   type_summary(new_blocks),
            "dryRun":      dry_run,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }
        log_entries.append(entry)

        if not dry_run:
            try:
                patch_lesson(lesson_id, {
                    "blocks": new_blocks,
                    "contentSource": "platform",
                })
                time.sleep(0.5)
            except RuntimeError as e:
                print(f"    ERROR: {e}")
                n_errors += 1
                continue

        n_full += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Done{' (dry run -- nothing written)' if dry_run else ''}.")
    print(f"  Full migrations    : {n_full}")
    print(f"  Source-only patches: {n_source_only}")
    print(f"  Skipped (platform) : {n_skipped}")
    print(f"  Errors             : {n_errors}")

    # ── Write / append log ────────────────────────────────────────────────────
    existing = []
    if LOG_PATH.exists():
        try:
            existing = json.loads(LOG_PATH.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    combined = existing + log_entries
    LOG_PATH.write_text(
        json.dumps(combined, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Log: {LOG_PATH}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate 1-block markdown-in-HTML lessons to typed Block[]."
    )
    # --dry-run and --save are mutually exclusive; default is dry-run
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", dest="save", action="store_false",
        help="Preview only (default)",
    )
    mode.add_argument(
        "--save", dest="save", action="store_true",
        help="PATCH lessons on the platform",
    )
    parser.set_defaults(save=False)

    parser.add_argument("--lesson-id", metavar="ID",
                        help="Migrate a single lesson by ID")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="Stop after N full migrations (for testing)")

    args = parser.parse_args()

    # Safety: if --save is not explicitly in argv, treat as dry-run
    if "--save" not in sys.argv:
        args.save = False

    run(args)


if __name__ == "__main__":
    main()
