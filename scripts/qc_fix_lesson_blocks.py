"""
qc_fix_lesson_blocks.py

In-place repair of broken lesson block structure.

Problems fixed:
  1. h2/h3 heading-only blocks — merges the heading into the following content block
  2. Template placeholder paragraphs — removes unfilled Gemini template labels
     like "<strong>Plain:</strong> language explanation"
  3. Empty / whitespace-only text blocks — pruned

Non-text blocks (embed, image, vocab, callout, divider, tabs, etc.) are NEVER
touched — they stay exactly where they are.

Run:
  python scripts/qc_fix_lesson_blocks.py --dry-run            # preview all 134
  python scripts/qc_fix_lesson_blocks.py --save               # apply fixes
  python scripts/qc_fix_lesson_blocks.py --lesson C-040 --dry-run
  python scripts/qc_fix_lesson_blocks.py --lesson C-040 --save
"""

import argparse, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
API_KEY      = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
AUDIT_PATH   = Path(__file__).parent / "lesson_quality_audit.json"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# ── HTML helpers ──────────────────────────────────────────────────────────────

STRIP_RE = re.compile(r"<[^>]+>")

def strip_tags(html: str) -> str:
    return STRIP_RE.sub("", html or "").strip()


# Matches a text block whose ENTIRE content is a single h2 or h3 tag
HEADING_ONLY_RE = re.compile(r"^\s*<h[23][^>]*>[^<]*</h[23]>\s*$", re.IGNORECASE)

# Matches a text block that contains only whitespace after tag stripping
def is_empty_text(html: str) -> bool:
    return not strip_tags(html)


# Template placeholder patterns — these are unfilled Gemini template instructions
# that leaked into lesson content. We remove the *entire* <p>...</p> element that
# contains them, not the whole block.
PLACEHOLDER_P_RE = re.compile(
    r"<p[^>]*>"
    r"(?:"
    # "Term: Definition" (header row of vocab table that wasn't cleaned up)
    r"(?:<strong>\s*Term\s*:\s*</strong>\s*Definition)"
    r"|(?:\s*Term\s*:\s*Definition\s*)"
    # "Plain: language explanation" or "Plain language explanation" variants
    r"|(?:<strong>\s*Plain\s*:?\s*</strong>[^<]*)"
    r"|(?:\s*Plain\s*:\s*language explanation\s*)"
    r"|(?:\s*Plain\s*language explanation\s*)"
    # Bare "Plain" paragraph (split-line placeholder "Plain\nlanguage explanation")
    r"|(?:\s*Plain\s*)"
    # "language explanation" continuation line from split placeholder
    r"|(?:\s*language explanation\s*)"
    # "Engineering analogy:" placeholder
    r"|(?:<strong>\s*Engineering analogy[^<]*</strong>\s*)"
    r"|(?:\s*Engineering analogy\s*:?\s*(?:with|provide|concrete)?\s*(?:imagery)?\s*)"
    # "Faith or stewardship connection:" placeholder
    r"|(?:<strong>\s*Faith or stewardship[^<]*</strong>\s*)"
    r"|(?:\s*Faith or stewardship connection\s*:?\s*)"
    # "Multiscale Modeling connection" placeholder when it's a bare label
    r"|(?:\s*Multiscale Modeling connection\s*:?\s*)"
    # "OCV application" placeholder
    r"|(?:\s*OCV application\s*:?\s*(?:where relevant)?\s*)"
    # Generic "[IMAGE NEEDED: ...]" placeholder
    r"|(?:\s*\[IMAGE NEEDED[^\]]*\]\s*)"
    r")"
    r"[^<]*</p>",
    re.IGNORECASE | re.DOTALL,
)

# Short label-only blocks to merge even if not wrapped in h2/h3
# (e.g. <p>Part 1: What is Procurement, Really?</p> — 36 chars, starts with Part N:)
SHORT_LABEL_RE = re.compile(
    r"^\s*<p[^>]*>\s*(?:Part\s+\d+|Section\s+\d+)[^<]{0,80}</p>\s*$",
    re.IGNORECASE,
)


def clean_placeholders(html: str) -> str:
    """Remove template placeholder <p> elements from a block's HTML."""
    cleaned = PLACEHOLDER_P_RE.sub("", html)
    # Collapse multiple spaces/newlines that result from deletions
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# ── Block fixers ──────────────────────────────────────────────────────────────

