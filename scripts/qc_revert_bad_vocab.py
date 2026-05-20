"""
Genesis K-12 QC — Revert Bad Vocab Blocks

Finds vocab blocks where "Definition" or "Term" were used as the vocabulary
term names (a parsing bug from the 2026-05-19 auto-convert run). Converts
those blocks back to plain text so lessons are readable again.

The vocab items are reconstructed to HTML:
  - If the item looks like a section heading (multi-word or known heading label)
    → <h3>term</h3><p>definition</p>
  - Otherwise → <p><strong>term:</strong> definition</p>

Run with --dry-run first to preview affected lessons.

Usage:
  python scripts/qc_revert_bad_vocab.py --dry-run
  python scripts/qc_revert_bad_vocab.py --save
  python scripts/qc_revert_bad_vocab.py --lesson-id C-025 --save
  python scripts/qc_revert_bad_vocab.py --course C --save
"""

import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY  = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

# Terms that should never be vocabulary headings — they're structural labels
BAD_TERMS = {
    "definition", "definitions", "term", "terms",
    "part 1", "part 2", "part 3", "part 4", "part 5", "part 6",
    "section 1", "section 2", "section 3", "section 4", "section 5",
    "step 1", "step 2", "step 3", "step 4", "step 5",
}

# Labels that look like section headings — render as <h3> not <strong>
HEADING_INDICATORS = {
    "the beginning", "the end", "engineering analogy", "multiscale modeling",
    "multiscale modeling connection", "real world", "real-world", "connection",
    "biblical connection", "faith connection", "key concept", "key insight",
    "summary", "overview", "application", "example", "activity",
}


def is_heading_like(term: str) -> bool:
    """Returns True if the term looks more like a section heading than a vocab word."""
    t = term.lower().strip()
    if t in HEADING_INDICATORS:
        return True
    # Multi-word phrases that aren't clean vocab terms are likely headings
    words = t.split()
    if len(words) >= 3:
        return True
    return False


def vocab_item_to_html(term: str, definition: str) -> str:
    t = term.strip()
    d = definition.strip()
    if not d:
        return f"<p><strong>{t}</strong></p>"
    if is_heading_like(t):
        return f"<h3>{t}</h3><p>{d}</p>"
    return f"<p><strong>{t}:</strong> {d}</p>"


def vocab_block_to_text_html(block: dict) -> str:
    items = block.get("data", {}).get("items", [])
    parts = [vocab_item_to_html(i.get("term", ""), i.get("definition", "")) for i in items]
    return "\n".join(parts)


def is_bad_vocab_block(block: dict) -> bool:
    if block.get("type") != "vocab":
        return False
    items = block.get("data", {}).get("items", [])
    bad = sum(1 for i in items if i.get("term", "").lower().strip() in BAD_TERMS)
    return bad >= 2


# ── Platform API ───────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] {lesson_id}")
        return None
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
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"  [PATCH ERR] {lesson_id}: {e}")
        return False


# ── Main logic ─────────────────────────────────────────────────────────────────

def process_lesson(lesson_id: str, dry_run: bool) -> dict:
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return {"lessonId": lesson_id, "status": "fetch_error"}

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    bad_indices = [i for i, b in enumerate(blocks) if is_bad_vocab_block(b)]
    if not bad_indices:
        return {"lessonId": lesson_id, "status": "clean"}

    print(f"\n  {lesson_id} — {title}")
    print(f"    Bad vocab blocks at indices: {bad_indices}")

    updated_blocks = list(blocks)
    for idx in bad_indices:
        block = blocks[idx]
        items = block.get("data", {}).get("items", [])
        bad_terms = [i.get("term") for i in items if i.get("term", "").lower().strip() in BAD_TERMS]
        print(f"    Block {idx}: {len(items)} items, bad term names: {bad_terms[:5]}")

        if not dry_run:
            text_html = vocab_block_to_text_html(block)
            updated_blocks[idx] = {
                "id": block.get("id", ""),
                "type": "text",
                "data": {"html": text_html},
                "meta": block.get("meta", {"spacing": "md"}),
            }

    if not dry_run:
        ok = patch_lesson(lesson_id, updated_blocks)
        status = "reverted" if ok else "patch_failed"
        print(f"    → {status}")
    else:
        status = "would_revert"
        print(f"    → (dry-run) would revert {len(bad_indices)} block(s)")

    return {"lessonId": lesson_id, "title": title, "status": status, "badBlocks": len(bad_indices)}


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lessons", data) if isinstance(data, dict) else data


def main():
    parser = argparse.ArgumentParser(description="Revert bad vocab blocks (Definition/Term label bug)")
    parser.add_argument("--dry-run",   action="store_true", help="Preview without saving")
    parser.add_argument("--save",      action="store_true", help="Apply changes")
    parser.add_argument("--lesson-id", help="Single lesson")
    parser.add_argument("--course",    choices=["C", "M"], help="All lessons in course")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("No --dry-run or --save specified — defaulting to --dry-run")

    dry_run = not args.save

    lessons: list[str] = []
    if args.lesson_id:
        lessons = [args.lesson_id]
    elif args.course:
        manifest = load_manifest()
        prefix = args.course + "-"
        lessons = [l["id"] for l in manifest if l["id"].startswith(prefix)]
    else:
        manifest = load_manifest()
        lessons = [l["id"] for l in manifest]

    print(f"\nGenesis K-12 QC Revert Bad Vocab — {len(lessons)} lessons {'(DRY RUN)' if dry_run else '(SAVING)'}")
    print("=" * 60)

    results = []
    reverted = 0
    clean = 0
    errors = 0

    for lid in lessons:
        r = process_lesson(lid, dry_run)
        results.append(r)
        s = r.get("status")
        if s in ("reverted", "would_revert"):
            reverted += 1
        elif s == "clean":
            clean += 1
        else:
            errors += 1
        time.sleep(0.3)

    print(f"\n{'='*60}")
    action = "Would revert" if dry_run else "Reverted"
    print(f"Done. {clean} clean, {reverted} {action.lower()}, {errors} errors.")

    if dry_run and reverted > 0:
        print(f"\nRun with --save to apply changes.")


if __name__ == "__main__":
    main()
