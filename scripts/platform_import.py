"""
Genesis K-12 Platform Import Script

Reads QC-passed lessons from Google Docs + assessment JSON files + local images,
then POSTs each to the GK12 Platform Pipeline API.

Usage:
  python scripts/platform_import.py --dry-run          # preview what will be sent
  python scripts/platform_import.py                    # import to localhost:3000
  python scripts/platform_import.py --live             # import to production
  python scripts/platform_import.py --lesson C-025     # single lesson
  python scripts/platform_import.py --course creationeering  # one course only
  python scripts/platform_import.py --skip-images      # skip image upload
"""

import argparse, base64, json, os, re, sys, time, urllib.request, urllib.error

MANIFEST_PATH   = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
ASSESSMENTS_DIR = os.path.join(os.path.dirname(__file__), "assessments")
MEDIA_PROMPTS   = os.path.join(os.path.dirname(__file__), "media_prompts.json")
IMAGES_DIR      = os.path.join(os.path.dirname(__file__), "..", "output", "images")

LOCAL_URL = "http://localhost:3000"
LIVE_URL  = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
API_KEY   = "gk12-pipeline-2026"

COURSE_IDS = {
    "creationeering": "creationeering-ms",
    "mousetrap":      "mousetrap-ms",
}

DOC_IDS = {
    "creationeering": "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
    "mousetrap":      "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
}

# Paragraph styles that map to HTML headings
HEADING_MAP = {
    "HEADING_1": "h2",
    "HEADING_2": "h2",
    "HEADING_3": "h3",
    "HEADING_4": "h3",
}


def read_doc_tab_as_html(lesson):
    import google.auth
    from googleapiclient.discovery import build

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/documents.readonly"])
    svc = build("docs", "v1", credentials=creds)
    doc_id = DOC_IDS[lesson["doc"]]
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()

    tab_title = lesson["tab"].strip().lower()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title:
            body = tab.get("documentTab", {}).get("body", {})
            return _body_to_html(body)

    raise ValueError(f"Tab '{lesson['tab']}' not found in {lesson['doc']} doc")


def _body_to_html(body):
    parts = []
    list_state = None  # "ul" or "ol"

    for element in body.get("content", []):
        para = element.get("paragraph")
        if not para:
            continue

        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        bullet = para.get("bullet")

        # Collect inline text with basic formatting
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
            # Close any open list before empty paragraph
            if list_state:
                parts.append(f"</{list_state}>")
                list_state = None
            continue

        # List items
        if bullet:
            list_type = "ol" if bullet.get("listId") and _is_ordered(para) else "ul"
            if list_state != list_type:
                if list_state:
                    parts.append(f"</{list_state}>")
                parts.append(f"<{list_type}>")
                list_state = list_type
            parts.append(f"<li>{content}</li>")
            continue

        # Close any open list
        if list_state:
            parts.append(f"</{list_state}>")
            list_state = None

        # Headings
        tag = HEADING_MAP.get(style)
        if tag:
            parts.append(f"<{tag}>{content}</{tag}>")
        else:
            parts.append(f"<p>{content}</p>")

    if list_state:
        parts.append(f"</{list_state}>")

    return "\n".join(parts)


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _is_ordered(para):
    # Docs API doesn't expose list type directly in simple reads; default to unordered
    return False


