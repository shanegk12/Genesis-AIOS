"""
Genesis K-12 Interactive Uploader (local → Firebase Storage)

Uploads pre-generated HTML5 interactives from scripts/interactives/{lessonId}/
directly to Firebase Storage, then creates/replaces embed blocks in each lesson.

Unlike interactive_importer.py (which reads from Drive), this script reads from
the local scripts/interactives/ directory — where interactive_agent.py writes.

Storage layout after upload:
  interactives/{lessonId}/flashcards.html
  interactives/{lessonId}/accordion.html
  interactives/{lessonId}/ocv.html
  interactives/{lessonId}/concept.html

Each lesson gets ONE embed block pointing to the primary interactive (concept.html
if present, otherwise flashcards.html as fallback).

Usage:
  python scripts/interactive_upload.py --dry-run
  python scripts/interactive_upload.py --save
  python scripts/interactive_upload.py --lesson-id C-025 --save
  python scripts/interactive_upload.py --course C --save
"""

import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))
from _gws_auth import get_session

# ── Config ─────────────────────────────────────────────────────────────────────

LIVE_URL        = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY    = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
STORAGE_BUCKET  = "genesis-modularity.firebasestorage.app"
UPLOAD_API_BASE = f"https://storage.googleapis.com/upload/storage/v1/b/{STORAGE_BUCKET}/o"
MANIFEST_PATH   = Path(__file__).parent / "lessons_manifest.json"
INTERACTIVES_DIR = Path(__file__).parent / "interactives"

EMBED_HEIGHT_DEFAULT = 560

# Priority order for choosing the primary embed interactive
PRIMARY_PRIORITY = ["concept.html", "flashcards.html", "accordion.html", "ocv.html"]


# ── Helpers ─────────────────────────────────────────────────────────────────────

def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def mime_for(filename: str) -> str:
    return {"html": "text/html; charset=utf-8"}.get(
        Path(filename).suffix.lstrip(".").lower(), "application/octet-stream"
    )


def upload_file(session, storage_path: str, content: bytes, content_type: str) -> str:
    import urllib.parse
    encoded = urllib.parse.quote(storage_path, safe="")
    resp = session.post(
        f"{UPLOAD_API_BASE}?uploadType=media&name={encoded}",
        data=content,
        headers={"Content-Type": content_type},
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed {resp.status_code}: {resp.text[:200]}")
    return storage_path


def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [ERR] fetch {lesson_id}: {e}")
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
        print(f"  [ERR] patch {lesson_id}: {e}")
        return False


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lessons", data) if isinstance(data, dict) else data


# ── Core ────────────────────────────────────────────────────────────────────────

def process_lesson(session, lesson_id: str, dry_run: bool) -> dict:
    lesson_dir = INTERACTIVES_DIR / lesson_id
    if not lesson_dir.exists():
        return {"lessonId": lesson_id, "status": "no_local_files"}

    html_files = sorted(lesson_dir.glob("*.html"))
    if not html_files:
        return {"lessonId": lesson_id, "status": "no_local_files"}

    # Pick primary interactive for the embed block
    primary = next(
        (lesson_dir / p for p in PRIMARY_PRIORITY if (lesson_dir / p).exists()),
        html_files[0],
    )
    embed_url = f"/api/interactive/{lesson_id}/{primary.name}"

    print(f"\n  {lesson_id} — {len(html_files)} file(s), primary: {primary.name}")

    if not dry_run:
        for html_file in html_files:
            storage_path = f"interactives/{lesson_id}/{html_file.name}"
            content = html_file.read_bytes()
            upload_file(session, storage_path, content, "text/html; charset=utf-8")
            print(f"    ✓ uploaded {html_file.name}")

        lesson = fetch_lesson(lesson_id)
        if not lesson:
            return {"lessonId": lesson_id, "status": "fetch_error"}

        blocks: list = lesson.get("blocks", [])
        embed_block = {
            "id": gen_id(),
            "type": "embed",
            "data": {
                "url": embed_url,
                "height": EMBED_HEIGHT_DEFAULT,
                "title": f"Interactive — {lesson_id}",
            },
            "meta": {"spacing": "md", "qcStatus": "pending"},
        }

        replaced = False
        for i, b in enumerate(blocks):
            if b.get("type") == "embed":
                blocks[i] = embed_block
                replaced = True
                break
        if not replaced:
            blocks.append(embed_block)

        ok = patch_lesson(lesson_id, blocks)
        status = "uploaded" if ok else "upload_ok_patch_failed"
        print(f"    → {status} ({'replaced' if replaced else 'appended'} embed block)")
    else:
        status = "would_upload"
        print(f"    → (dry-run) embed URL: {embed_url}")

    return {"lessonId": lesson_id, "status": status, "files": len(html_files), "primary": primary.name}


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upload local interactives to Firebase Storage")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--lesson-id", help="Single lesson")
    parser.add_argument("--course",    choices=["C", "M"])
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run")
    dry_run = not args.save

    if not INTERACTIVES_DIR.exists():
        print(f"No interactives directory found at {INTERACTIVES_DIR}")
        sys.exit(1)

    if args.lesson_id:
        lesson_ids = [args.lesson_id]
    elif args.course:
        lesson_ids = [d.name for d in sorted(INTERACTIVES_DIR.iterdir())
                      if d.is_dir() and d.name.startswith(args.course + "-")]
    else:
        lesson_ids = [d.name for d in sorted(INTERACTIVES_DIR.iterdir()) if d.is_dir()]

    print(f"\nGenesis K-12 Interactive Uploader — {len(lesson_ids)} lesson(s) {'(DRY RUN)' if dry_run else '(SAVING)'}")
    print("=" * 60)

    session = get_session() if not dry_run else None

    results = []
    for lid in lesson_ids:
        r = process_lesson(session, lid, dry_run)
        results.append(r)
        if not dry_run:
            time.sleep(0.3)

    uploaded = sum(1 for r in results if r["status"] == "uploaded")
    would = sum(1 for r in results if r["status"] == "would_upload")
    skipped = sum(1 for r in results if r["status"] == "no_local_files")
    errors = sum(1 for r in results if r["status"] not in ("uploaded", "would_upload", "no_local_files"))

    print(f"\n{'='*60}")
    if dry_run:
        print(f"Would upload: {would}, no local files: {skipped}")
        print("Run with --save to apply.")
    else:
        print(f"Uploaded: {uploaded}, skipped: {skipped}, errors: {errors}")


if __name__ == "__main__":
    main()
