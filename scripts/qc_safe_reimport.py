"""
qc_safe_reimport.py

Re-imports lesson content from Google Docs into the GK12 platform.

For each target lesson:
  1. Fetch current blocks — save all non-text blocks (vocab, image, embed, callout, etc.)
  2. Read fresh HTML from the Google Doc tab via the Docs API
  3. POST to /api/admin/lessons  — platform parses HTML into h2-boundary blocks
  4. PATCH the lesson to append the saved non-text blocks back in

This preserves vocab, image, and embed blocks while replacing all text content
with the authoritative Drive source.

Target: C-011 onward + all M- lessons (by default).

Run:
  python scripts/qc_safe_reimport.py --dry-run            # preview only
  python scripts/qc_safe_reimport.py --save               # apply
  python scripts/qc_safe_reimport.py --lesson C-040 --save
  python scripts/qc_safe_reimport.py --lesson C-040 --dry-run
"""

import argparse, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS_DIR  = Path(__file__).parent
REPO_ROOT    = SCRIPTS_DIR.parent

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
def _get_platform_key() -> str:
    """Load platform API key from env or .env - never hardcode in source."""
    import os as _os
    from pathlib import Path as _Path
    k = (_os.environ.get('PIPELINE_KEY')
         or _os.environ.get('PLATFORM_KEY')
         or _os.environ.get('ADMIN_API_KEY', ''))
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=', 'ADMIN_API_KEY=')):
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


API_KEY      = _get_platform_key()
MANIFEST_PATH = SCRIPTS_DIR / "lessons_manifest.json"

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# Mousetrap is bundled inside the Creationeering course (one license covers both)
COURSE_IDS = {
    "creationeering":   "creationeering-ms",
    "creationeering-2": "creationeering-ms",
    "mousetrap":        "creationeering-ms",
}


# ── Lesson filter ─────────────────────────────────────────────────────────────

def should_include(lesson: dict) -> bool:
    lid = lesson["id"]
    if lid.startswith("C-"):
        m = re.search(r"\d+", lid)
        return m is not None and int(m.group()) >= 11
    return lid.startswith("M-")


# ── API helpers ───────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", headers=HEADERS
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  fetch error: {e}")
        return None


def post_lesson(lesson: dict, html: str, dry_run: bool) -> bool:
    """POST fresh HTML to the lessons collection endpoint."""
    course_id = COURSE_IDS.get(lesson["doc"], "creationeering-ms")
    payload = {
        "lessonId":      lesson["id"],
        "courseId":      course_id,
        "title":         lesson["tab"],
        "topic":         lesson.get("topic", ""),
        "order":         lesson.get("tab_number", 0),
        "html":          html,
        "parseToBlocks": True,
        "force":         True,
    }
    if dry_run:
        block_est = html.count("<h2") + html.count("<p>")
        print(f"  [DRY] would POST ~{block_est} elements → {lesson['id']}")
        return True

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons",
        data=data,
        headers=HEADERS,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if result.get("skipped"):
                print(f"  SKIPPED (contentSource=platform)")
                return False
            blk = result.get("blockCount", "?")
            print(f"  POST ok — {blk} blocks")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  POST HTTP {e.code}: {body[:120]}")
        return False
    except Exception as e:
        print(f"  POST error: {e}")
        return False


def patch_blocks(lesson_id: str, blocks: list, dry_run: bool) -> bool:
    """PATCH the lesson to append saved non-text blocks."""
    if not blocks:
        return True
    if dry_run:
        types = [b.get("type") for b in blocks]
        print(f"  [DRY] would patch back {len(blocks)} non-text blocks: {types}")
        return True

    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers=HEADERS,
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


# ── Google Docs reader ────────────────────────────────────────────────────────

def read_doc_tab_as_html(lesson: dict) -> str:
    """Read lesson content from Google Docs tab. Returns HTML string."""
    import google.auth
    from googleapiclient.discovery import build

    DOC_IDS = {
        "creationeering":   "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
        "creationeering-2": "14zURPF6v6A_rQFDD0ojrmFSos3jwu_kZvLkpfg5dqDc",
        "mousetrap":        "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
    }
    HEADING_MAP = {"HEADING_1": "h2", "HEADING_2": "h2", "HEADING_3": "h3", "HEADING_4": "h3"}

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/documents.readonly"]
    )
    svc = build("docs", "v1", credentials=creds, cache_discovery=False)
    doc_id = DOC_IDS[lesson["doc"]]
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()

    tab_title = lesson["tab"].strip().lower()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title:
            body = tab.get("documentTab", {}).get("body", {})
            return _body_to_html(body, HEADING_MAP)

    raise ValueError(f"Tab '{lesson['tab']}' not found in {lesson['doc']} doc")


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_ordered(para: dict) -> bool:
    return False  # Docs API doesn't expose list type easily; default ul


