"""
One-shot fix: patch Firebase Storage download tokens for all existing lesson images.

The /api/admin/images route incorrectly set firebaseStorageDownloadTokens as a
top-level GCS metadata field instead of custom metadata (metadata.metadata). This
causes 403 on all token URLs. This script reads the token from each stored URL and
patches the GCS object's custom metadata to put it in the right place.

Usage:
  python scripts/fix_image_tokens.py --dry-run
  python scripts/fix_image_tokens.py --save
  python scripts/fix_image_tokens.py --lesson-id C-006 --save
"""

import argparse, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
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

STORAGE_BUCKET = "genesis-modularity.firebasestorage.app"
GCS_META_BASE  = f"https://storage.googleapis.com/storage/v1/b/{STORAGE_BUCKET}/o"


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


def parse_firebase_url(url: str) -> tuple[str, str] | None:
    """Extract (storage_path, token) from a firebasestorage.googleapis.com URL."""
    if "firebasestorage.googleapis.com" not in url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        token = params.get("token", [None])[0]
        if not token:
            return None
        # path is like /v0/b/{bucket}/o/{encoded_path}
        path_part = parsed.path.split("/o/", 1)
        if len(path_part) < 2:
            return None
        storage_path = urllib.parse.unquote(path_part[1])
        return storage_path, token
    except Exception:
        return None


def patch_gcs_token(session, storage_path: str, token: str, dry_run: bool) -> bool:
    """PATCH the GCS object's custom metadata to set firebaseStorageDownloadTokens."""
    encoded = urllib.parse.quote(storage_path, safe="")
    url = f"{GCS_META_BASE}/{encoded}?alt=json"
    body = json.dumps({"metadata": {"firebaseStorageDownloadTokens": token}}).encode("utf-8")

    if dry_run:
        print(f"    Would patch: {storage_path[:70]}")
        return True

    try:
        resp = session.patch(url, data=body, headers={"Content-Type": "application/json"})
        if resp.status_code == 200:
            return True
        print(f"    PATCH failed {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"    PATCH error: {e}")
        return False


def load_manifest() -> list[str]:
    if MANIFEST_PATH.exists():
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return [l["id"] for l in data.get("lessons", [])]
    return []


def main():
    parser = argparse.ArgumentParser(description="Fix Firebase Storage download tokens on existing images")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--save",      action="store_true")
    parser.add_argument("--lesson-id", help="Single lesson ID")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run (pass --save to apply)")
    dry_run = not args.save

    if args.lesson_id:
        lesson_ids = [args.lesson_id]
    else:
        lesson_ids = load_manifest()
        if not lesson_ids:
            # Fallback: known image lessons
            lesson_ids = [
                "C-001","C-004","C-005","C-006","C-008","C-009","C-010",
                "C-012","C-013","C-014","C-015","C-016","C-017","C-018","C-019",
                "M-004","M-005","M-014","M-018","M-054",
            ]

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\nFix Image Tokens [{mode}]: {len(lesson_ids)} lesson(s)")
    print("=" * 60)

    print("Authenticating with Google...")
    from _gws_auth import get_session
    session = get_session()

    total_fixed = 0
    total_skipped = 0
    total_errors = 0

    for lesson_id in lesson_ids:
        lesson = fetch_lesson(lesson_id)
        if not lesson:
            continue

        image_blocks = [b for b in lesson.get("blocks", []) if b.get("type") == "image"]
        firebase_images = []
        for b in image_blocks:
            src = b.get("data", {}).get("src", "")
            parsed = parse_firebase_url(src)
            if parsed:
                firebase_images.append(parsed)

        if not firebase_images:
            continue

        print(f"\n  [{lesson_id}] {lesson.get('title', '')} — {len(firebase_images)} image(s)")

        for storage_path, token in firebase_images:
            ok = patch_gcs_token(session, storage_path, token, dry_run)
            if ok:
                total_fixed += 1
            else:
                total_errors += 1
            time.sleep(0.2)

    print(f"\n{'=' * 60}")
    print(f"Fixed: {total_fixed}  Errors: {total_errors}")
    if dry_run:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
