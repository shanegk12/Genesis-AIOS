"""
qc_regen_flashcards.py

Regenerates flashcards.html for every lesson that has vocab blocks,
using the clean Previous/Flip/Next template from generate_flashcards.py.
Replaces the old vertical-stack style that required scrolling.

Uploads via /api/admin/interactives and patches the lesson embed block
with the correct proxy URL.

Usage:
  python scripts/qc_regen_flashcards.py --dry-run         # preview
  python scripts/qc_regen_flashcards.py --save            # regenerate + upload all
  python scripts/qc_regen_flashcards.py --lesson C-007    # single lesson
"""

import argparse, base64, json, os, random, string, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Import the canonical flashcard generator from generate_flashcards.py
sys.path.insert(0, str(Path(__file__).parent))
from generate_flashcards import generate_flashcard_html, extract_vocab_items

LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
INTERACTIVES_DIR = Path(__file__).parent / "interactives"
MANIFEST_PATH    = Path(__file__).parent / "lessons_manifest.json"


def _get_platform_key() -> str:
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
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


def fetch_lesson(lesson_id: str, key: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  Fetch error: {e}")
        return None


def upload_interactive(lesson_id: str, filename: str, html: str, key: str) -> str | None:
    payload = json.dumps({
        "lessonId": lesson_id,
        "filename": filename,
        "mimeType": "text/html; charset=utf-8",
        "dataBase64": base64.b64encode(html.encode("utf-8")).decode(),
    }).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/interactives", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("url") if result.get("ok") else None
    except urllib.error.HTTPError as e:
        print(f"  Upload HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return None
    except Exception as e:
        print(f"  Upload error: {e}")
        return None


def patch_blocks(lesson_id: str, blocks: list, key: str) -> bool:
    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


def gen_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def process_lesson(lesson_id: str, key: str, dry_run: bool) -> dict:
    lesson = fetch_lesson(lesson_id, key)
    if not lesson:
        return {"id": lesson_id, "status": "fetch_error"}

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])
    items  = extract_vocab_items(blocks)

    if not items:
        return {"id": lesson_id, "status": "no_vocab"}

    print(f"  [{lesson_id}] {title} — {len(items)} vocab terms")

    html = generate_flashcard_html(lesson_id, title, items)

    if dry_run:
        print(f"    DRY RUN: would generate {len(html)} chars and upload")
        return {"id": lesson_id, "status": "dry_run", "terms": len(items)}

    # Save locally
    local_dir = INTERACTIVES_DIR / lesson_id
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "flashcards.html").write_text(html, encoding="utf-8")

    # Upload
    url = upload_interactive(lesson_id, "flashcards.html", html, key)
    if not url:
        return {"id": lesson_id, "status": "upload_failed"}

    print(f"    Uploaded → {url}")

    # Find and update existing flashcard embed, or append new one
    updated = list(blocks)
    embed_idx = next(
        (i for i, b in enumerate(updated)
         if b.get("type") == "embed" and (
             "flashcard" in (b.get("data", {}).get("src") or "").lower()
             or "flashcard" in (b.get("data", {}).get("label") or "").lower()
             or "vocabulary" in (b.get("data", {}).get("label") or "").lower()
             or (not (b.get("data", {}).get("src") or "").strip())  # empty src
         )),
        None,
    )

    if embed_idx is not None:
        updated[embed_idx] = {
            **updated[embed_idx],
            "data": {**updated[embed_idx].get("data", {}), "src": url, "label": "Vocabulary Flashcards"},
        }
    else:
        updated.append({
            "id": gen_id(),
            "type": "embed",
            "data": {"src": url, "height": 520, "label": "Vocabulary Flashcards"},
            "meta": {"spacing": "md", "qcStatus": "approved"},
        })

    ok = patch_blocks(lesson_id, updated, key)
    status = "done" if ok else "patch_failed"
    print(f"    {'OK' if ok else 'PATCH FAILED'}")
    return {"id": lesson_id, "status": status, "terms": len(items)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--lesson",  help="Single lesson ID")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    key = _get_platform_key()
    if not key:
        print("PIPELINE_KEY not found in .env"); sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lesson_ids = [l["id"] for l in manifest["lessons"]]
    if args.lesson:
        lesson_ids = [args.lesson.upper()]

    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"\nQC Regen Flashcards [{mode}] — {len(lesson_ids)} lesson(s)")
    print("=" * 60)

    counts: dict[str, int] = {}
    for i, lid in enumerate(lesson_ids, 1):
        print(f"[{i}/{len(lesson_ids)}]", end=" ")
        r = process_lesson(lid, key, dry_run=args.dry_run)
        s = r["status"]
        counts[s] = counts.get(s, 0) + 1
        time.sleep(0.2)

    print(f"\n{'='*60}")
    print("SUMMARY:", counts)


if __name__ == "__main__":
    main()
