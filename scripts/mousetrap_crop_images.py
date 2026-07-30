"""
mousetrap_crop_images.py

Scans Mousetrap lesson screenshots with Claude Vision to detect embedded
diagrams/photos, crops them with Pillow, uploads to Firebase Storage via the
platform /api/admin/images endpoint, and PATCHes empty image blocks.

Matching: detected images are assigned positionally across all screenshots in
filename order — 1st detected image → 1st empty block, 2nd → 2nd, etc.

Usage:
  python scripts/mousetrap_crop_images.py --dry-run            # preview
  python scripts/mousetrap_crop_images.py --save               # apply
  python scripts/mousetrap_crop_images.py --lesson M-006       # single lesson
"""

import argparse, base64, io, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image

LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
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
SCREENSHOTS_ROOT = Path(__file__).parent.parent / "screenshots"
CLAUDE_MODEL     = "claude-sonnet-5"
BATCH_SIZE       = 4   # screenshots per Vision call (keep small — screenshots are large)

LESSON_MAP = [
    {"folder": "Mousetrap/Mousetrap Course Intro",               "id": "M-002"},
    {"folder": "Mousetrap/Kit Overview",                         "id": "M-003"},
    {"folder": "Mousetrap/OCV",                                  "id": "M-004"},
    {"folder": "Mousetrap/Prototyping and Iterative Design",     "id": "M-005"},
    {"folder": "Mousetrap/Build 1 Mousetrap Prototype Mark 1.0","id": "M-006"},
    {"folder": "Mousetrap/Design",                               "id": "M-011"},
    {"folder": "Mousetrap/Communicating Designs and Testing",    "id": "M-012"},
    {"folder": "Mousetrap/Power Transmission Mechanics",         "id": "M-014"},
    {"folder": "Mousetrap/The Dynamics of Stored Energy",        "id": "M-018"},
    {"folder": "Mousetrap/Modeling Resistive Forces",            "id": "M-019"},
]

DETECT_PROMPT = """You are scanning lesson screenshots to extract embedded content images.

For EACH screenshot provided, identify any diagrams, photographs, illustrations,
technical drawings, or charts that appear as CONTENT (not UI chrome).

IGNORE: navigation bars, header/footer UI, buttons, pagination arrows, browser chrome,
scroll bars, watermarks, and plain text paragraphs.

INCLUDE: diagrams showing assembly steps, photos of equipment, labeled technical
figures, charts, engineering drawings — anything that is IMAGE content, not text.

For each image found, return its bounding box as percentages of that screenshot's
total width/height. Add ~2% padding around the visible image edges.

Return a JSON array (one element per screenshot, in input order). Each element is
an array of objects — or an empty array [] if that screenshot has no content images:

[
  [{"description": "...", "crop": {"x_pct": 10, "y_pct": 25, "w_pct": 80, "h_pct": 45}}],
  [],
  [{"description": "...", "crop": {...}}, {"description": "...", "crop": {...}}]
]

Return ONLY valid JSON. No explanation or markdown."""


# ── Env ───────────────────────────────────────────────────────────────────────

def load_env() -> dict:
    env = {}
    for name in [".env", ".env.local"]:
        path = Path(__file__).parent.parent / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
    return env


# ── Screenshot loading ────────────────────────────────────────────────────────

def natural_key(p: Path):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", p.stem)]


def load_screenshots(folder: Path) -> list[tuple[Path, str, str]]:
    """Returns sorted list of (path, mime, base64_data)."""
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in exts], key=natural_key)
    result = []
    for f in files:
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp"}.get(f.suffix.lower().lstrip("."), "image/png")
        data = base64.standard_b64encode(f.read_bytes()).decode()
        result.append((f, mime, data))
    return result


# ── Claude Vision detection ───────────────────────────────────────────────────

