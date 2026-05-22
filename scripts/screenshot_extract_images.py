"""
Genesis K-12 — Extract Images from LW Screenshots

Uses Claude Vision to detect image/diagram bounding boxes in each screenshot,
crops them with Pillow, uploads to Firebase Storage via the platform API,
then backfills the src field on the lesson's image blocks positionally.

Positional matching: detected images ordered top→bottom across all screenshots
are matched 1:1 to the lesson's image blocks in order. If counts differ, best-
effort partial match is applied and a warning printed for manual QC review.

Usage:
  python scripts/screenshot_extract_images.py C-007              # dry-run: show detected images
  python scripts/screenshot_extract_images.py C-007 --upload     # upload + backfill src
  python scripts/screenshot_extract_images.py C-007 --folder "screenshots/Creationeering/Objectives Constraints and Variables" --upload

Batch (all high-priority lessons):
  python scripts/screenshot_extract_images.py --batch high --upload
  python scripts/screenshot_extract_images.py --batch all --upload
"""

import argparse, base64, io, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load API keys from .env so the key is available even without shell env export
_ENV_PATH = Path(__file__).parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SCREENSHOTS_ROOT = Path(__file__).parent.parent / "screenshots"
LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY     = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL     = "claude-sonnet-4-6"

# Minimum crop size — skip tiny regions (icons, bullets, decorative elements)
MIN_WIDTH_PX  = 80
MIN_HEIGHT_PX = 60

# Lesson → screenshot folder mapping (same as batch importer)
LESSON_MAP = [
    {"folder": "Creationeering/What is Engineering",                    "id": "C-001", "priority": "medium"},
    {"folder": "Creationeering/Entrepreneurship",                       "id": "C-002", "priority": "high"},
    {"folder": "Creationeering/Genesis and Creationeering",             "id": "C-003", "priority": "high"},
    {"folder": "Creationeering/Understanding Math and Science as Tools", "id": "C-004", "priority": "medium"},
    {"folder": "Creationeering/Units Conversions and Measurement",      "id": "C-005", "priority": "medium"},
    {"folder": "Creationeering/Intro to Systems Thinking",              "id": "C-006", "priority": "medium"},
    {"folder": "Creationeering/Objectives Constraints and Variables",   "id": "C-007", "priority": "high"},
    {"folder": "Creationeering/Ethics in Engineering and Stewardship",  "id": "C-008", "priority": "medium"},
    {"folder": "Creationeering/Process Mapping and Flowcharts",         "id": "C-009", "priority": "medium"},
    {"folder": "Creationeering/Visualization and sketching",            "id": "C-010", "priority": "medium"},
    {"folder": "Creationeering/Design Forces and Influences",           "id": "C-011", "priority": "medium"},
    {"folder": "Creationeering/Design Historical Case Studies",         "id": "C-012", "priority": "medium"},
    {"folder": "Creationeering/Form Function and Aesthetic",            "id": "C-013", "priority": "medium"},
    {"folder": "Creationeering/Design Iteration and Communication",     "id": "C-014", "priority": "medium"},
    {"folder": "Creationeering/Alternatives and Patents",               "id": "C-015", "priority": "medium"},
    {"folder": "Creationeering/Novelty and Innovation in Engineering",  "id": "C-016", "priority": "medium"},
    {"folder": "Creationeering/Concept Generation",                     "id": "C-017", "priority": "medium"},
    {"folder": "Creationeering/Fundamentals of Force Motion and Work",  "id": "C-018", "priority": "medium"},
    {"folder": "Mousetrap/Mousetrap Course Intro",                      "id": "M-002", "priority": "high"},
    {"folder": "Mousetrap/Kit Overview",                                "id": "M-003", "priority": "high"},
    {"folder": "Mousetrap/OCV",                                         "id": "M-004", "priority": "medium"},
    {"folder": "Mousetrap/Prototyping and Iterative Design",            "id": "M-005", "priority": "medium"},
    {"folder": "Mousetrap/Build 1 Mousetrap Prototype Mark 1.0",       "id": "M-006", "priority": "high"},
    {"folder": "Mousetrap/Design",                                      "id": "M-011", "priority": "high"},
    {"folder": "Mousetrap/Communicating Designs and Testing",           "id": "M-012", "priority": "high"},
    {"folder": "Mousetrap/Power Transmission Mechanics",                "id": "M-014", "priority": "medium"},
    {"folder": "Mousetrap/The Dynamics of Stored Energy",               "id": "M-018", "priority": "medium"},
    {"folder": "Mousetrap/Modeling Resistive Forces",                   "id": "M-019", "priority": "medium"},
]

