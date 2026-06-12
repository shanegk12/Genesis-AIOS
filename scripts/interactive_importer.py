"""
Genesis K-12 Interactive Importer

Scans Google Drive lesson folders for HTML5 files (.html) and zip packages (.zip),
uploads them to Firebase Storage under interactives/{lessonId}/, then creates or
updates an embed block in the Firestore lesson document via the platform API.

Setup: place HTML5 files in the Drive lesson folder (e.g. C-025/simulation.html or
C-025/game.zip). Zip files are extracted before upload.

Storage layout after import:
  interactives/{lessonId}/index.html
  interactives/{lessonId}/assets/script.js   (for zip packages)

The embed block URL will be: /api/interactive/{lessonId}/index.html

Usage:
  python scripts/interactive_importer.py --dry-run
  python scripts/interactive_importer.py --save
  python scripts/interactive_importer.py --lesson-id C-025 --save
  python scripts/interactive_importer.py --course C --save
"""

import argparse, io, json, os, sys, time, urllib.request, urllib.error, zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ─────────────────────────────────────────────────────────────────────

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
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

DRIVE_ROOT_ID   = "1aiPs5WeyJEqL4kPyK5Gt5IAUfG2TSTkH"
STORAGE_BUCKET  = "genesis-modularity.firebasestorage.app"
UPLOAD_API_BASE = f"https://storage.googleapis.com/upload/storage/v1/b/{STORAGE_BUCKET}/o"

INTERACTIVE_EXTS = {".html", ".htm", ".zip"}
EMBED_HEIGHT_DEFAULT = 560

from _gws_auth import get_session
from google.auth.transport.requests import AuthorizedSession


# ── Drive helpers ──────────────────────────────────────────────────────────────

def list_folder(session: AuthorizedSession, folder_id: str) -> list[dict]:
    resp = session.get("https://www.googleapis.com/drive/v3/files", params={
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,size)",
        "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
        "pageSize": 200,
    })
    return resp.json().get("files", [])


def download_file(session: AuthorizedSession, file_id: str) -> bytes:
    resp = session.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
    )
    return resp.content


def find_lesson_folder(session: AuthorizedSession, course_folder_id: str, lesson_id: str) -> str | None:
    files = list_folder(session, course_folder_id)
    for f in files:
        if f["name"] == lesson_id and "folder" in f.get("mimeType", ""):
            return f["id"]
    return None


def get_course_folders(session: AuthorizedSession) -> dict[str, str]:
    """Returns {'Creationeering': id, 'Mousetrap Build': id}"""
    files = list_folder(session, DRIVE_ROOT_ID)
    return {f["name"]: f["id"] for f in files if "folder" in f.get("mimeType", "")}


# ── Storage upload ─────────────────────────────────────────────────────────────

def upload_to_storage(session: AuthorizedSession, storage_path: str, content: bytes, content_type: str) -> str:
    """Upload bytes to Firebase Storage, return the storage path."""
    import urllib.parse
    encoded_path = urllib.parse.quote(storage_path, safe="")
    resp = session.post(
        f"{UPLOAD_API_BASE}?uploadType=media&name={encoded_path}",
        data=content,
        headers={"Content-Type": content_type},
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed {resp.status_code}: {resp.text[:200]}")
    return storage_path


def mime_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".html": "text/html", ".htm": "text/html",
        ".js": "application/javascript", ".mjs": "application/javascript",
        ".css": "text/css", ".json": "application/json",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
        ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
        ".ico": "image/x-icon", ".mp3": "audio/mpeg", ".wav": "audio/wav",
        ".mp4": "video/mp4", ".webm": "video/webm",
    }.get(ext, "application/octet-stream")


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
        print(f"  [WARN] fetch {lesson_id}: {e}")
        return None


def patch_lesson_blocks(lesson_id: str, blocks: list) -> bool:
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
        print(f"  [WARN] patch {lesson_id}: {e}")
        return False


# ── Core import logic ──────────────────────────────────────────────────────────

def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


