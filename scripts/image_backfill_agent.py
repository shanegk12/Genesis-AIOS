"""
Genesis K-12 Image Backfill Agent

Reads [IMAGE NEEDED: description] placeholders from Firestore lessons,
matches them to images in Google Drive (one folder per lesson ID), uploads
to Firebase Storage, then updates the lesson blocks with real URLs.

Drive structure:
  Homeschool MS: Curriculum/
    Creationeering/
      C-025/
        image-title.png
    Mousetrap Build/
      M-010/
        image-title.png

Usage:
  python scripts/image_backfill_agent.py --dry-run          # preview matches
  python scripts/image_backfill_agent.py                    # live upload + patch
  python scripts/image_backfill_agent.py --lesson-id C-025  # one lesson
  python scripts/image_backfill_agent.py --course C         # all Creationeering
  python scripts/image_backfill_agent.py --course M         # all Mousetrap
"""

import argparse, html, json, os, re, sys, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

# Force UTF-8 on Windows so Unicode in placeholder text / print arrows don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"

STORAGE_BUCKET = "genesis-modularity.firebasestorage.app"

# Drive folder IDs — root is hardcoded, subfolders found by name under root
DRIVE_ROOT_ID    = "1aiPs5WeyJEqL4kPyK5Gt5IAUfG2TSTkH"
DRIVE_CREAT_NAME = "Creationeering"
DRIVE_MOUSE_NAME = "Mousetrap Build"

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
REPORTS_PATH  = os.path.join(os.path.dirname(__file__), "qc_reports.json")
LOG_PATH      = os.path.join(os.path.dirname(__file__), "image_backfill_log.json")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = (f"https://generativelanguage.googleapis.com/v1beta"
                f"/models/{GEMINI_MODEL}:generateContent")

IMAGE_NEEDED_RE = re.compile(r'\[IMAGE NEEDED:\s*([^\]]+)\]', re.IGNORECASE)


# ── Env / auth ────────────────────────────────────────────────────────────────

def _load_env() -> dict:
    env = {}
    for name in [".env", ".env.local"]:
        path = os.path.join(os.path.dirname(__file__), "..", name)
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip().strip('"\'')
    return env


# ── Drive helpers (REST via AuthorizedSession) ────────────────────────────────

def _find_folder(session, name: str, parent_id: str | None = None) -> str | None:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    params = urllib.parse.urlencode({
        "q": q, "fields": "files(id,name)", "pageSize": 5,
        "includeItemsFromAllDrives": "true", "supportsAllDrives": "true",
    })
    resp = session.get(f"https://www.googleapis.com/drive/v3/files?{params}")
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def _list_images_in_folder(session, folder_id: str) -> list[dict]:
    """Return list of {id, name, mimeType} for image files in folder."""
    q = f"'{folder_id}' in parents and trashed=false and (mimeType contains 'image/')"
    params = urllib.parse.urlencode({
        "q": q,
        "fields": "files(id,name,mimeType,size)",
        "pageSize": 100,
        "includeItemsFromAllDrives": "true", "supportsAllDrives": "true",
    })
    resp = session.get(f"https://www.googleapis.com/drive/v3/files?{params}")
    resp.raise_for_status()
    return resp.json().get("files", [])


def _download_file(session, file_id: str) -> bytes:
    resp = session.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
        stream=True,
    )
    resp.raise_for_status()
    return resp.content


# ── Firebase Storage upload (via platform /api/admin/images) ─────────────────

