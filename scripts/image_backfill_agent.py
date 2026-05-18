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

import argparse, json, os, re, sys, time, urllib.request, urllib.error, mimetypes
from datetime import datetime, timezone

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


def _get_drive_service():
    """Build Google Drive API service using ADC + oauth-client.json."""
    try:
        from googleapiclient.discovery import build
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing packages. Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib")
        sys.exit(1)

    SCOPES = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/devstorage.read_write",
    ]
    token_path  = os.path.join(os.path.dirname(__file__), "..", "drive-token.json")
    client_path = os.path.join(os.path.dirname(__file__), "..", "oauth-client.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_path):
                print(f"oauth-client.json not found at {client_path}")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds), creds


def _get_storage_service(creds):
    from googleapiclient.discovery import build
    return build("storage", "v1", credentials=creds)


# ── Drive helpers ─────────────────────────────────────────────────────────────

def _find_folder(drive, name: str, parent_id: str | None = None) -> str | None:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    result = drive.files().list(q=q, fields="files(id,name)", pageSize=5).execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def _list_images_in_folder(drive, folder_id: str) -> list[dict]:
    """Return list of {id, name, mimeType} for image files in folder."""
    q = (f"'{folder_id}' in parents and trashed=false and "
         f"(mimeType contains 'image/')")
    result = drive.files().list(
        q=q,
        fields="files(id,name,mimeType,size)",
        pageSize=100,
    ).execute()
    return result.get("files", [])


def _download_file(drive, file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    import io
    request  = drive.files().get_media(fileId=file_id)
    buffer   = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


# ── Firebase Storage upload ───────────────────────────────────────────────────

def _upload_to_storage(storage_svc, lesson_id: str, filename: str,
                       data: bytes, mime_type: str) -> str:
    """Upload bytes to Firebase Storage, return public GCS URL.

    Uses images/ path (same as block editor uploads) with publicRead ACL.
    Firebase security rules gate Firebase SDK access only — direct GCS URLs
    are publicly accessible when the ACL is set to publicRead.
    """
    from googleapiclient.http import MediaInMemoryUpload
    import urllib.parse

    object_name = f"images/{lesson_id}/{filename}"
    media = MediaInMemoryUpload(data, mimetype=mime_type, resumable=False)

    storage_svc.objects().insert(
        bucket=STORAGE_BUCKET,
        name=object_name,
        media_body=media,
        predefinedAcl="publicRead",
    ).execute()

    encoded = urllib.parse.quote(object_name, safe="")
    return f"https://storage.googleapis.com/{STORAGE_BUCKET}/{encoded}"


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
    Uses Gemini flash (fast + cheap) since this is pure matching, no generation.
    """
    if not image_names or not placeholders:
        return {}

    # Simple 1:1 case — no need to call Gemini
    if len(image_names) == 1 and len(placeholders) == 1:
        return {0: image_names[0]}

    prompt = f"""You are matching image files to placeholder slots in a lesson.

Lesson ID: {lesson_id}

Image files available (from Google Drive):
{json.dumps(image_names, indent=2)}

Placeholder descriptions (from lesson content):
{json.dumps([f"{i}: {p}" for i, p in enumerate(placeholders)], indent=2)}

Return a JSON object mapping placeholder index (as string) to image filename.
Only include placeholders that have a clear match. If an image has no match, omit it.
Example: {{"0": "newton-second-law.png", "2": "free-body-diagram.png"}}
Return ONLY the JSON object, no explanation."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512},
    }).encode()

    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = re.sub(r'^```json?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        raw  = json.loads(text)
        return {int(k): v for k, v in raw.items()}
    except Exception as e:
        print(f"    Match error: {e}")
        return {}


# ── Per-lesson processing ─────────────────────────────────────────────────────

def process_lesson(
    lesson_id: str,
    drive,
    storage_svc,
    course_folder_id: str,
    api_key: str,
    dry_run: bool,
    log: dict,
) -> str:
    """Returns status: 'done' | 'skipped' | 'no_folder' | 'no_images' | 'error'"""

    # Find lesson folder in Drive
    lesson_folder_id = _find_folder(drive, lesson_id, course_folder_id)
    if not lesson_folder_id:
        print(f"  [{lesson_id}] No Drive folder — skipping")
        return "no_folder"

    # List images in Drive folder
    drive_images = _list_images_in_folder(drive, lesson_folder_id)
    if not drive_images:
        print(f"  [{lesson_id}] No images in Drive folder — skipping")
        return "no_images"

    image_names = [img["name"] for img in drive_images]
    print(f"  [{lesson_id}] {len(image_names)} image(s) in Drive: {image_names}")

    # Fetch lesson content
    lesson = _fetch_lesson(lesson_id)
    if not lesson:
        return "error"

    content = lesson.get("content", "")
    if not content:
        print(f"    No content in lesson")
        return "skipped"

    # Find all [IMAGE NEEDED: ...] placeholders
    placeholders = IMAGE_NEEDED_RE.findall(content)
    if not placeholders:
        print(f"    No [IMAGE NEEDED] placeholders found")
        # Still might have image blocks with empty/placeholder src — skip for now
        return "skipped"

    print(f"    {len(placeholders)} placeholder(s): {[p[:50] for p in placeholders]}")

    # Match images to placeholders
    matches = _match_images_to_placeholders(api_key, lesson_id, image_names, placeholders)
    if not matches:
        print(f"    No matches found")
        return "skipped"

    print(f"    Matches: { {k: v for k, v in matches.items()} }")

    if dry_run:
        return "done"

    # Download, upload to Storage, and replace in HTML
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
            # Download from Drive
            img_data  = _download_file(drive, drive_file["id"])
            mime_type = drive_file.get("mimeType", "image/jpeg")

            # Upload to Firebase Storage
            storage_url = _upload_to_storage(
                storage_svc, lesson_id, drive_filename, img_data, mime_type
            )
            print(f"    Uploaded: {drive_filename} → {storage_url}")

            # Replace placeholder in HTML
            placeholder_text = f"[IMAGE NEEDED: {placeholder_desc}]"
            img_tag = f'<img src="{storage_url}" alt="{placeholder_desc}" style="width:100%;border-radius:6px;display:block;margin:12px auto">'
            updated_content = updated_content.replace(
                f"<p><em>{placeholder_text}</em></p>",
                img_tag,
                1,
            )
            # Also try without em tags
            updated_content = updated_content.replace(
                f"<p>{placeholder_text}</p>",
                img_tag,
                1,
            )

            lesson_log.append({"placeholder": placeholder_desc, "url": storage_url})

        except Exception as e:
            print(f"    Error processing {drive_filename}: {e}")
            continue

    if updated_content == content:
        print(f"    Content unchanged (placeholder text mismatch?)")
        return "skipped"

    # Save updated content → re-parses to blocks
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
    drive, creds = _get_drive_service()
    storage_svc  = _get_storage_service(creds)

    # Locate Drive folders — root ID is hardcoded, subfolders by name
    creat_id = _find_folder(drive, DRIVE_CREAT_NAME, DRIVE_ROOT_ID)
    mouse_id = _find_folder(drive, DRIVE_MOUSE_NAME, DRIVE_ROOT_ID)
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
            lid, drive, storage_svc, course_folder_id,
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
