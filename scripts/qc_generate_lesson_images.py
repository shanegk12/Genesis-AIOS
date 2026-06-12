"""
Genesis K-12 QC — Generate Images for Empty Lesson Image Blocks

For lessons that have image blocks with empty src="" (created by screenshot import
but never filled), this script:
  1. Fetches the lesson from the platform API
  2. For each empty image block, builds a prompt from block caption + surrounding context
  3. Calls the selected image model to produce an educational illustration
  4. Uploads the image to Firebase Storage via the platform /api/admin/images endpoint
  5. PATCHes the lesson block with the real URL

Models (--model flag):
  imagen   — Imagen 4.0 fast (Google, default). Best for general illustrations.
  flux     — FLUX 1.1 Pro via fal.ai. Better photorealism, more variety.
  ideogram — Ideogram v3 via fal.ai. Best for labeled diagrams and text-in-image.

Usage:
  python scripts/qc_generate_lesson_images.py --dry-run                     # preview
  python scripts/qc_generate_lesson_images.py                               # Imagen
  python scripts/qc_generate_lesson_images.py --model flux                  # FLUX
  python scripts/qc_generate_lesson_images.py --model ideogram              # Ideogram
  python scripts/qc_generate_lesson_images.py --lesson-id C-008 --model flux
  python scripts/qc_generate_lesson_images.py --course C --model ideogram
"""

import argparse, base64, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
LOG_PATH      = Path(__file__).parent / "image_generation_log.json"
LOGO_PATH     = Path(__file__).parent.parent / "references" / "gk12-logo.PNG"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_IMAGE_MODEL = "imagen-4.0-fast-generate-001"
GEMINI_URL       = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GEMINI_IMAGE_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:predict"

# fal.ai model IDs
FAL_MODELS = {
    "flux":     "fal-ai/flux-pro/v1.1",
    "ideogram": "fal-ai/ideogram/v3",
}
FAL_BASE = "https://fal.run"

# Lessons that need image generation — either existing empty src blocks or
# zero image blocks altogether (insert mode auto-triggers for the latter).
# NOTE: Mousetrap screenshot-crop lessons (M-002..M-006, M-011, M-012, M-014,
# M-018, M-019) excluded — handled by mousetrap_crop_images.py.
EMPTY_IMAGE_LESSONS = [
    # Creationeering — originally had empty src blocks
    "C-001","C-004","C-005","C-006","C-008","C-009","C-010",
    "C-012","C-013","C-014","C-015","C-016","C-017","C-018","C-019",
    # Substantial lessons (>8 blocks) confirmed with zero image blocks (audit 2026-05-28)
    "C-011","C-020","C-021","C-022","C-024","C-025","C-026","C-027","C-028",
    "C-029","C-030","C-035","C-054","C-074",
    "M-001","M-009","M-015","M-016","M-017","M-019","M-020","M-021","M-022",
    "M-023","M-024","M-035","M-042","M-045","M-054","M-060","M-062","M-066","M-069",
]

# Auto-insert constants — used when a lesson has zero image blocks
_INSERT_INTERVAL   = 4   # insert after every Nth consecutive text block
_MAX_INSERT        = 3   # cap images per lesson


def load_env() -> dict:
    env = {}
    for name in [".env", ".env.local"]:
        path = Path(__file__).parent.parent / name
        if path.exists():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip().strip('"\'')
    return env


