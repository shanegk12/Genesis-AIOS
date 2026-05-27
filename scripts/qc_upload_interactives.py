"""
Genesis K-12 QC — Upload Pre-generated Interactives to Firebase Storage

Scans scripts/interactives/{lessonId}/ for HTML files, uploads each to Firebase Storage
at interactives/{lessonId}/{filename}, and adds embed blocks to the lesson if not present.

Usage:
  python scripts/qc_upload_interactives.py --dry-run
  python scripts/qc_upload_interactives.py --save
  python scripts/qc_upload_interactives.py --lesson-id C-025 --save
"""

import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"
INTERACTIVES_DIR = Path(__file__).parent / "interactives"
LOG_PATH = Path(__file__).parent / "interactive_upload_log.json"

STORAGE_BUCKET  = "genesis-modularity.firebasestorage.app"
UPLOAD_API_BASE = f"https://storage.googleapis.com/upload/storage/v1/b/{STORAGE_BUCKET}/o"

EMBED_HEIGHT = 520

# Priority order: concept.html is the primary, others are supplementary
PRIMARY_FILE   = "concept.html"
SECONDARY_FILES = ["flashcards.html", "accordion.html", "ocv.html"]


def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  Fetch error: {e}")
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
        print(f"  PATCH error: {e}")
        return False


def upload_to_storage(session, lesson_id: str, local_path: Path, filename: str) -> str | None:
    """Upload an HTML file to Firebase Storage. Returns the embed URL or None."""
    storage_path = f"interactives/{lesson_id}/{filename}"
    content = local_path.read_bytes()
    encoded = urllib.parse.quote(storage_path, safe="")
    try:
        resp = session.post(
            f"{UPLOAD_API_BASE}?uploadType=media&name={encoded}",
            data=content,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
        if resp.status_code in (200, 201):
            return f"/api/interactive/{lesson_id}/{filename}"
        print(f"    Storage upload failed {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"    Storage error: {e}")
        return None


def process_lesson(lesson_id: str, out_dir: Path, session, dry_run: bool) -> str:
    """Upload interactives from out_dir and add embed blocks to the lesson."""
    html_files = list(out_dir.glob("*.html"))
    if not html_files:
        return "no_files"

    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return "fetch_error"

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    # Check existing embed URLs
    existing_embeds = {
        b.get("data", {}).get("src", "")
        for b in blocks if b.get("type") == "embed"
    }

    html_map = {f.name: f for f in html_files}
    # Order: primary first, then secondaries, then any others
    ordered = []
    for fname in [PRIMARY_FILE] + SECONDARY_FILES:
        if fname in html_map:
            ordered.append((fname, html_map[fname]))
    for f in html_files:
        if f.name not in dict(ordered):
            ordered.append((f.name, f))

    print(f"\n  [{lesson_id}] {title} — {len(html_files)} interactive(s)")
    print(f"    Files: {[f for f, _ in ordered]}")
    print(f"    Existing embeds: {len(existing_embeds)}")

    if dry_run:
        for fname, _ in ordered:
            url = f"/api/interactive/{lesson_id}/{fname}"
            status = "exists" if url in existing_embeds else "would upload"
            print(f"    {fname}: {status}")
        return "would_upload"

    new_embeds = []
    for fname, fpath in ordered:
        url = f"/api/interactive/{lesson_id}/{fname}"
        if url in existing_embeds:
            print(f"    {fname}: already embedded, uploading to refresh storage...")
            # Still upload to storage to ensure file exists
            upload_to_storage(session, lesson_id, fpath, fname)
            time.sleep(0.3)
            continue

        print(f"    Uploading {fname}...", end=" ", flush=True)
        uploaded_url = upload_to_storage(session, lesson_id, fpath, fname)
        if uploaded_url:
            label = fname.replace(".html", "").replace("-", " ").title()
            new_embeds.append({"url": url, "label": label})
            print(f"OK")
        else:
            print(f"FAILED")
        time.sleep(0.3)

    if not new_embeds:
        return "no_new_embeds"

    # Add embed blocks
    new_blocks = list(blocks)
    for e in new_embeds:
        new_blocks.append({
            "id": gen_id(),
            "type": "embed",
            "data": {
                "src": e["url"],
                "height": EMBED_HEIGHT,
                "label": e["label"],
            },
            "meta": {"spacing": "md", "qcStatus": "pending"},
        })

    ok = patch_lesson(lesson_id, new_blocks)
    if ok:
        print(f"    Patched: added {len(new_embeds)} embed block(s)")
        return "done"
    return "patch_error"


def load_log() -> dict:
    if LOG_PATH.exists():
        try:
            return json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def main():
    parser = argparse.ArgumentParser(description="Upload pre-generated interactives to Firebase Storage")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--save",      action="store_true")
    parser.add_argument("--lesson-id", help="Single lesson ID")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run (pass --save to apply)")
    dry_run = not args.save

    # Find all lesson directories with HTML files
    if args.lesson_id:
        targets = [(args.lesson_id, INTERACTIVES_DIR / args.lesson_id)]
    else:
        targets = [
            (d.name, d) for d in sorted(INTERACTIVES_DIR.iterdir())
            if d.is_dir() and list(d.glob("*.html"))
        ]

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\nQC Upload Interactives [{mode}]: {len(targets)} lesson(s)")
    print("=" * 60)

    session = None
    if not dry_run:
        print("Authenticating with Google...")
        from _gws_auth import get_session
        session = get_session()

    log    = load_log()
    counts = {"done": 0, "would_upload": 0, "no_new_embeds": 0, "no_files": 0, "error": 0}

    for lesson_id, out_dir in targets:
        status = process_lesson(lesson_id, out_dir, session, dry_run)
        key    = status if status in counts else "error"
        counts[key] += 1
        time.sleep(0.5)

    if not dry_run:
        log["last_run"] = datetime.now(timezone.utc).isoformat()
        LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"Done: {counts}")
    if dry_run:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
