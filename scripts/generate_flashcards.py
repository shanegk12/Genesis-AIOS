"""
Genesis K-12 Flashcard Generator

Fetches lessons with vocab blocks from the platform, generates self-contained
HTML5 flashcard widgets, and uploads them to the correct Google Drive lesson
folder so interactive_importer.py can pick them up.

Usage:
  python scripts/generate_flashcards.py --dry-run        # preview only
  python scripts/generate_flashcards.py --save           # generate + upload
  python scripts/generate_flashcards.py --lesson-id C-025 --save
  python scripts/generate_flashcards.py --course C --save
  python scripts/generate_flashcards.py --limit 15 --save
"""

import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))
from _gws_auth import get_session

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
LOG_PATH      = Path(__file__).parent / "interactive_flashcards_log.json"

DRIVE_ROOT_ID = "1aiPs5WeyJEqL4kPyK5Gt5IAUfG2TSTkH"


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
        if e.code == 404:
            return None
        print(f"  [WARN] fetch {lesson_id}: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  [WARN] fetch {lesson_id}: {e}")
        return None


def extract_vocab_items(blocks: list) -> list[dict]:
    """Merge all vocab block items across a lesson into one flat list.

    Strips placeholder header rows (term='Term', definition='Definition') that
    some vocab blocks include as column-header sentinels.
    """
    items = []
    for block in blocks:
        if block.get("type") == "vocab":
            data = block.get("data", {})
            block_items = data.get("items", [])
            for item in block_items:
                term = item.get("term", "").strip()
                definition = item.get("definition", "").strip()
                if not term or not definition:
                    continue
                # Skip placeholder header rows
                if term.lower() == "term" and definition.lower() == "definition":
                    continue
                items.append({"term": term, "definition": definition})
    return items


# ── HTML5 Flashcard Generator ──────────────────────────────────────────────────