def detect_batch(screenshots: list[tuple[Path, str, str]], api_key: str) -> list[list[dict]]:
    """Send one batch to Claude Vision. Returns list[list[detection]] — one inner list per screenshot."""
    content: list[dict] = []
    for i, (path, mime, data) in enumerate(screenshots):
        content.append({"type": "text", "text": f"Screenshot {i+1} ({path.name}):"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})

    n = len(screenshots)
    content.append({
        "type": "text",
        "text": (
            f"Above are {n} screenshot(s) (numbered 1–{n}).\n\n"
            + DETECT_PROMPT
            + f"\n\nIMPORTANT: Return exactly {n} array elements — one per screenshot, in order."
        ),
    })

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 6144,
        "messages": [{"role": "user", "content": content}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read())

    raw = result["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.splitlines() if not l.strip().startswith("```")).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        debug_path = Path(__file__).parent.parent / f"_crop_raw_debug.txt"
        debug_path.write_text(raw, encoding="utf-8")
        raise ValueError(f"Vision JSON parse error: {e} (raw saved to {debug_path})")

    if not isinstance(parsed, list):
        raise ValueError("Expected outer JSON array from Vision")

    # Normalise: pad or trim to match batch size
    while len(parsed) < n:
        parsed.append([])
    return [parsed[i] if isinstance(parsed[i], list) else [] for i in range(n)]


# ── Cropping ─────────────────────────────────────────────────────────────────

def crop_to_png(path: Path, crop: dict) -> bytes:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    x1 = max(0, int(crop["x_pct"] / 100 * w))
    y1 = max(0, int(crop["y_pct"] / 100 * h))
    x2 = min(w, int((crop["x_pct"] + crop["w_pct"]) / 100 * w))
    y2 = min(h, int((crop["y_pct"] + crop["h_pct"]) / 100 * h))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"Invalid crop box: ({x1},{y1})→({x2},{y2})")
    buf = io.BytesIO()
    img.crop((x1, y1, x2, y2)).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Platform API ──────────────────────────────────────────────────────────────

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


def upload_image(lesson_id: str, filename: str, img_bytes: bytes) -> str | None:
    payload = json.dumps({
        "lessonId": lesson_id,
        "filename": filename,
        "mimeType": "image/png",
        "dataBase64": base64.b64encode(img_bytes).decode(),
    }).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/images",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("url") if result.get("ok") else None
    except urllib.error.HTTPError as e:
        print(f"  Upload HTTP {e.code}: {e.read().decode('utf-8','replace')[:200]}")
        return None
    except Exception as e:
        print(f"  Upload error: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list) -> bool:
    payload = json.dumps({"blocks": blocks}).encode()
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


# ── Per-lesson orchestration ──────────────────────────────────────────────────

def process_lesson(entry: dict, api_key: str, dry_run: bool) -> dict:
    lesson_id = entry["id"]
    folder    = SCREENSHOTS_ROOT / entry["folder"]

    print(f"\n{'='*60}")
    print(f"  {lesson_id}  ({entry['folder']})")

    if not folder.exists():
        print(f"  [SKIP] Screenshot folder not found")
        return {"id": lesson_id, "status": "no_folder"}

    # Find empty image blocks
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return {"id": lesson_id, "status": "fetch_error"}

    blocks = lesson.get("blocks", [])
    empty_indices = [
        i for i, b in enumerate(blocks)
        if b.get("type") == "image" and not b.get("data", {}).get("src")
    ]
    if not empty_indices:
        print(f"  [SKIP] No empty image blocks")
        return {"id": lesson_id, "status": "no_empty_blocks"}

    print(f"  {len(empty_indices)} empty block(s) to fill")

    screenshots = load_screenshots(folder)
    if not screenshots:
        print(f"  [SKIP] No screenshots in folder")
        return {"id": lesson_id, "status": "no_screenshots"}

    print(f"  {len(screenshots)} screenshot(s) loaded")

    # Vision detection — process in batches
    detections: list[tuple[Path, dict, str]] = []  # (path, crop, description)
    n_batches = (len(screenshots) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(n_batches):
        batch = screenshots[batch_idx * BATCH_SIZE:(batch_idx + 1) * BATCH_SIZE]
        print(f"  Vision batch {batch_idx+1}/{n_batches} ({len(batch)} screenshots)...")
        last_err = None
        for attempt in range(3):
            try:
                results = detect_batch(batch, api_key)
                for (path, _, _), img_list in zip(batch, results):
                    for det in img_list:
                        crop = det.get("crop", {})
                        desc = det.get("description", "")[:80]
                        detections.append((path, crop, desc))
                        print(f"    + {path.name}: {desc}")
                break
            except Exception as e:
                last_err = e
                if attempt < 2:
                    print(f"    [retry {attempt+1}] {e}")
                    time.sleep(3)
        else:
            print(f"  [ERR] Batch {batch_idx+1} failed after 3 attempts: {last_err}")
            return {"id": lesson_id, "status": "vision_error", "error": str(last_err)}

        if batch_idx < n_batches - 1:
            time.sleep(1.5)

    print(f"  Total detected: {len(detections)}")

    if dry_run:
        fill = min(len(detections), len(empty_indices))
        print(f"  DRY RUN: would fill {fill}/{len(empty_indices)} blocks from {len(detections)} detections")
        return {"id": lesson_id, "status": "dry_run",
                "detected": len(detections), "empty_blocks": len(empty_indices)}

    # Crop + upload
    urls: list[str | None] = []
    for i, (path, crop, desc) in enumerate(detections):
        filename = f"crop-{i+1:03d}.png"
        try:
            img_bytes = crop_to_png(path, crop)
            url = upload_image(lesson_id, filename, img_bytes)
            urls.append(url)
            status = "ok" if url else "upload_failed"
            print(f"  [{i+1}/{len(detections)}] {filename} {status}")
        except Exception as e:
            print(f"  [{i+1}/{len(detections)}] crop error: {e}")
            urls.append(None)

    # Fill blocks positionally
    filled = 0
    for slot, block_idx in enumerate(empty_indices):
        if slot < len(urls) and urls[slot]:
            blocks[block_idx]["data"]["src"] = urls[slot]
            filled += 1

    if filled == 0:
        print(f"  No images filled — patch skipped")
        return {"id": lesson_id, "status": "no_fills"}

    ok = patch_lesson(lesson_id, blocks)
    status = "done" if ok else "patch_failed"
    print(f"  {'OK' if ok else 'PATCH FAILED'}: {filled}/{len(empty_indices)} blocks filled")
    return {"id": lesson_id, "status": status, "filled": filled, "empty": len(empty_indices)}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--save",    action="store_true", help="Crop, upload, and patch")
    parser.add_argument("--lesson",  help="Single lesson ID, e.g. M-006")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    env = load_env()
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ANTHROPIC_API_KEY not found in .env or environment"); sys.exit(1)

    lessons = LESSON_MAP
    if args.lesson:
        lessons = [e for e in LESSON_MAP if e["id"].upper() == args.lesson.upper()]
        if not lessons:
            print(f"Lesson {args.lesson} not in LESSON_MAP"); sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"\nMousetrap Image Crop — {mode} — {len(lessons)} lesson(s)")

    results = []
    for entry in lessons:
        r = process_lesson(entry, api_key, dry_run=args.dry_run)
        results.append(r)
        time.sleep(0.5)

    print(f"\n{'='*60}")
    print("SUMMARY")
    for r in results:
        extra = ""
        if "filled" in r:
            extra = f" — {r['filled']}/{r['empty']} filled"
        elif "detected" in r:
            extra = f" — {r['detected']} detected, {r['empty_blocks']} blocks"
        print(f"  {r['id']}: {r['status']}{extra}")


if __name__ == "__main__":
    main()