def import_interactive(
    session: AuthorizedSession,
    lesson_id: str,
    filename: str,
    file_bytes: bytes,
    dry_run: bool,
) -> dict:
    """Upload file(s) to Storage and create/update embed block in the lesson."""

    ext = Path(filename).suffix.lower()
    files_to_upload: list[tuple[str, bytes, str]] = []  # (storage_path, bytes, content_type)
    entry_storage_path = f"interactives/{lesson_id}/index.html"

    if ext == ".zip":
        # Extract zip, upload all files, entry point = index.html
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                names = zf.namelist()
                # Find the top-level index.html (strip leading folder prefix if present)
                prefix = ""
                if all(n.startswith(names[0].split("/")[0] + "/") for n in names if n):
                    prefix = names[0].split("/")[0] + "/"

                for name in names:
                    if name.endswith("/"):
                        continue
                    rel = name[len(prefix):]
                    if not rel:
                        continue
                    data = zf.read(name)
                    spath = f"interactives/{lesson_id}/{rel}"
                    files_to_upload.append((spath, data, mime_for(name)))
                    if rel.lower() == "index.html":
                        entry_storage_path = spath
        except zipfile.BadZipFile as e:
            return {"lessonId": lesson_id, "status": "error", "error": f"Bad zip: {e}"}
    else:
        # Single HTML file — upload as index.html
        files_to_upload.append((entry_storage_path, file_bytes, "text/html; charset=utf-8"))

    embed_url = f"/api/interactive/{lesson_id}/index.html"
    print(f"    Files to upload: {len(files_to_upload)}")
    print(f"    Embed URL: {embed_url}")

    if not dry_run:
        for spath, data, ctype in files_to_upload:
            upload_to_storage(session, spath, data, ctype)
            print(f"    ✓ {spath}")

        # Fetch lesson and insert/replace embed block
        lesson = fetch_lesson(lesson_id)
        if not lesson:
            return {"lessonId": lesson_id, "status": "error", "error": "fetch failed"}

        blocks: list = lesson.get("blocks", [])
        embed_block = {
            "id": gen_id(),
            "type": "embed",
            "data": {"url": embed_url, "height": EMBED_HEIGHT_DEFAULT, "title": f"Interactive — {lesson_id}"},
            "meta": {"spacing": "md", "qcStatus": "pending"},
        }

        # Replace existing embed block if present, otherwise append
        replaced = False
        for i, b in enumerate(blocks):
            if b.get("type") == "embed":
                blocks[i] = embed_block
                replaced = True
                break
        if not replaced:
            blocks.append(embed_block)

        ok = patch_lesson_blocks(lesson_id, blocks)
        status = "imported" if ok else "upload_ok_patch_failed"
    else:
        status = "would_import"

    return {"lessonId": lesson_id, "status": status, "files": len(files_to_upload), "embedUrl": embed_url}


# ── Main ───────────────────────────────────────────────────────────────────────

def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lessons", data) if isinstance(data, dict) else data


def main():
    parser = argparse.ArgumentParser(description="Import HTML5 interactives from Drive into lessons")
    parser.add_argument("--dry-run",   action="store_true", help="Preview without uploading")
    parser.add_argument("--save",      action="store_true", help="Upload and patch lessons")
    parser.add_argument("--lesson-id", help="Process a single lesson")
    parser.add_argument("--course",    choices=["C", "M"], help="All lessons in course")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("No --save specified — defaulting to --dry-run")
    dry_run = not args.save

    session = get_session()
    course_folders = get_course_folders(session)
    print(f"Course folders: {list(course_folders.keys())}")

    # Determine which lessons to check
    if args.lesson_id:
        target_lessons = [args.lesson_id]
    elif args.course:
        manifest = load_manifest()
        prefix = args.course + "-"
        target_lessons = [l["id"] for l in manifest if l["id"].startswith(prefix)]
    else:
        manifest = load_manifest()
        target_lessons = [l["id"] for l in manifest]

    print(f"\nScanning {len(target_lessons)} lessons {'(DRY RUN)' if dry_run else '(SAVING)'}...")
    print("=" * 60)

    results = []
    found = 0

    for lesson_id in target_lessons:
        # Determine course folder
        prefix = lesson_id.split("-")[0]
        course_name = "Creationeering" if prefix == "C" else "Mousetrap Build"
        course_folder_id = course_folders.get(course_name)
        if not course_folder_id:
            continue

        lesson_folder_id = find_lesson_folder(session, course_folder_id, lesson_id)
        if not lesson_folder_id:
            continue

        files = list_folder(session, lesson_folder_id)
        interactive_files = [f for f in files if Path(f["name"]).suffix.lower() in INTERACTIVE_EXTS]

        if not interactive_files:
            continue

        found += 1
        for ifile in interactive_files:
            print(f"\n  {lesson_id} — {ifile['name']} ({int(ifile.get('size', 0)) // 1024}KB)")
            if not dry_run:
                file_bytes = download_file(session, ifile["id"])
            else:
                file_bytes = b""  # don't download in dry-run
            result = import_interactive(session, lesson_id, ifile["name"], file_bytes, dry_run)
            results.append(result)
            print(f"    → {result['status']}")
        time.sleep(0.5)

    print(f"\n{'='*60}")
    print(f"Found {found} lessons with interactive files.")
    imported = sum(1 for r in results if r["status"] == "imported")
    print(f"Imported: {imported}, dry-run previewed: {len(results) - imported}")

    if found == 0:
        print("\nNo HTML5 files found in Drive lesson folders.")
        print("To add an interactive:")
        print("  1. Upload your .html or .zip file to the lesson's Drive folder")
        print("     e.g. Creationeering / C-025 / simulation.html")
        print("  2. Re-run this script with --save")


if __name__ == "__main__":
    main()
