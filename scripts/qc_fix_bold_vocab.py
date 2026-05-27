"""
Genesis K-12 QC — Fix Bold Vocab Blocks

Finds text blocks where content is a list of bold "Term: Definition" items
(3+ per block) and converts them into proper vocab blocks.

Pattern detected:
  <p><strong>Tension:</strong> The force that pulls or stretches...</p>
  <p><strong>Compression:</strong> The force that pushes...</p>
  ...

This is distinct from qc_fix_vocab_labels.py which handles "Term:" / "Definition:"
alternating label pairs. This script handles blocks where each <strong> tag IS the
term itself (not a label).

Usage:
  python scripts/qc_fix_bold_vocab.py --dry-run
  python scripts/qc_fix_bold_vocab.py --save
  python scripts/qc_fix_bold_vocab.py --lesson-id C-023 --save
  python scripts/qc_fix_bold_vocab.py --course C --save
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY  = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

# Minimum number of bold-term items in a block to trigger conversion
MIN_TERMS = 3

# Labels that indicate "Term:" / "Definition:" alternating format — handled by
# qc_fix_vocab_labels.py, not this script.
SKIP_LABELS = {"term", "terms", "definition", "definitions"}

# Section-heading labels to exclude from vocab conversion
HEADING_LABELS = {
    "part 1", "part 2", "part 3", "part 4", "part 5", "part 6",
    "section 1", "section 2", "section 3", "section 4", "section 5",
    "step 1", "step 2", "step 3", "step 4", "step 5",
    "overview", "summary", "conclusion", "note",
    "objective", "objectives",
    "key concept", "faith connection", "biblical connection",
    "real world application", "engineering analogy",
    # OCV structural labels (used as section headers, not vocab definitions)
    "constraint", "constraints", "variable", "variables",
    "optimization", "plain", "ocv application",
    # Activity labels
    "initial test", "iteration 1", "iteration 2", "iteration 3",
    "plan", "do", "check", "act",
    # Form fields
    "person", "date of analysis", "location of lab",
    "name", "date", "location",
}

# ── Regex patterns ─────────────────────────────────────────────────────────────

# <p><strong>TERM:</strong> definition</p>  (colon inside strong)
BOLD_COLON_IN_RE = re.compile(
    r'<p[^>]*>\s*<(?:strong|b)>([^<:]{1,100}):\s*<\/(?:strong|b)>\s*(.*?)\s*<\/p>',
    re.IGNORECASE | re.DOTALL,
)

# <p><strong>TERM</strong>: definition</p>  (colon outside strong)
BOLD_COLON_OUT_RE = re.compile(
    r'<p[^>]*>\s*<(?:strong|b)>([^<]{1,100}?)<\/(?:strong|b)>\s*[:\-—–]\s*(.*?)\s*<\/p>',
    re.IGNORECASE | re.DOTALL,
)

# <p><strong>TERM: definition</strong></p>  (both inside strong)
BOLD_ALL_IN_RE = re.compile(
    r'<p[^>]*>\s*<(?:strong|b)>([^<:]{1,100}):\s+(.*?)<\/(?:strong|b)>\s*<\/p>',
    re.IGNORECASE | re.DOTALL,
)


def strip_tags(s: str) -> str:
    return re.sub(r'<[^>]+>', ' ', s).strip()


# Numbered step prefix: (1), (2), 1., 2., etc.
NUMBERED_STEP_RE = re.compile(r'^\s*[\(\[]?\d+[\)\]\.]\s*')


def extract_bold_terms(html: str) -> list[dict]:
    """
    Extract bold-term items from HTML. Returns list of
    {term, definition, raw, span_start, span_end}.
    Skips items whose label is a SKIP_LABEL (Term/Definition alternating format),
    HEADING_LABEL, numbered activity step, form fill-in blank, or hyphenated
    term that was incorrectly split at the first colon.
    """
    results = []

    for pattern in (BOLD_COLON_IN_RE, BOLD_COLON_OUT_RE, BOLD_ALL_IN_RE):
        for m in pattern.finditer(html):
            term = strip_tags(m.group(1)).strip().rstrip(":").strip()
            defn = strip_tags(m.group(2)).strip()
            if not term or not defn:
                continue
            term_lower = term.lower()

            # Skip Term/Definition label alternating format
            if term_lower in SKIP_LABELS:
                continue

            # Skip known section/structural headings
            if term_lower in HEADING_LABELS:
                continue

            # Skip numbered activity steps: (1), 1., etc.
            if NUMBERED_STEP_RE.match(term):
                continue

            # Skip "Option A/B/C" type items (example comparisons, not vocab)
            if re.match(r'^[Oo]ption\s+[A-Za-z0-9]$', term):
                continue

            # Skip terms starting with article + heading word: "A Plain", "The Trade"
            article_stripped = re.sub(r'^(A|An|The)\s+', '', term, flags=re.IGNORECASE).lower()
            if article_stripped in HEADING_LABELS:
                continue

            # Skip form fill-in blanks (definition is all underscores or a date template)
            if re.match(r'^[_\s/]*$', defn) or "___" in defn:
                continue

            # Skip compound terms incorrectly split at first colon:
            # e.g. "Cradle-to-Cradle Design" → "Cradle" + "to-Cradle Design: ..."
            # "Trade-off" → "Trade" + "off: A situation..."
            # "Non-Functional" → "Non" + "Functional Requirement: ..."
            # Detected when definition starts with a continuation fragment
            if defn.lower().startswith(("to-", "to ", "of-", "of ", "off", "functional")):
                continue

            results.append({
                "term": term,
                "definition": defn,
                "raw": m.group(0),
                "start": m.start(),
                "end": m.end(),
            })
        if results:
            break  # found matches with this pattern, no need to try others

    return results


def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def is_bold_vocab_block(html: str) -> bool:
    return len(extract_bold_terms(html)) >= MIN_TERMS


def split_block(block: dict) -> list[dict]:
    """
    Split a text block into:
    - A vocab block for the bold-term items
    - A text block for any remaining HTML (before/between/after items)
    Returns a list of replacement blocks.
    """
    html  = block.get("data", {}).get("html", "")
    meta  = block.get("meta", {"spacing": "md", "qcStatus": "pending"})
    items = extract_bold_terms(html)

    if len(items) < MIN_TERMS:
        return [block]

    vocab_items = [{"term": i["term"], "definition": i["definition"]} for i in items]

    # Remove the matched portions from HTML to find remaining content
    remaining_html = html
    for item in sorted(items, key=lambda x: x["start"], reverse=True):
        remaining_html = remaining_html[:item["start"]] + remaining_html[item["end"]:]

    # Clean up remaining content
    remaining_html = re.sub(r'\s*<p[^>]*>\s*<\/p>\s*', '', remaining_html).strip()
    remaining_html = re.sub(r'\n{3,}', '\n\n', remaining_html).strip()

    result = []

    vocab_block = {
        "id": gen_id(),
        "type": "vocab",
        "data": {"columns": 2, "items": vocab_items},
        "meta": {**meta, "qcStatus": "pending"},
    }
    result.append(vocab_block)

    if remaining_html and len(remaining_html) > 10:
        result.append({
            "id": gen_id(),
            "type": "text",
            "data": {"html": remaining_html},
            "meta": meta,
        })

    return result


# ── Platform API ───────────────────────────────────────────────────────────────

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
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  [PATCH ERR] {lesson_id}: {e}")
        return False


# ── Per-lesson processing ──────────────────────────────────────────────────────

def process_lesson(lesson_id: str, dry_run: bool) -> dict:
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return {"lessonId": lesson_id, "status": "fetch_error"}

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    affected = [
        (i, b) for i, b in enumerate(blocks)
        if b.get("type") == "text"
        and is_bold_vocab_block(b.get("data", {}).get("html", ""))
    ]

    if not affected:
        return {"lessonId": lesson_id, "status": "clean"}

    total_terms = sum(
        len(extract_bold_terms(b.get("data", {}).get("html", "")))
        for _, b in affected
    )
    print(f"\n  {lesson_id} — {title}")
    print(f"    {len(affected)} block(s) with {total_terms} bold-term pairs to convert")

    if dry_run:
        for i, b in affected:
            items = extract_bold_terms(b.get("data", {}).get("html", ""))
            for it in items[:5]:
                print(f"      • {it['term']}: {it['definition'][:60]}...")
            if len(items) > 5:
                print(f"      ... {len(items) - 5} more")
        return {"lessonId": lesson_id, "status": "would_fix",
                "blocksFixed": len(affected), "termsFound": total_terms}

    updated = list(blocks)
    offset  = 0

    for orig_idx, block in affected:
        replacements = split_block(block)
        real_idx = orig_idx + offset
        updated  = updated[:real_idx] + replacements + updated[real_idx + 1:]
        offset  += len(replacements) - 1

    ok     = patch_lesson(lesson_id, updated)
    status = "fixed" if ok else "patch_failed"
    print(f"    → {status} ({total_terms} terms)")
    return {"lessonId": lesson_id, "status": status,
            "blocksFixed": len(affected), "termsFixed": total_terms}


# ── Main ───────────────────────────────────────────────────────────────────────

def load_manifest() -> list[str]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    lessons = data.get("lessons", data) if isinstance(data, dict) else data
    return [l["id"] for l in lessons]


def main():
    parser = argparse.ArgumentParser(description="Convert bold Term: Definition blocks to vocab blocks")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--save",      action="store_true")
    parser.add_argument("--lesson-id", help="Single lesson")
    parser.add_argument("--course",    choices=["C", "M"])
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run (pass --save to apply)")

    dry_run = not args.save

    if args.lesson_id:
        lesson_ids = [args.lesson_id]
    elif args.course:
        lesson_ids = [l for l in load_manifest() if l.startswith(args.course + "-")]
    else:
        lesson_ids = load_manifest()

    mode = "DRY RUN" if dry_run else "SAVING"
    print(f"\nGenesis K-12 QC Fix Bold Vocab — {len(lesson_ids)} lessons [{mode}]")
    print("=" * 60)

    fixed = clean = errors = 0

    for lid in lesson_ids:
        r = process_lesson(lid, dry_run)
        s = r.get("status")
        if s in ("fixed", "would_fix"):
            fixed += 1
        elif s == "clean":
            clean += 1
        else:
            errors += 1
        time.sleep(0.3)

    print(f"\n{'=' * 60}")
    action = "Would fix" if dry_run else "Fixed"
    print(f"Done.  {clean} clean,  {fixed} {action.lower()},  {errors} errors.")
    if dry_run and fixed > 0:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