DETECT_PROMPT = """
You are analyzing a LearnWorlds lesson screenshot to locate every meaningful image,
diagram, photograph, illustration, chart, or table visible on the page.

COORDINATE FORMAT — IMPORTANT:
Return bounding boxes as PROPORTIONAL values between 0.0 and 1.0, where:
  (0.0, 0.0) = top-left corner of the screenshot
  (1.0, 1.0) = bottom-right corner of the screenshot
Use 2 decimal places of precision.

DO NOT mark:
- UI chrome (navigation bars, buttons, lesson titles, progress bars)
- Plain text blocks, headings, or bullet lists
- Background decorations or color fills
- Slide-style text graphics: large or stylized text on a solid/gradient/white background
  with no photographic or diagrammatic content. This includes "quote card" layouts,
  animated text slides, or any region where the primary content is words — even if the
  font is very large, decorative, or split across multiple lines.
- Any region where ≥70% of visible area is text.
- Icons smaller than ~5% of screenshot width.

DO mark (only clearly non-text visual content):
- Photographs of real-world objects, people, places, or physical processes
- Engineering diagrams, schematics, technical drawings, or labeled component diagrams
- Charts or graphs (bar, line, pie, scatter, etc.)
- Illustrations, clip art, or infographics with graphical elements
- Tables containing data values (columns of numbers or mixed text+data cells)
- Step-by-step instruction images showing physical build or lab actions

SPLIT-LAYOUT SLIDES: Some slides have text on one side (left or right) and a photo on
the other side. In this case, mark ONLY the photo region — do not include the text side
in the bounding box. The photo region typically has a distinct photographic background
(not white or plain color).

Return a JSON array. Each item:
{
  "bbox": [x1, y1, x2, y2],   // proportional 0.0-1.0 coordinates
  "caption": "brief description of what the image shows",
  "type": "photo|diagram|chart|table|illustration"
}

If no meaningful images are present, return an empty array: []

Return ONLY valid JSON — no explanation, no markdown fences.
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _natural_key(path: Path):
    parts = re.split(r"(\d+)", path.stem)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def load_screenshot_files(folder: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    return sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in exts],
        key=_natural_key,
    )


def detect_images_in_screenshot(img_path: Path) -> list[dict]:
    """Ask Claude Vision for bounding boxes of all meaningful images in one screenshot."""
    if not ANTHROPIC_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set. Run: $env:ANTHROPIC_API_KEY='sk-ant-...'")

    ext  = img_path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png",  "webp": "image/webp"}.get(ext, "image/png")
    data = base64.standard_b64encode(img_path.read_bytes()).decode()

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}},
                {"type": "text", "text": DETECT_PROMPT},
            ],
        }],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key":          ANTHROPIC_KEY,
            "anthropic-version":  "2023-06-01",
            "content-type":       "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    raw = result["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("```")).strip()

    detections = json.loads(raw)
    return detections if isinstance(detections, list) else []


BBOX_PADDING = 0.01  # proportional padding (1% of image dimension) added to each edge

def crop_image(img_path: Path, bbox: list[float]) -> bytes:
    """Crop a region from an image file and return JPEG bytes.

    bbox values are proportional (0.0-1.0). A small padding is added on each
    side to avoid clipping at the detected boundary edge.
    """
    from PIL import Image
    with Image.open(img_path) as img:
        w, h = img.size
        # Convert proportional → pixels with padding, then clamp
        x1 = max(0, int((bbox[0] - BBOX_PADDING) * w))
        y1 = max(0, int((bbox[1] - BBOX_PADDING) * h))
        x2 = min(w, int((bbox[2] + BBOX_PADDING) * w))
        y2 = min(h, int((bbox[3] + BBOX_PADDING) * h))
        if x2 - x1 < MIN_WIDTH_PX or y2 - y1 < MIN_HEIGHT_PX:
            return b""
        cropped = img.crop((x1, y1, x2, y2)).convert("RGB")
        buf = io.BytesIO()
        cropped.save(buf, format="JPEG", quality=88)
        return buf.getvalue()


def upload_image(lesson_id: str, index: int, jpeg_bytes: bytes, caption: str) -> str | None:
    """Upload a cropped image via the platform /api/admin/images endpoint. Returns URL."""
    filename = f"img_{index:02d}.jpg"
    payload = json.dumps({
        "lessonId":   lesson_id,
        "filename":   filename,
        "mimeType":   "image/jpeg",
        "dataBase64": base64.standard_b64encode(jpeg_bytes).decode(),
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/images",
        data=payload,
        headers={
            "Authorization": f"Bearer {PLATFORM_KEY}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("url")
    except Exception as e:
        print(f"  [upload ERR] {filename}: {e}")
        return None


def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [fetch ERR] {lesson_id}: {e}")
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
        print(f"  [patch ERR] {lesson_id}: {e}")
        return False


# ── Core logic ────────────────────────────────────────────────────────────────

def extract_lesson_images(lesson_id: str, folder: Path, upload: bool) -> dict:
    """
    Detect images in all screenshots, crop them, upload, and backfill lesson blocks.
    Returns summary dict.
    """
    files = load_screenshot_files(folder)
    if not files:
        return {"id": lesson_id, "status": "no_screenshots"}

    print(f"\n  {lesson_id} — {folder.name} ({len(files)} screenshots)")

    # Pass 1: detect bounding boxes in every screenshot
    all_detections = []  # list of (img_path, bbox, caption, type)
    for img_path in files:
        try:
            detections = detect_images_in_screenshot(img_path)
            for d in detections:
                all_detections.append((img_path, d["bbox"], d.get("caption", ""), d.get("type", "photo")))
            count = len(detections)
            print(f"    {img_path.name}: {count} image(s) detected")
        except Exception as e:
            print(f"    {img_path.name}: detection error — {e}")
        time.sleep(0.3)  # gentle rate limiting

    print(f"  Total detected: {len(all_detections)}")

    if not all_detections:
        return {"id": lesson_id, "status": "no_images_detected", "detected": 0}

    if not upload:
        print("  (dry-run — pass --upload to crop and upload)")
        for i, (path, bbox, caption, itype) in enumerate(all_detections):
            print(f"    [{i}] {path.name} bbox={bbox} — {caption[:60]}")
        return {"id": lesson_id, "status": "dry_run", "detected": len(all_detections)}

    # Pass 2: crop + upload
    uploaded_urls = []
    for i, (img_path, bbox, caption, itype) in enumerate(all_detections):
        jpeg = crop_image(img_path, bbox)
        if not jpeg:
            print(f"  [{i}] SKIP — crop too small: {bbox}")
            uploaded_urls.append(None)
            continue
        url = upload_image(lesson_id, i, jpeg, caption)
        uploaded_urls.append(url)
        status = f"✓ {url.split('?')[0].split('/')[-1]}" if url else "ERR"
        print(f"  [{i}] {status} — {caption[:50]}")
        time.sleep(0.2)

    # Pass 3: fetch lesson blocks + positional backfill
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return {"id": lesson_id, "status": "fetch_failed", "uploaded": len([u for u in uploaded_urls if u])}

    blocks = lesson.get("blocks", [])
    image_blocks = [(i, b) for i, b in enumerate(blocks) if b.get("type") == "image"]
    valid_urls   = [u for u in uploaded_urls if u]

    n_blocks = len(image_blocks)
    n_images  = len(valid_urls)
    matched   = min(n_blocks, n_images)

    if n_blocks != n_images:
        print(f"  ⚠ Mismatch: {n_images} uploaded image(s), {n_blocks} image block(s) — {matched} matched positionally")

    for pos, (block_idx, block) in enumerate(image_blocks[:matched]):
        block["data"]["src"]     = valid_urls[pos]
        block["data"]["caption"] = all_detections[pos][2] or block["data"].get("caption", "")

    ok = patch_lesson(lesson_id, blocks)
    print(f"  {'✓ Patched' if ok else '⚠ Patch failed'}: {matched} image(s) backfilled")

    return {
        "id":       lesson_id,
        "status":   "done" if ok else "patch_failed",
        "detected": len(all_detections),
        "uploaded": len(valid_urls),
        "matched":  matched,
        "mismatch": n_blocks != n_images,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lesson_id", nargs="?",   help="Single lesson ID, e.g. C-007")
    parser.add_argument("--folder",               help="Custom screenshot folder path")
    parser.add_argument("--upload", action="store_true", help="Crop, upload, and backfill (default: dry-run)")
    parser.add_argument("--batch",  choices=["high", "medium", "all"], help="Run on all lessons at given priority")
    args = parser.parse_args()

    if not args.lesson_id and not args.batch:
        parser.print_help()
        sys.exit(1)

    if args.batch:
        priority = args.batch
        lessons = LESSON_MAP if priority == "all" else [e for e in LESSON_MAP if e["priority"] == priority]
        print(f"\nBatch image extraction — {len(lessons)} lesson(s), priority={priority}, upload={args.upload}")

        results = []
        for entry in lessons:
            folder = SCREENSHOTS_ROOT / entry["folder"]
            if not folder.exists():
                print(f"  [SKIP] {entry['id']}: folder not found")
                results.append({"id": entry["id"], "status": "no_folder"})
                continue
            result = extract_lesson_images(entry["id"], folder, upload=args.upload)
            results.append(result)
            time.sleep(1)

        # Summary
        print(f"\n{'='*60}")
        print("BATCH COMPLETE")
        for r in results:
            flag = " ⚠ MISMATCH" if r.get("mismatch") else ""
            print(f"  {r['id']}: {r['status']} — detected={r.get('detected',0)} uploaded={r.get('uploaded',0)} matched={r.get('matched',0)}{flag}")

        mismatch_count = sum(1 for r in results if r.get("mismatch"))
        if mismatch_count:
            print(f"\n  {mismatch_count} lesson(s) have image/block count mismatches — review in admin editor")

        summary_path = Path(__file__).parent.parent / "screenshots_import_output" / "_image_extract_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Summary saved to {summary_path}")

    else:
        lesson_id = args.lesson_id.upper()
        if args.folder:
            folder = Path(args.folder)
        else:
            entry = next((e for e in LESSON_MAP if e["id"] == lesson_id), None)
            if entry:
                folder = SCREENSHOTS_ROOT / entry["folder"]
            else:
                print(f"Lesson {lesson_id} not in LESSON_MAP. Use --folder to specify path.")
                sys.exit(1)

        if not folder.exists():
            print(f"Folder not found: {folder}")
            sys.exit(1)

        result = extract_lesson_images(lesson_id, folder, upload=args.upload)
        print(f"\nResult: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