def load_assessment(lesson_id):
    path = os.path.join(ASSESSMENTS_DIR, f"{lesson_id}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.dumps(json.load(f))
    return None


def _slug(text):
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")


def upload_images(base_url, lesson_id, dry_run=False):
    """Upload all local images for a lesson to Firebase Storage via the platform API.
    Returns (cover_url, section_urls_dict) — cover_url is None if no cover image.
    """
    with open(MEDIA_PROMPTS, encoding="utf-8") as f:
        mp = json.load(f)

    entry = mp.get(lesson_id)
    if not entry:
        return None, {}

    images = entry.get("images", {})
    if not images:
        return None, {}

    cover_url = None
    section_urls = {}

    for section, img_data in images.items():
        local_path = img_data.get("local", "")
        if not local_path or not os.path.exists(local_path):
            continue

        filename = f"{_slug(section)}.png"

        if dry_run:
            print(f"    [img] {section} -> {filename}")
            if section.lower() == "cover":
                cover_url = "DRY_RUN_URL"
            else:
                section_urls[section] = "DRY_RUN_URL"
            continue

        with open(local_path, "rb") as f:
            data_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = json.dumps({
            "lessonId":   lesson_id,
            "filename":   filename,
            "mimeType":   "image/png",
            "dataBase64": data_b64,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{base_url}/api/admin/images",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                url = result.get("url", "")
                if section.lower() == "cover":
                    cover_url = url
                else:
                    section_urls[section] = url
                print(f"    [img] {section} -> uploaded")
        except Exception as e:
            print(f"    [img] {section} -> error: {e}")

    return cover_url, section_urls


def post_lesson(base_url, lesson, html, assessment_json, cover_url=None, dry_run=False):
    course_id = COURSE_IDS[lesson["doc"]]

    # Prepend cover image if available
    if cover_url and cover_url != "DRY_RUN_URL":
        html = f'<img src="{cover_url}" alt="{_esc(lesson["tab"])} cover">\n' + html

    payload = {
        "lessonId":      lesson["id"],
        "courseId":      course_id,
        "title":         lesson["tab"],
        "topic":         lesson["topic"],
        "order":         lesson["tab_number"],
        "html":          html,
        "parseToBlocks": True,
    }
    if assessment_json:
        payload["assessmentJson"] = assessment_json

    if dry_run:
        blocks_estimate = html.count("<p>") + html.count("<h2>") + html.count("<h3>")
        assessment_note = "with assessment" if assessment_json else "no assessment"
        cover_note = "cover image" if cover_url else "no cover"
        print(f"  [{lesson['id']}] {lesson['tab'][:50]}  ~{blocks_estimate} blocks  {assessment_note}  {cover_note}")
        return True

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/admin/lessons",
        data=data,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            blocks = result.get("blockCount", "?")
            print(f"  [{lesson['id']}] OK — {blocks} blocks")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [{lesson['id']}] HTTP {e.code}: {body[:120]}")
        return False
    except Exception as e:
        print(f"  [{lesson['id']}] Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Import QC-passed lessons into GK12 Platform")
    parser.add_argument("--live",       action="store_true", help="Target production URL")
    parser.add_argument("--dry-run",    action="store_true", help="Preview without posting")
    parser.add_argument("--lesson",     help="Import a single lesson by ID (e.g. C-025)")
    parser.add_argument("--course",     choices=["creationeering", "mousetrap", "both"], default="both")
    parser.add_argument("--delay",       type=float, default=0.5, help="Seconds between requests (default 0.5)")
    parser.add_argument("--skip-images", action="store_true", help="Skip image upload")
    args = parser.parse_args()

    base_url = LIVE_URL if args.live else LOCAL_URL
    target = "PRODUCTION" if args.live else "localhost:3000"

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    lessons = data["lessons"]

    # Build target list
    if args.lesson:
        targets = [l for l in lessons if l["id"] == args.lesson]
        if not targets:
            print(f"Lesson {args.lesson} not found in manifest")
            sys.exit(1)
    else:
        targets = [
            l for l in lessons
            if l.get("qc_status") == "passed"
            and l.get("status") == "done"
            and (args.course == "both" or l["doc"] == args.course)
        ]

    print(f"Platform import -> {target}")
    print(f"Lessons: {len(targets)}")
    if args.dry_run:
        print("Mode: DRY RUN — no data will be sent\n")
    else:
        print()

    ok = fail = 0
    for i, lesson in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {lesson['id']} — {lesson['tab']}")

        if not args.dry_run:
            try:
                html = read_doc_tab_as_html(lesson)
                if len(html.strip()) < 100:
                    print(f"  Tab content too short — skipping")
                    fail += 1
                    continue
            except Exception as e:
                print(f"  Doc read error: {e}")
                fail += 1
                continue
        else:
            html = "<p>dry run placeholder</p>"

        assessment_json = load_assessment(lesson["id"])

        cover_url = None
        if not args.skip_images:
            cover_url, _ = upload_images(base_url, lesson["id"], dry_run=args.dry_run)

        if post_lesson(base_url, lesson, html, assessment_json, cover_url=cover_url, dry_run=args.dry_run):
            ok += 1
        else:
            fail += 1

        if not args.dry_run and i < len(targets):
            time.sleep(args.delay)

    print(f"\n=== Import complete: {ok} ok, {fail} failed ===")


if __name__ == "__main__":
    main()