def _upload_to_storage(session, lesson_id: str, filename: str,
                       data: bytes, mime_type: str) -> str:
    """Upload image via the platform's /api/admin/images endpoint.

    This uses Firebase Admin SDK on the server (file.save + file.makePublic),
    which correctly handles GCS Uniform Bucket-Level Access.
    Returns the public storage.googleapis.com URL.
    """
    import base64

    payload = json.dumps({
        "lessonId": lesson_id,
        "filename": filename,
        "mimeType": mime_type,
        "dataBase64": base64.b64encode(data).decode("utf-8"),
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/images",
        data=payload,
        headers={
            "Authorization": f"Bearer {PLATFORM_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Image upload HTTP {e.code}: {body}") from e

    if not result.get("ok"):
        raise RuntimeError(f"Image upload failed: {result}")

    return result["url"]


# ── Platform API ──────────────────────────────────────────────────────────────

def _fetch_lesson(lesson_id: str) -> dict | None:
    url = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {PLATFORM_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  Fetch error {lesson_id}: {e}")
        return None


def _save_lesson_html(lesson_id: str, html: str) -> bool:
    url     = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    payload = json.dumps({"action": "parse-html", "html": html}).encode()
    req     = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            print(f"    Saved: {result.get('blockCount', '?')} blocks")
            return result.get("ok", False)
    except Exception as e:
        print(f"  Save error {lesson_id}: {e}")
        return False


# ── Gemini matching ───────────────────────────────────────────────────────────

def _match_images_to_placeholders(
    api_key: str,
    lesson_id: str,
    image_names: list[str],
    placeholders: list[str],
) -> dict[int, str]:
    """
    Returns {placeholder_index: image_filename} mapping.

    Strategy: sort Drive images by Part number (Part_1, Part_2, …), deduplicate,
    exclude Cover.png, then assign positionally to placeholders.
    This is reliable because the curriculum images are named after lesson parts
    which correspond to the order placeholders appear in the content.
    """
    if not image_names or not placeholders:
        return {}

    # Deduplicate while preserving order
    seen = set()
    unique = [n for n in image_names if not (n in seen or seen.add(n))]

    # Separate Part_N images from others, exclude Cover.png
    part_map: dict[int, str] = {}
    extras: list[str] = []
    for name in unique:
        if name.lower() == "cover.png":
            continue
        m = re.match(r'Part_(\d+)_', name, re.IGNORECASE)
        if m:
            part_num = int(m.group(1))
            if part_num not in part_map:   # first occurrence wins
                part_map[part_num] = name
        else:
            extras.append(name)

    ordered = [part_map[k] for k in sorted(part_map)] + extras

    if not ordered:
        return {}

    # Assign positionally — Part_1 → placeholder 0, Part_2 → placeholder 1, …
    return {i: img for i, img in enumerate(ordered) if i < len(placeholders)}


# ── Per-lesson processing ─────────────────────────────────────────────────────

def process_lesson(
    lesson_id: str,
    session,
    course_folder_id: str,
    api_key: str,
    dry_run: bool,
    log: dict,
) -> str:
    """Returns status: 'done' | 'skipped' | 'no_folder' | 'no_images' | 'error'"""

    # Find lesson folder in Drive
    lesson_folder_id = _find_folder(session, lesson_id, course_folder_id)
    if not lesson_folder_id:
        print(f"  [{lesson_id}] No Drive folder — skipping")
        return "no_folder"

    # List images in Drive folder
    drive_images = _list_images_in_folder(session, lesson_folder_id)
    if not drive_images:
        print(f"  [{lesson_id}] No images in Drive folder — skipping")
        return "no_images"

    image_names = [img["name"] for img in drive_images]
    print(f"  [{lesson_id}] {len(image_names)} image(s) in Drive: {image_names}")

    # Fetch lesson content
    lesson = _fetch_lesson(lesson_id)
    if not lesson:
        return "error"

    # ── Mode A: block-based (QC-extracted image blocks with empty src) ──────────
    blocks = lesson.get("blocks", [])
    empty_image_blocks = [
        (i, b) for i, b in enumerate(blocks)
        if b.get("type") == "image" and not b.get("data", {}).get("src", "")
    ]

    if empty_image_blocks:
        placeholders = [b.get("data", {}).get("caption", "") for _, b in empty_image_blocks]
        print(f"    {len(placeholders)} empty image block(s): {[p[:50] for p in placeholders]}")

        matches = _match_images_to_placeholders(api_key, lesson_id, image_names, placeholders)
        if not matches:
            print(f"    No Drive images matched")
            return "skipped"

        print(f"    Matches: { {k: v for k, v in matches.items()} }")
        if dry_run:
            return "done"

        lesson_log = []
        updated_blocks = [dict(b) for b in blocks]

        for placeholder_idx, drive_filename in matches.items():
            _, orig_block = empty_image_blocks[placeholder_idx]
            block_index   = next(i for i, b in enumerate(blocks) if b is orig_block)
            drive_file    = next((f for f in drive_images if f["name"] == drive_filename), None)
            if not drive_file:
                print(f"    Image not found: {drive_filename}")
                continue
            try:
                img_data   = _download_file(session, drive_file["id"])
                mime_type  = drive_file.get("mimeType", "image/jpeg")
                storage_url = _upload_to_storage(None, lesson_id, drive_filename, img_data, mime_type)
                print(f"    Uploaded: {drive_filename} → {storage_url}")

                updated_blocks[block_index] = {
                    **orig_block,
                    "data": {**orig_block.get("data", {}), "src": storage_url},
                    "meta": {**orig_block.get("meta", {}), "qcStatus": "pending"},
                }
                lesson_log.append({"placeholder": placeholders[placeholder_idx], "url": storage_url})
            except Exception as e:
                print(f"    Error processing {drive_filename}: {e}")
                continue

        if not lesson_log:
            return "skipped"

        # PATCH blocks directly — no HTML re-parse needed
        patch_payload = json.dumps({"blocks": updated_blocks}).encode("utf-8")
        patch_req = urllib.request.Request(
            f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
            data=patch_payload,
            headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
            method="PATCH",
        )
        try:
            with urllib.request.urlopen(patch_req, timeout=30) as resp:
                result = json.loads(resp.read())
                ok = result.get("ok", False)
                print(f"    Patched blocks: ok={ok}")
        except Exception as e:
            print(f"    PATCH error: {e}")
            ok = False

        if ok:
            log[lesson_id] = {"status": "done", "images": lesson_log,
                               "at": datetime.now(timezone.utc).isoformat()}
            return "done"
        return "error"

    # ── Mode B: HTML-based ([IMAGE NEEDED: ...] text placeholders, legacy) ───────
    content = lesson.get("content", "")
    if not content:
        print(f"    No content in lesson")
        return "skipped"

    placeholders = IMAGE_NEEDED_RE.findall(content)
    if not placeholders:
        print(f"    No [IMAGE NEEDED] placeholders or empty image blocks found")
        return "skipped"

    print(f"    {len(placeholders)} HTML placeholder(s): {[p[:50] for p in placeholders]}")

    matches = _match_images_to_placeholders(api_key, lesson_id, image_names, placeholders)
    if not matches:
        print(f"    No matches found")
        return "skipped"

    print(f"    Matches: { {k: v for k, v in matches.items()} }")

    if dry_run:
        return "done"

    updated_content = content
    lesson_log = []

    for placeholder_idx, drive_filename in matches.items():
        if placeholder_idx >= len(placeholders):
            continue

        placeholder_desc = placeholders[placeholder_idx]
        drive_file = next((f for f in drive_images if f["name"] == drive_filename), None)
        if not drive_file:
            print(f"    Image not found: {drive_filename}")
            continue

        try:
            img_data  = _download_file(session, drive_file["id"])
            mime_type = drive_file.get("mimeType", "image/jpeg")
            storage_url = _upload_to_storage(None, lesson_id, drive_filename, img_data, mime_type)
            print(f"    Uploaded: {drive_filename} → {storage_url}")

            placeholder_text = f"[IMAGE NEEDED: {placeholder_desc}]"
            img_tag = f'<img src="{storage_url}" alt="{placeholder_desc}" style="width:100%;border-radius:6px;display:block;margin:12px auto">'
            updated_content = updated_content.replace(f"<p><em>{placeholder_text}</em></p>", img_tag, 1)
            updated_content = updated_content.replace(f"<p>{placeholder_text}</p>", img_tag, 1)
            lesson_log.append({"placeholder": placeholder_desc, "url": storage_url})
        except Exception as e:
            print(f"    Error processing {drive_filename}: {e}")
            continue

    if updated_content == content:
        idx = content.find("[IMAGE NEEDED")
        snippet = content[max(0, idx-20):idx+120] if idx >= 0 else "(not found)"
        print(f"    Content unchanged — snippet: {repr(snippet)}")
        return "skipped"

    ok = _save_lesson_html(lesson_id, updated_content)
    if ok:
        log[lesson_id] = {"status": "done", "images": lesson_log,
                           "at": datetime.now(timezone.utc).isoformat()}
        return "done"
    return "error"


# ── Log I/O ───────────────────────────────────────────────────────────────────

def _load_log() -> dict:
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_log(log: dict):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lesson-id", help="Process a single lesson")
    parser.add_argument("--course", choices=["C", "M"],
                        help="Process one course: C=Creationeering, M=Mousetrap")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env     = _load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found")
        sys.exit(1)

    print("Authenticating with Google...")
    from _gws_auth import get_session
    session = get_session()

    # Locate Drive folders — root ID is hardcoded, subfolders by name
    creat_id = _find_folder(session, DRIVE_CREAT_NAME, DRIVE_ROOT_ID)
    mouse_id = _find_folder(session, DRIVE_MOUSE_NAME, DRIVE_ROOT_ID)
    print(f"Creationeering folder: {creat_id}")
    print(f"Mousetrap Build folder: {mouse_id}")

    # Build lesson list
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    lessons = [l for l in manifest["lessons"] if l["status"] == "done"]
    if args.lesson_id:
        lessons = [l for l in lessons if l["id"] == args.lesson_id]
    elif args.course == "C":
        lessons = [l for l in lessons if l["id"].startswith("C-")]
    elif args.course == "M":
        lessons = [l for l in lessons if l["id"].startswith("M-")]

    print(f"\nImage Backfill: {len(lessons)} lessons{' [DRY RUN]' if args.dry_run else ''}...\n")

    log     = _load_log()
    counts  = {"done": 0, "skipped": 0, "no_folder": 0, "no_images": 0, "error": 0}

    for lesson in lessons:
        lid    = lesson["id"]
        prefix = "C-" if lid.startswith("C-") else "M-"
        course_folder_id = creat_id if prefix == "C-" else mouse_id

        if not course_folder_id:
            print(f"  [{lid}] Course folder not found in Drive — skipping")
            counts["no_folder"] += 1
            continue

        status = process_lesson(
            lid, session, course_folder_id,
            api_key, args.dry_run, log
        )
        counts[status] = counts.get(status, 0) + 1
        time.sleep(0.5)

    if not args.dry_run:
        _save_log(log)

    print(f"\n=== Image Backfill {'Dry Run ' if args.dry_run else ''}Complete ===")
    print(f"  Done      : {counts['done']}")
    print(f"  No folder : {counts['no_folder']}")
    print(f"  No images : {counts['no_images']}")
    print(f"  Skipped   : {counts['skipped']}")
    print(f"  Errors    : {counts['error']}")


if __name__ == "__main__":
    main()