def load_log() -> dict:
    if LOG_PATH.exists():
        with open(LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_log(log: dict):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


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


def upload_image(lesson_id: str, filename: str, img_bytes: bytes, mime: str = "image/png") -> str | None:
    """Upload image bytes to Firebase Storage via platform API. Returns URL or None."""
    payload = json.dumps({
        "lessonId": lesson_id,
        "filename": filename,
        "mimeType": mime,
        "dataBase64": base64.b64encode(img_bytes).decode("utf-8"),
    }).encode("utf-8")
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
        print(f"  Image upload HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
        return None
    except Exception as e:
        print(f"  Image upload error: {e}")
        return None


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).strip()


def _insertion_points(blocks: list) -> list[tuple[int, str]]:
    """Return (insert_after_index, context_text) for auto-insert mode."""
    import random, string
    points = []
    consecutive = 0
    for i, block in enumerate(blocks):
        if block.get("type") == "text":
            consecutive += 1
            if consecutive % _INSERT_INTERVAL == 0 and i < len(blocks) - 1:
                ctx = " ".join(
                    strip_tags(blocks[j].get("data", {}).get("html", ""))[:200]
                    for j in range(max(0, i - 2), i + 1)
                    if blocks[j].get("type") == "text"
                )
                points.append((i, ctx))
                if len(points) >= _MAX_INSERT:
                    break
        else:
            consecutive = 0
    return points


def _make_empty_image_block(caption: str) -> dict:
    import random, string
    bid = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return {
        "id": bid,
        "type": "image",
        "data": {"src": "", "width": "100%", "caption": caption},
        "meta": {"spacing": "md", "qcStatus": "pending"},
    }


def build_context(lesson: dict, block_index: int) -> str:
    """Extract context for image prompt: title + caption + neighboring text blocks."""
    title  = lesson.get("title", "Engineering lesson")
    blocks = lesson.get("blocks", [])
    block  = blocks[block_index]

    caption = block.get("data", {}).get("caption", "") or block.get("data", {}).get("alt", "")

    # Gather text from up to 2 blocks before
    context_pieces = []
    for i in range(max(0, block_index - 2), block_index):
        b = blocks[i]
        if b.get("type") in ("text", "heading"):
            text = strip_tags(b.get("data", {}).get("html", ""))
            if text:
                context_pieces.append(text[:200])

    context = " ".join(context_pieces)
    return title, caption, context


def make_image_prompt(api_key: str, lesson_title: str, caption: str, context: str) -> str:
    """Use Gemini to write a detailed image generation prompt."""
    system_prompt = f"""You write image generation prompts for Genesis K-12 Academy's middle school engineering curriculum.

Lesson title: {lesson_title}
Image caption/alt: {caption if caption else '(none)'}
Surrounding content: {context[:400] if context else '(none)'}

Write a single, detailed image generation prompt for an educational illustration suitable for 6th-8th grade students.
Requirements:
- Accurately depict the specific engineering or science concept described — this is the top priority
- Clean, professional educational illustration style
- No text or labels in the image
- Age-appropriate, faith-neutral (faith is welcome but not required)
- Focus on realistic or diagram-style depictions of tools, materials, processes, or phenomena from the lesson
- Do NOT impose color schemes or brand colors — use whatever colors best serve the illustration

Return ONLY the image prompt text, no explanation."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": system_prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 300},
    }).encode("utf-8")
    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        parts = data["candidates"][0]["content"]["parts"]
        return " ".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip()
    except Exception as e:
        # Fallback: use caption or lesson title
        return f"Educational illustration accurately depicting a middle school engineering lesson on {lesson_title}. {caption or 'Detailed diagram or depiction of the concept.'} Clean professional style, no text or labels."


def generate_image(api_key: str, prompt: str, logo_b64: str | None = None) -> bytes | None:
    """Generate image using Imagen 3. Returns PNG bytes or None."""
    # logo_b64 unused — Imagen 3 predict endpoint is text-only
    full_prompt = (
        "Educational illustration, clean professional style, accurate depiction of the concept, "
        "no text or labels. " + prompt
    )
    payload = json.dumps({
        "instances": [{"prompt": full_prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "4:3"},
    }).encode("utf-8")

    url = f"{GEMINI_IMAGE_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        predictions = data.get("predictions", [])
        if predictions and "bytesBase64Encoded" in predictions[0]:
            return base64.b64decode(predictions[0]["bytesBase64Encoded"])
        print("    No image data in Imagen response")
        return None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"    Imagen HTTP {e.code}: {body[:300]}")
        return None
    except Exception as e:
        print(f"    Imagen error: {e}")
        return None


def generate_image_fal(fal_key: str, model: str, prompt: str) -> bytes | None:
    """Generate image via fal.ai (FLUX or Ideogram). Returns JPEG bytes or None."""
    model_id = FAL_MODELS.get(model)
    if not model_id:
        print(f"    Unknown fal.ai model: {model}")
        return None

    full_prompt = (
        "Educational illustration, clean professional style, accurate depiction of the concept, "
        "no distracting text. " + prompt
    )

    if model == "flux":
        body = {
            "prompt": full_prompt,
            "image_size": "landscape_4_3",
            "num_images": 1,
            "output_format": "jpeg",
            "safety_tolerance": "2",
        }
    else:  # ideogram
        body = {
            "prompt": full_prompt,
            "aspect_ratio": "4:3",
            "rendering_speed": "QUALITY",
            "style_type": "ILLUSTRATION",
        }

    payload = json.dumps(body).encode("utf-8")
    url = f"{FAL_BASE}/{model_id}"
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Key {fal_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
        images = result.get("images", [])
        if not images:
            print(f"    No images in fal.ai response")
            return None
        img_url = images[0].get("url", "")
        if not img_url:
            return None
        # Download from the returned CDN URL
        with urllib.request.urlopen(img_url, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"    fal.ai HTTP {e.code}: {body_text[:300]}")
        return None
    except Exception as e:
        print(f"    fal.ai error: {e}")
        return None


def process_lesson(lesson_id: str, api_key: str, fal_key: str | None, logo_b64: str | None, dry_run: bool, log: dict, model: str = "imagen") -> str:
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return "fetch_error"

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    empty = [(i, b) for i, b in enumerate(blocks)
             if b.get("type") == "image" and not b.get("data", {}).get("src", "")]

    # Auto-insert mode: lesson has no image blocks at all — create empty slots first
    if not empty and not any(b.get("type") == "image" for b in blocks):
        points = _insertion_points(blocks)
        if not points:
            print(f"  [{lesson_id}] No empty image blocks and no text runs long enough — skipping")
            return "skipped"
        print(f"  [{lesson_id}] Zero image blocks — auto-inserting {len(points)} slot(s)")
        # Insert in reverse so indices remain valid
        for insert_after, ctx in reversed(points):
            new_block = _make_empty_image_block(ctx[:120])
            blocks.insert(insert_after + 1, new_block)
        # Rebuild empty list from modified blocks
        empty = [(i, b) for i, b in enumerate(blocks)
                 if b.get("type") == "image" and not b.get("data", {}).get("src", "")]

    if not empty:
        print(f"  [{lesson_id}] No empty image blocks — skipping")
        return "skipped"

    print(f"\n  [{lesson_id}] {title} — {len(empty)} empty image block(s)")

    if dry_run:
        for i, b in empty:
            _, caption, context = build_context(lesson, i)
            print(f"    Block {i}: caption={repr(caption[:60])} ctx={repr(context[:60])}")
        return "would_fill"

    updated_blocks = list(blocks)
    filled = 0

    for block_idx, block in empty:
        lesson_title, caption, context = build_context(lesson, block_idx)
        safe_caption = re.sub(r"\s+", "_", re.sub(r"[^\w\s-]", "", (caption or lesson_title).strip()))[:25].strip("_")
        filename = f"{lesson_id.lower()}_img{block_idx:03d}_{safe_caption}.png"

        print(f"    Block {block_idx}: generating image [{model}]...")
        prompt = make_image_prompt(api_key, lesson_title, caption, context)
        print(f"    Prompt: {prompt[:100]}...")

        if model in ("flux", "ideogram"):
            if not fal_key:
                print(f"    FAL_KEY not set — cannot use {model}")
                continue
            img_bytes = generate_image_fal(fal_key, model, prompt)
        else:
            img_bytes = generate_image(api_key, prompt, logo_b64)

        if not img_bytes:
            print(f"    Image generation failed — skipping block {block_idx}")
            continue

        print(f"    Generated {len(img_bytes)//1024}KB — uploading...")
        url = upload_image(lesson_id, filename, img_bytes)
        if not url:
            print(f"    Upload failed — skipping block {block_idx}")
            continue

        print(f"    Uploaded: {url[:80]}...")
        updated_blocks[block_idx] = {
            **block,
            "data": {
                **block.get("data", {}),
                "src": url,
                "alt": caption or lesson_title,
            },
            "meta": {**block.get("meta", {}), "qcStatus": "pending"},
        }
        filled += 1
        time.sleep(1)  # rate limit

    if filled == 0:
        return "error"

    ok = patch_lesson(lesson_id, updated_blocks)
    if ok:
        log[lesson_id] = {"status": "done", "filled": filled, "total": len(empty)}
        print(f"    Patched OK ({filled}/{len(empty)} blocks filled)")
        return "done"
    else:
        return "patch_error"


def main():
    parser = argparse.ArgumentParser(description="Generate images for empty lesson image blocks")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--lesson-id", help="Single lesson ID")
    parser.add_argument("--course",    choices=["C", "M"])
    parser.add_argument("--model",     choices=["imagen", "flux", "ideogram"], default="imagen",
                        help="Image model: imagen (default), flux, ideogram")
    args = parser.parse_args()

    env     = load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found in .env")
        sys.exit(1)

    fal_key = os.environ.get("FAL_KEY") or env.get("FAL_KEY")
    if args.model in ("flux", "ideogram") and not fal_key:
        print(f"FAL_KEY not found in .env — required for --model {args.model}")
        sys.exit(1)

    logo_b64 = None
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode("utf-8")
        print(f"Logo loaded: {LOGO_PATH}")

    if args.lesson_id:
        lessons = [args.lesson_id]
    elif args.course:
        lessons = [l for l in EMPTY_IMAGE_LESSONS if l.startswith(args.course + "-")]
    else:
        lessons = EMPTY_IMAGE_LESSONS

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\nQC Generate Lesson Images [{mode}] [{args.model.upper()}]: {len(lessons)} lessons")
    print("=" * 60)

    log    = load_log()
    counts = {"done": 0, "would_fill": 0, "skipped": 0, "fetch_error": 0, "error": 0, "patch_error": 0}

    for lid in lessons:
        status = process_lesson(lid, api_key, fal_key, logo_b64, args.dry_run, log, args.model)
        counts[status] = counts.get(status, 0) + 1
        time.sleep(0.5)

    if not args.dry_run:
        save_log(log)

    print(f"\n{'=' * 60}")
    print(f"Done: {counts}")
    if args.dry_run:
        print("Run without --dry-run to generate.")


if __name__ == "__main__":
    main()
