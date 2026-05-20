"""
Genesis K-12 QC — Fix Vocab Labels (Smart Re-import Pass)

After the bad vocab revert, 57 lessons have content as:
  <p><strong>Term:</strong> Milestone</p>
  <p><strong>Definition:</strong> A significant point or event...</p>

This script detects that alternating Term/Definition pattern and re-pairs them
into proper vocab blocks: {term: "Milestone", definition: "A significant point..."}

Non-vocab labeled content (Part 1:, Part 2:, section headings, paragraph content)
is left as text or promoted to h3 headings.

Usage:
  python scripts/qc_fix_vocab_labels.py --dry-run
  python scripts/qc_fix_vocab_labels.py --save
  python scripts/qc_fix_vocab_labels.py --lesson-id C-040 --save
  python scripts/qc_fix_vocab_labels.py --course C --save
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

# Labels that are real vocabulary markers (from the LearnWorlds format)
TERM_LABELS = {"term", "terms"}
DEF_LABELS  = {"definition", "definitions"}
VOCAB_LABELS = TERM_LABELS | DEF_LABELS

# Labels that look like section headings — convert to <h3>
HEADING_LABELS = {
    "part 1", "part 2", "part 3", "part 4", "part 5", "part 6",
    "section 1", "section 2", "section 3", "section 4", "section 5",
    "step 1", "step 2", "step 3", "step 4", "step 5",
    "the beginning", "engineering analogy", "multiscale modeling connection",
    "real world application", "biblical connection", "faith connection",
    "key concept", "summary", "conclusion", "overview",
}


# ── HTML parsing helpers ───────────────────────────────────────────────────────

# Match <p><strong>LABEL:</strong> VALUE</p>  (colon inside strong, value outside)
# This is the format produced by qc_revert_bad_vocab.py
LABEL_COLON_IN_RE = re.compile(
    r'<p[^>]*>\s*<(?:strong|b)>([^<:]{1,79}):\s*<\/(?:strong|b)>\s*(.*?)\s*<\/p>',
    re.IGNORECASE | re.DOTALL
)

# Match <p><strong>LABEL</strong>: VALUE</p>  (colon outside strong tag)
LABEL_OUT_RE = re.compile(
    r'<p[^>]*>\s*<(?:strong|b)>([^<]{1,80}?)<\/(?:strong|b)>\s*[:\-—–]\s*(.*?)\s*<\/p>',
    re.IGNORECASE | re.DOTALL
)

# Match <p><strong>LABEL: VALUE</strong></p>  (colon and value both inside strong tag)
LABEL_IN_RE = re.compile(
    r'<p[^>]*>\s*<(?:strong|b)>([^<:]{1,79}):\s+(.*?)<\/(?:strong|b)>\s*<\/p>',
    re.IGNORECASE | re.DOTALL
)

def strip_tags(html: str) -> str:
    return re.sub(r'<[^>]+>', ' ', html).strip()


def parse_labeled_items(html: str) -> list[dict]:
    """
    Parse all <p><strong>Label:</strong> value</p> items from an HTML block.
    Returns list of {label: str, value: str, raw: str} dicts.
    Tries LABEL_COLON_IN_RE first (format from qc_revert_bad_vocab.py),
    then LABEL_OUT_RE, then LABEL_IN_RE.
    """
    items = []
    for m in LABEL_COLON_IN_RE.finditer(html):
        label = strip_tags(m.group(1)).strip().rstrip(":")
        value = strip_tags(m.group(2)).strip()
        items.append({"label": label, "value": value, "raw": m.group(0)})
    if not items:
        for m in LABEL_OUT_RE.finditer(html):
            label = strip_tags(m.group(1)).strip().rstrip(":")
            value = strip_tags(m.group(2)).strip()
            items.append({"label": label, "value": value, "raw": m.group(0)})
    if not items:
        for m in LABEL_IN_RE.finditer(html):
            label = strip_tags(m.group(1)).strip().rstrip(":")
            value = strip_tags(m.group(2)).strip()
            items.append({"label": label, "value": value, "raw": m.group(0)})
    return items


def is_vocab_label_block(html: str) -> bool:
    """Return True if the block has ≥2 items with Term/Definition labels."""
    items = parse_labeled_items(html)
    vocab_count = sum(1 for i in items if i["label"].lower() in VOCAB_LABELS)
    return vocab_count >= 2


# ── Repair logic ───────────────────────────────────────────────────────────────

def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def repair_vocab_block(block: dict) -> list[dict]:
    """
    Convert a text block with Term/Definition labels into:
    - A vocab block with properly paired term+definition items
    - Text blocks for non-vocab labeled content (part headings, section prose)

    Returns a list of replacement blocks (may be 1 vocab + surrounding text blocks).
    """
    html = block.get("data", {}).get("html", "")
    items = parse_labeled_items(html)
    if not items:
        return [block]

    meta = block.get("meta", {"spacing": "md", "qcStatus": "pending"})

    # Separate items into vocab vs non-vocab labeled content
    terms = [i for i in items if i["label"].lower() in TERM_LABELS]
    defs  = [i for i in items if i["label"].lower() in DEF_LABELS]
    other = [i for i in items if i["label"].lower() not in VOCAB_LABELS]

    result_blocks = []

    # ── Vocab pairs ────────────────────────────────────────────────────────────
    # Strategy: if we have equal counts, pair in order (Term[0]+Def[0], etc.)
    # If unequal, try to detect interleaved T/D/T/D pattern from original order.
    vocab_items = []

    if len(terms) == len(defs) and terms:
        for t, d in zip(terms, defs):
            if t["value"] and d["value"]:
                vocab_items.append({"term": t["value"], "definition": d["value"]})
    elif terms and defs:
        # Best-effort: pair any term with the next definition that follows it
        term_queue = list(terms)
        used_defs  = set()
        for t in term_queue:
            # Find first def that comes after this term in the original item order
            t_pos = items.index(t)
            for d in defs:
                d_pos = items.index(d)
                if d_pos > t_pos and id(d) not in used_defs:
                    if t["value"] and d["value"]:
                        vocab_items.append({"term": t["value"], "definition": d["value"]})
                    used_defs.add(id(d))
                    break

    if len(vocab_items) >= 2:
        result_blocks.append({
            "id": gen_id(),
            "type": "vocab",
            "data": {"columns": 2, "items": vocab_items},
            "meta": {**meta, "qcStatus": "pending"},
        })

    # ── Non-vocab labeled items → text or h3 ──────────────────────────────────
    if other:
        html_parts = []
        for item in other:
            label_lower = item["label"].lower()
            if label_lower in HEADING_LABELS or (len(item["label"].split()) <= 4 and len(item["value"]) < 80):
                # Short label + short value → section heading style
                html_parts.append(f"<h3>{item['label']}</h3>")
                if item["value"]:
                    html_parts.append(f"<p>{item['value']}</p>")
            else:
                html_parts.append(f"<p><strong>{item['label']}:</strong> {item['value']}</p>")

        if html_parts:
            result_blocks.append({
                "id": gen_id(),
                "type": "text",
                "data": {"html": "\n".join(html_parts)},
                "meta": meta,
            })

    # If we couldn't produce anything useful, return original
    return result_blocks if result_blocks else [block]


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


# ── Main ───────────────────────────────────────────────────────────────────────

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

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    # Find text blocks with Term/Definition label patterns
    affected = [(i, b) for i, b in enumerate(blocks)
                if b.get("type") == "text" and is_vocab_label_block(b.get("data", {}).get("html", ""))]

    if not affected:
        return {"lessonId": lesson_id, "status": "clean"}

    print(f"\n  {lesson_id} — {title}")

    updated = list(blocks)
    offset = 0  # track index shift as we replace 1 block with N blocks

    for orig_idx, block in affected:
        html = block.get("data", {}).get("html", "")
        items = parse_labeled_items(html)
        terms = [i for i in items if i["label"].lower() in TERM_LABELS]
        defs  = [i for i in items if i["label"].lower() in DEF_LABELS]
        print(f"    Block {orig_idx}: {len(terms)} terms, {len(defs)} definitions")

        replacements = repair_vocab_block(block)
        vocab_blocks = [b for b in replacements if b["type"] == "vocab"]
        print(f"    → {len(replacements)} replacement block(s), "
              f"{sum(len(b['data']['items']) for b in vocab_blocks)} vocab pairs")

        if not dry_run:
            real_idx = orig_idx + offset
            updated = updated[:real_idx] + replacements + updated[real_idx + 1:]
            offset += len(replacements) - 1

    if not dry_run:
        ok = patch_lesson(lesson_id, updated)
        status = "fixed" if ok else "patch_failed"
        print(f"    → {status}")
    else:
        status = "would_fix"
        print(f"    → (dry-run) would fix")

    return {"lessonId": lesson_id, "title": title, "status": status, "blocksFixed": len(affected)}


def main():
    parser = argparse.ArgumentParser(description="Smart vocab re-import: repair Term/Definition label blocks")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--save",      action="store_true")
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

    print(f"\nGenesis K-12 QC Fix Vocab Labels — {len(lessons)} lessons {'(DRY RUN)' if dry_run else '(SAVING)'}")
    print("=" * 60)

    results = []
    fixed = clean = errors = 0

    for lid in lessons:
        r = process_lesson(lid, dry_run)
        results.append(r)
        s = r.get("status")
        if s in ("fixed", "would_fix"):
            fixed += 1
        elif s == "clean":
            clean += 1
        else:
            errors += 1
        time.sleep(0.3)

    print(f"\n{'='*60}")
    action = "Would fix" if dry_run else "Fixed"
    print(f"Done. {clean} already clean, {fixed} {action.lower()}, {errors} errors.")
    if dry_run and fixed > 0:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