def fix_blocks(blocks: list) -> tuple[list, dict]:
    """
    Returns (fixed_blocks, stats) where stats tracks what was changed.
    Never mutates input; returns new list.
    """
    stats = {"merged": 0, "placeholder_cleaned": 0, "empty_removed": 0}
    result = []
    i = 0

    while i < len(blocks):
        block = blocks[i]

        # ── Non-text blocks pass through unchanged ────────────────────────────
        if block.get("type") != "text":
            result.append(block)
            i += 1
            continue

        html = block.get("data", {}).get("html", "")

        # ── Remove empty text blocks ──────────────────────────────────────────
        if is_empty_text(html):
            stats["empty_removed"] += 1
            i += 1
            continue

        # ── Merge heading-only or short-label block into following content ──────
        is_heading = HEADING_ONLY_RE.match(html)
        is_short_label = SHORT_LABEL_RE.match(html)
        if is_heading or is_short_label:
            # Look ahead for the next text block to merge with
            j = i + 1
            while j < len(blocks) and blocks[j].get("type") != "text":
                j += 1

            if j < len(blocks):
                next_html = blocks[j].get("data", {}).get("html", "")
                # Merge if next block is not itself heading-only (not cascade-heading)
                if not HEADING_ONLY_RE.match(next_html) and not is_empty_text(next_html):
                    # Pass through all non-text blocks between i and j unchanged
                    for k in range(i + 1, j):
                        result.append(blocks[k])
                    # Emit the merged block (heading + content)
                    merged_html = html.rstrip() + "\n" + next_html.lstrip()
                    merged_block = {
                        **blocks[j],
                        "data": {**blocks[j].get("data", {}), "html": merged_html},
                    }
                    result.append(merged_block)
                    stats["merged"] += 1
                    i = j + 1
                    continue
            # No suitable following text block — keep as-is
            result.append(block)
            i += 1
            continue

        # ── Strip placeholder paragraphs from content blocks ─────────────────
        cleaned_html = clean_placeholders(html)
        if cleaned_html != html:
            stats["placeholder_cleaned"] += 1
            if is_empty_text(cleaned_html):
                # The whole block was placeholder
                stats["empty_removed"] += 1
                i += 1
                continue
            block = {**block, "data": {**block.get("data", {}), "html": cleaned_html}}

        result.append(block)
        i += 1

    return result, stats


# ── API helpers ───────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", headers=HEADERS
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  fetch error: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list) -> bool:
    payload = json.dumps({"blocks": blocks}).encode("utf-8")
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
        print(f"  PATCH error: {e}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--save",    action="store_true", help="Apply fixes")
    parser.add_argument("--lesson",  help="Fix a single lesson by ID (e.g. C-040)")
    parser.add_argument("--all",     action="store_true", help="Run on ALL lessons (not just audit-broken)")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    # Build lesson ID list
    if args.lesson:
        lesson_ids = [args.lesson]
    elif args.all:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        lesson_ids = [l["id"] for l in manifest["lessons"]]
    elif AUDIT_PATH.exists():
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        lesson_ids = [r["id"] for r in audit.get("broken", [])]
    else:
        print("No audit file found. Use --lesson or --all."); sys.exit(1)

    total = len(lesson_ids)
    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"{mode} — fixing {total} lessons\n")

    overall = {"fixed": 0, "unchanged": 0, "fetch_error": 0, "patch_error": 0}

    for idx, lid in enumerate(lesson_ids, 1):
        data = fetch_lesson(lid)
        if not data:
            print(f"[{idx}/{total}] {lid}: FETCH ERROR")
            overall["fetch_error"] += 1
            continue

        blocks = data.get("blocks", [])
        fixed, stats = fix_blocks(blocks)

        total_changes = stats["merged"] + stats["placeholder_cleaned"] + stats["empty_removed"]

        if total_changes == 0:
            print(f"[{idx}/{total}] {lid}: unchanged ({len(blocks)} blocks)")
            overall["unchanged"] += 1
            if not args.dry_run:
                time.sleep(0.1)
            continue

        change_desc = []
        if stats["merged"]:           change_desc.append(f"{stats['merged']} headings merged")
        if stats["placeholder_cleaned"]: change_desc.append(f"{stats['placeholder_cleaned']} placeholders cleaned")
        if stats["empty_removed"]:    change_desc.append(f"{stats['empty_removed']} empty blocks removed")

        print(f"[{idx}/{total}] {lid}: {', '.join(change_desc)}  ({len(blocks)} → {len(fixed)} blocks)", end="")

        if args.dry_run:
            print(" [DRY RUN]")
            overall["fixed"] += 1
            continue

        ok = patch_lesson(lid, fixed)
        if ok:
            print(" ✓")
            overall["fixed"] += 1
        else:
            print(" PATCH FAILED")
            overall["patch_error"] += 1

        time.sleep(0.2)

    print(f"\n{'='*60}")
    print(f"Results: {overall}")
    if args.dry_run:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