def generate_flashcard_html(lesson_id: str, title: str, items: list[dict]) -> str:
    """Generate a self-contained HTML5 flashcard widget."""
    terms_json = json.dumps(items, ensure_ascii=False)
    term_count = len(items)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(title)} — Vocabulary</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    /* No scrollbar — sized to fit the 520px embed container */
    html, body {{ height: 100%; overflow: hidden; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f7fb;
      display: flex;
      flex-direction: column;
      align-items: center;
      height: 100%;
      padding: 16px;
      color: #1B2A5C;
    }}

    .header {{
      text-align: center;
      margin-bottom: 12px;
      width: 100%;
      max-width: 560px;
    }}

    .header h1 {{
      font-size: 1rem;
      font-weight: 700;
      color: #1B2A5C;
      letter-spacing: 0.02em;
      line-height: 1.3;
    }}

    .counter {{
      font-size: 0.8rem;
      color: #6b7a99;
      margin-top: 4px;
    }}

    /* Progress bar */
    .progress-bar {{
      width: 100%;
      max-width: 560px;
      height: 4px;
      background: #dde3f0;
      border-radius: 2px;
      margin-bottom: 16px;
      overflow: hidden;
    }}

    .progress-fill {{
      height: 100%;
      background: #C9A84C;
      border-radius: 2px;
      transition: width 0.3s ease;
    }}

    /* Card scene */
    .card-scene {{
      width: 100%;
      max-width: 560px;
      height: 220px;
      perspective: 1000px;
      cursor: pointer;
      margin-bottom: 16px;
    }}

    .card-inner {{
      position: relative;
      width: 100%;
      height: 100%;
      transform-style: preserve-3d;
      transition: transform 0.45s ease;
    }}

    .card-scene.flipped .card-inner {{
      transform: rotateY(180deg);
    }}

    .card-face {{
      position: absolute;
      inset: 0;
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 24px 28px;
      backface-visibility: hidden;
      -webkit-backface-visibility: hidden;
      box-shadow: 0 4px 16px rgba(27, 42, 92, 0.12);
    }}

    .card-front {{
      background: #1B2A5C;
      color: #ffffff;
    }}

    .card-back {{
      background: #ffffff;
      color: #1B2A5C;
      border: 2px solid #C9A84C;
      transform: rotateY(180deg);
    }}

    .card-label {{
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      opacity: 0.6;
      margin-bottom: 10px;
    }}

    .card-front .card-label {{ color: #C9A84C; opacity: 1; }}
    .card-back  .card-label {{ color: #1B2A5C; opacity: 0.5; }}

    .card-text {{
      font-size: 1.15rem;
      font-weight: 600;
      text-align: center;
      line-height: 1.4;
    }}

    .card-hint {{
      font-size: 0.7rem;
      margin-top: 14px;
      opacity: 0.45;
      font-style: italic;
    }}

    /* Controls */
    .controls {{
      display: flex;
      gap: 12px;
      align-items: center;
      width: 100%;
      max-width: 560px;
      justify-content: center;
    }}

    button {{
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 9px 20px;
      border: none;
      border-radius: 8px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s, transform 0.1s;
    }}

    button:active {{ transform: scale(0.97); }}

    .btn-nav {{
      background: #1B2A5C;
      color: #ffffff;
      min-width: 100px;
    }}

    .btn-nav:hover {{ background: #243870; }}
    .btn-nav:disabled {{ background: #b0b8d0; cursor: not-allowed; transform: none; }}

    .btn-flip {{
      background: #C9A84C;
      color: #1B2A5C;
      min-width: 110px;
    }}

    .btn-flip:hover {{ background: #d4b55e; }}

    /* Shuffle toggle */
    .shuffle-row {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 12px;
      font-size: 0.78rem;
      color: #6b7a99;
    }}

    .shuffle-row input[type=checkbox] {{
      accent-color: #C9A84C;
      width: 15px;
      height: 15px;
      cursor: pointer;
    }}

    .shuffle-row label {{ cursor: pointer; user-select: none; }}

    /* Footer — pinned at bottom, minimal height */
    footer {{
      margin-top: 8px;
      padding-top: 6px;
      font-size: 0.65rem;
      color: #9aa0b8;
      text-align: center;
      flex-shrink: 0;
    }}

    @media (max-height: 580px) {{
      .card-scene {{ height: 180px; }}
    }}
  </style>
</head>
<body>

  <div class="header">
    <h1>{_esc(title)}</h1>
    <div class="counter" id="counter">Card 1 of {term_count}</div>
  </div>

  <div class="progress-bar">
    <div class="progress-fill" id="progressFill" style="width: {round(100/term_count, 1) if term_count else 0}%"></div>
  </div>

  <div class="card-scene" id="cardScene" onclick="flipCard()">
    <div class="card-inner" id="cardInner">
      <div class="card-face card-front" id="cardFront">
        <div class="card-label">Term</div>
        <div class="card-text" id="termText"></div>
        <div class="card-hint">Click to reveal definition</div>
      </div>
      <div class="card-face card-back" id="cardBack">
        <div class="card-label">Definition</div>
        <div class="card-text" id="defText"></div>
      </div>
    </div>
  </div>

  <div class="controls">
    <button class="btn-nav" id="prevBtn" onclick="navigate(-1)" disabled>&#8592; Previous</button>
    <button class="btn-flip" onclick="flipCard()">Flip</button>
    <button class="btn-nav" id="nextBtn" onclick="navigate(1)">Next &#8594;</button>
  </div>

  <div class="shuffle-row">
    <input type="checkbox" id="shuffleCheck" onchange="onShuffleToggle()">
    <label for="shuffleCheck">Shuffle cards</label>
  </div>

  <footer>Genesis K-12 Academy &nbsp;|&nbsp; {_esc(lesson_id)} Vocabulary &nbsp;|&nbsp; {term_count} term{"s" if term_count != 1 else ""}</footer>

  <script>
    const TERMS_ORIGINAL = {terms_json};

    let terms = [...TERMS_ORIGINAL];
    let idx = 0;
    let isFlipped = false;

    function shuffle(arr) {{
      for (let i = arr.length - 1; i > 0; i--) {{
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
      }}
      return arr;
    }}

    function showCard() {{
      const t = terms[idx];
      document.getElementById('termText').textContent = t.term;
      document.getElementById('defText').textContent = t.definition;

      // Reset to front face
      isFlipped = false;
      document.getElementById('cardScene').classList.remove('flipped');

      // Update counter
      document.getElementById('counter').textContent =
        'Card ' + (idx + 1) + ' of ' + terms.length;

      // Update progress bar
      const pct = ((idx + 1) / terms.length * 100).toFixed(1);
      document.getElementById('progressFill').style.width = pct + '%';

      // Update buttons
      document.getElementById('prevBtn').disabled = (idx === 0);
      document.getElementById('nextBtn').disabled = (idx === terms.length - 1);
    }}

    function flipCard() {{
      isFlipped = !isFlipped;
      document.getElementById('cardScene').classList.toggle('flipped', isFlipped);
    }}

    function navigate(dir) {{
      const next = idx + dir;
      if (next >= 0 && next < terms.length) {{
        idx = next;
        showCard();
      }}
    }}

    function onShuffleToggle() {{
      const checked = document.getElementById('shuffleCheck').checked;
      if (checked) {{
        terms = shuffle([...TERMS_ORIGINAL]);
      }} else {{
        terms = [...TERMS_ORIGINAL];
      }}
      idx = 0;
      showCard();
    }}

    // Keyboard navigation
    document.addEventListener('keydown', function(e) {{
      if (e.key === 'ArrowLeft')  navigate(-1);
      if (e.key === 'ArrowRight') navigate(1);
      if (e.key === ' ' || e.key === 'Enter') {{ e.preventDefault(); flipCard(); }}
    }});

    // Init
    showCard();
  </script>
</body>
</html>"""
    return html


def _esc(text: str) -> str:
    """HTML-escape a string for safe inclusion in attributes/content."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )


# ── Drive helpers ──────────────────────────────────────────────────────────────

def get_course_folders(session) -> dict[str, str]:
    resp = session.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{DRIVE_ROOT_ID}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
            "fields": "files(id,name)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": 50,
        },
    )
    resp.raise_for_status()
    return {f["name"]: f["id"] for f in resp.json().get("files", [])}


def get_all_lesson_folders(session) -> dict[str, str]:
    """
    Return a flat dict mapping lesson_id -> Drive folder_id for ALL lessons in
    both Creationeering and Mousetrap Build, using paginated listing so nothing
    is missed.
    """
    course_folders = get_course_folders(session)
    lesson_folders: dict[str, str] = {}

    for course_name, course_folder_id in course_folders.items():
        if course_name not in ("Creationeering", "Mousetrap Build"):
            continue
        page_token = None
        while True:
            params = {
                "q": f"'{course_folder_id}' in parents and trashed=false",
                "fields": "nextPageToken,files(id,name,mimeType)",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "pageSize": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            resp = session.get("https://www.googleapis.com/drive/v3/files", params=params)
            resp.raise_for_status()
            data = resp.json()
            for f in data.get("files", []):
                if "folder" in f.get("mimeType", ""):
                    lesson_folders[f["name"]] = f["id"]
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    return lesson_folders


def find_lesson_folder(session, course_folder_id: str, lesson_id: str) -> str | None:
    resp = session.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{course_folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder' and name='{lesson_id}'",
            "fields": "files(id,name)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": 10,
        },
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def get_course_folder_for_lesson(session, lesson_id: str) -> str | None:
    """Return the parent course folder ID for a lesson based on its ID prefix."""
    course_folders = get_course_folders(session)
    prefix = "Creationeering" if lesson_id.startswith("C-") else "Mousetrap Build"
    return course_folders.get(prefix)


def create_lesson_folder(session, lesson_id: str) -> str | None:
    """Create a Drive folder named lesson_id inside the correct course folder. Returns new folder ID."""
    course_folder_id = get_course_folder_for_lesson(session, lesson_id)
    if not course_folder_id:
        print(f"  [WARN] Cannot find course folder for {lesson_id} — skipping folder creation")
        return None
    import json as _json
    meta = _json.dumps({"name": lesson_id, "mimeType": "application/vnd.google-apps.folder", "parents": [course_folder_id]})
    resp = session.post(
        "https://www.googleapis.com/drive/v3/files",
        params={"supportsAllDrives": "true"},
        data=meta.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    folder_id = resp.json().get("id")
    print(f"  [CREATED] Drive folder {lesson_id} → {folder_id}")
    return folder_id


def list_folder_files(session, folder_id: str) -> list[dict]:
    resp = session.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "files(id,name,mimeType)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": 100,
        },
    )
    resp.raise_for_status()
    return resp.json().get("files", [])


def upload_or_update_file(session, folder_id: str, filename: str, content: str) -> str:
    """
    Upload content as filename in folder_id. If a file with the same name already
    exists, PATCH it (update content) instead of creating a duplicate.
    Returns 'created' or 'updated'.
    """
    content_bytes = content.encode("utf-8")
    boundary = "===boundary==="
    content_type_header = f"multipart/related; boundary={boundary}"

    # Check if file already exists
    existing_files = list_folder_files(session, folder_id)
    existing = next((f for f in existing_files if f["name"] == filename), None)

    if existing:
        # Update existing file via PATCH
        file_id = existing["id"]
        resp = session.patch(
            f"https://www.googleapis.com/upload/drive/v3/files/{file_id}",
            params={"uploadType": "media", "supportsAllDrives": "true"},
            data=content_bytes,
            headers={"Content-Type": "text/html; charset=UTF-8"},
        )
        resp.raise_for_status()
        return "updated"
    else:
        # Create new file via multipart upload
        meta = json.dumps({"name": filename, "parents": [folder_id]})
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{meta}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: text/html; charset=UTF-8\r\n\r\n"
        ).encode("utf-8") + content_bytes + f"\r\n--{boundary}--".encode("utf-8")

        resp = session.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "multipart", "supportsAllDrives": "true"},
            data=body,
            headers={"Content-Type": content_type_header},
        )
        resp.raise_for_status()
        return "created"


# ── Main ───────────────────────────────────────────────────────────────────────

def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lessons", data) if isinstance(data, dict) else data


def sort_lesson_id(lid: str) -> tuple:
    """Sort C- before M-, then numerically by number."""
    prefix, _, num = lid.partition("-")
    order = 0 if prefix == "C" else 1
    try:
        return (order, int(num))
    except ValueError:
        return (order, 9999)


def main():
    parser = argparse.ArgumentParser(description="Generate HTML5 flashcards and upload to Drive")
    parser.add_argument("--dry-run",   action="store_true", help="Preview without uploading")
    parser.add_argument("--save",      action="store_true", help="Generate + upload to Drive")
    parser.add_argument("--lesson-id", help="Process a single lesson")
    parser.add_argument("--course",    choices=["C", "M"], help="All lessons in course")
    parser.add_argument("--limit",     type=int, default=0, help="Cap on number of lessons with Drive folders (0 = all)")
    parser.add_argument("--all-vocab", action="store_true", help="Include lessons without Drive folders (marks as skipped)")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("No --save specified — defaulting to --dry-run")
    dry_run = not args.save

    # ── Load manifest and filter ──
    manifest = load_manifest()
    all_ids = [l["id"] for l in manifest]

    if args.lesson_id:
        target_ids = [args.lesson_id]
    elif args.course:
        prefix = args.course + "-"
        target_ids = [lid for lid in all_ids if lid.startswith(prefix)]
    else:
        target_ids = all_ids

    target_ids = sorted(target_ids, key=sort_lesson_id)

    # ── Fetch lessons and filter for vocab ──
    print(f"\nGenesis K-12 Flashcard Generator")
    print(f"Scanning {len(target_ids)} lesson(s) for vocab blocks...")
    print("=" * 60)

    vocab_lessons = []  # list of (lesson_id, title, items)

    for lid in target_ids:
        lesson = fetch_lesson(lid)
        if not lesson:
            continue
        blocks = lesson.get("blocks", [])
        items = extract_vocab_items(blocks)
        if items:
            vocab_lessons.append((lid, lesson.get("title", lid), items))

    vocab_lessons.sort(key=lambda x: sort_lesson_id(x[0]))
    print(f"Found {len(vocab_lessons)} lesson(s) with vocab blocks.")

    if not vocab_lessons:
        print("No vocab lessons found. Nothing to do.")
        return

    # ── Drive setup (load before applying limit so we can filter accurately) ──
    session = None
    lesson_folder_map: dict[str, str] = {}  # lesson_id -> Drive folder_id
    if not dry_run:
        session = get_session()
        print("Loading Drive lesson folder list...")
        lesson_folder_map = get_all_lesson_folders(session)
        print(f"Found {len(lesson_folder_map)} lesson folders in Drive.")

    # Apply limit — when saving, count only lessons with Drive folders
    limit = args.limit
    if limit and limit > 0:
        if not dry_run:
            # Keep only lessons that have Drive folders, then cap at limit
            uploadable = [(lid, t, i) for lid, t, i in vocab_lessons if lid in lesson_folder_map]
            vocab_lessons_to_process = uploadable[:limit]
            print(f"Limiting to first {limit} lessons with Drive folders "
                  f"({len(uploadable)} total have folders, {len(vocab_lessons)} have vocab).")
        else:
            vocab_lessons_to_process = vocab_lessons[:limit]
            print(f"Limiting to first {limit} vocab lessons (dry-run, ignoring Drive folders).")
    else:
        vocab_lessons_to_process = vocab_lessons

    vocab_lessons = vocab_lessons_to_process

    print(f"\nProcessing {len(vocab_lessons)} lesson(s) {'(DRY RUN)' if dry_run else '(SAVING)'}...")
    print("=" * 60)

    # ── Process each lesson ──
    log_entries = []
    uploaded = 0
    errors = 0

    for lesson_id, title, items in vocab_lessons:
        html = generate_flashcard_html(lesson_id, title, items)
        term_count = len(items)

        entry = {
            "lessonId": lesson_id,
            "title": title,
            "termCount": term_count,
            "status": "pending",
            "processedAt": datetime.now(timezone.utc).isoformat(),
        }

        if dry_run:
            print(f"  [DRY RUN] {lesson_id} — {title}: {term_count} terms")
            entry["status"] = "would_upload"
            log_entries.append(entry)
            continue

        # Look up lesson folder; auto-create if missing
        lesson_folder_id = lesson_folder_map.get(lesson_id)
        if not lesson_folder_id:
            lesson_folder_id = create_lesson_folder(session, lesson_id)
            if lesson_folder_id:
                lesson_folder_map[lesson_id] = lesson_folder_id  # cache it
            else:
                entry["status"] = "skipped_no_drive_folder"
                log_entries.append(entry)
                continue

        try:
            action = upload_or_update_file(session, lesson_folder_id, "flashcards.html", html)
            print(f"  {lesson_id} — {title}: {term_count} terms -> {action} flashcards.html to Drive")
            entry["status"] = action  # "created" or "updated"
            uploaded += 1
        except Exception as e:
            print(f"  [ERR] {lesson_id} — upload failed: {e}")
            entry["status"] = "error"
            entry["error"] = str(e)
            errors += 1

        log_entries.append(entry)
        time.sleep(0.3)  # Polite rate limiting

    # ── Save log ──
    log_data = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "dryRun": dry_run,
        "totalVocabLessons": len(vocab_lessons),
        "uploaded": uploaded,
        "errors": errors,
        "lessons": log_entries,
    }
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)

    # ── Summary ──
    skipped = sum(1 for e in log_entries if e["status"] == "skipped_no_drive_folder")
    print(f"\n{'='*60}")
    if dry_run:
        print(f"DRY RUN complete. {len(vocab_lessons)} lessons would generate flashcards.")
        print("Run with --save to upload.")
    else:
        print(f"Done. Uploaded: {uploaded}, Skipped (no Drive folder): {skipped}, Errors: {errors}")
    print(f"Log saved to: {LOG_PATH}")


if __name__ == "__main__":
    main()