def _body_to_html(body: dict, heading_map: dict) -> str:
    parts = []
    list_state = None

    for element in body.get("content", []):
        para = element.get("paragraph")
        if not para:
            continue

        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        bullet = para.get("bullet")

        inline = []
        for pe in para.get("elements", []):
            text_run = pe.get("textRun", {})
            text = text_run.get("content", "").replace("\n", "")
            if not text:
                continue
            tf = text_run.get("textStyle", {})
            if tf.get("bold"):
                text = f"<strong>{_esc(text)}</strong>"
            elif tf.get("italic"):
                text = f"<em>{_esc(text)}</em>"
            else:
                text = _esc(text)
            inline.append(text)

        content = "".join(inline).strip()
        if not content:
            if list_state:
                parts.append(f"</{list_state}>")
                list_state = None
            continue

        if bullet:
            list_type = "ol" if _is_ordered(para) else "ul"
            if list_state != list_type:
                if list_state:
                    parts.append(f"</{list_state}>")
                parts.append(f"<{list_type}>")
                list_state = list_type
            parts.append(f"<li>{content}</li>")
            continue

        if list_state:
            parts.append(f"</{list_state}>")
            list_state = None

        tag = heading_map.get(style)
        if tag:
            parts.append(f"<{tag}>{content}</{tag}>")
        else:
            parts.append(f"<p>{content}</p>")

    if list_state:
        parts.append(f"</{list_state}>")

    return "\n".join(parts)


# ── Per-lesson logic ──────────────────────────────────────────────────────────

NON_TEXT_TYPES = {"vocab", "image", "embed", "callout", "accordion", "columns",
                  "tabs", "bordered-note", "divider", "carousel", "math",
                  "accordion-grid", "video"}


def process_lesson(lesson: dict, dry_run: bool) -> str:
    lid = lesson["id"]

    # 1. Fetch current blocks and save non-text ones
    data = fetch_lesson(lid)
    if not data:
        return "fetch_error"

    current_blocks = data.get("blocks", [])
    saved_non_text = [b for b in current_blocks if b.get("type") in NON_TEXT_TYPES]
    print(f"  Saved {len(saved_non_text)} non-text blocks: {[b.get('type') for b in saved_non_text]}")

    # 2. Read fresh HTML from Google Docs
    if dry_run:
        print(f"  [DRY] would read from Google Docs tab: {lesson['tab']}")
        print(f"  [DRY] would POST fresh HTML + restore non-text blocks")
        return "ok"

    try:
        html = read_doc_tab_as_html(lesson)
    except Exception as e:
        print(f"  Drive read error: {e}")
        return "drive_error"

    if len(html.strip()) < 100:
        print(f"  Drive tab too short ({len(html)} chars) — skipping")
        return "too_short"

    print(f"  Read {len(html)} chars from Drive")

    # 3. POST fresh HTML → platform parses to h2-boundary blocks
    ok = post_lesson(lesson, html, dry_run=False)
    if not ok:
        return "post_error"

    # 4. Fetch newly-created blocks and append saved non-text blocks
    if not saved_non_text:
        return "ok"

    new_data = fetch_lesson(lid)
    if not new_data:
        print(f"  Warning: could not re-fetch after POST; saved blocks not restored")
        return "ok"

    new_blocks = new_data.get("blocks", [])
    # Deduplicate: don't re-add embed blocks that the new import already created
    # (shouldn't happen since import only creates text blocks from HTML)
    final_blocks = new_blocks + saved_non_text

    ok2 = patch_blocks(lid, final_blocks, dry_run=False)
    if ok2:
        print(f"  Restored {len(saved_non_text)} non-text blocks → {len(final_blocks)} total blocks")
    else:
        print(f"  Warning: PATCH to restore non-text blocks failed")

    return "ok"


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no Drive reads or writes")
    parser.add_argument("--save",    action="store_true", help="Apply reimport")
    parser.add_argument("--lesson",  help="Single lesson ID")
    parser.add_argument("--delay",   type=float, default=0.5, help="Seconds between requests (default 0.5)")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lessons = manifest["lessons"]

    if args.lesson:
        targets = [l for l in lessons if l["id"] == args.lesson]
        if not targets:
            print(f"Lesson {args.lesson} not found in manifest"); sys.exit(1)
    else:
        targets = [l for l in lessons if should_include(l) and l.get("status") == "done"]

    total = len(targets)
    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"{mode} — reimporting {total} lessons from Google Drive\n")

    results = {"ok": 0, "fetch_error": 0, "drive_error": 0, "post_error": 0, "too_short": 0}

    for idx, lesson in enumerate(targets, 1):
        lid = lesson["id"]
        print(f"[{idx}/{total}] {lid} — {lesson['tab'][:50]}")
        status = process_lesson(lesson, args.dry_run)
        results[status] = results.get(status, 0) + 1

        if not args.dry_run and idx < total:
            time.sleep(args.delay)

    print(f"\n{'='*60}")
    print(f"Results: {results}")
    if args.dry_run:
        print("\nRun with --save to apply.")


if __name__ == "__main__":
    main()
