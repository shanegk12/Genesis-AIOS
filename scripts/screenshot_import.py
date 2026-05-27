"""
Genesis K-12 — Screenshot → Block Importer

Reads a folder of lesson screenshots, sends them to Claude Vision in order,
and extracts a structured Block[] that matches the platform schema.

Workflow:
  1. In LearnWorlds, scroll through the lesson and take screenshots:
       Win+Shift+S  → save each as 01.png, 02.png, 03.png ... in order
  2. Put screenshots in:  screenshots/{lesson-id}/01.png  02.png ...
  3. Run this script — review the extracted JSON, then optionally patch live.

Usage:
  python scripts/screenshot_import.py C-007              # preview JSON only
  python scripts/screenshot_import.py C-007 --patch      # patch lesson live
  python scripts/screenshot_import.py C-007 --out out.json  # save JSON to file

Screenshot folder:  d:\\AIOS\\screenshots\\{lesson-id}\\
Supported formats:  .png  .jpg  .jpeg  .webp
Max images:         20 per call (Claude API limit)
"""

import argparse, base64, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

SCREENSHOTS_ROOT = Path(__file__).parent.parent / "screenshots"
LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY     = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL     = "claude-sonnet-4-6"

BLOCK_SCHEMA_PROMPT = """
You are converting a LearnWorlds lesson into structured content blocks for the Genesis K-12 Academy learning platform.

The screenshots are in ORDER from top to bottom of the lesson. Treat them as a single continuous document.

Extract the lesson content and return a JSON array of blocks. Each block follows this schema:

{
  "type": "<block type>",
  "data": { ... type-specific fields ... },
  "meta": { "spacing": "md", "qcStatus": "pending" }
}

BLOCK TYPES AND DATA SHAPES:

text — paragraphs, headings, lists (use proper HTML tags):
  { "html": "<h2>Section Title</h2><p>Body text here.</p><ul><li>Item</li></ul>" }

callout — visually distinct highlighted box (tip, warning, biblical quote, faith note):
  { "variant": "tip"|"warning"|"info"|"success"|"biblical", "html": "<p>Content.</p>" }
  Choose "biblical" for scripture or faith references. "tip" for study tips. "warning" for common mistakes.

vocab — term + definition list:
  { "columns": 1|2, "items": [{ "term": "Term", "definition": "Definition here." }] }
  Use 2 columns if there are 4+ terms. 1 column for 1-3 terms.

image — image or diagram placeholder (describe what you see in the image):
  { "src": "", "width": "100%", "caption": "Description of what this image shows" }
  Use this for any diagram, photo, illustration, or chart visible in the screenshots.
  Leave src empty — it will be filled by the image backfill pipeline.

accordion — collapsible section with a title:
  { "title": "Section Title", "html": "<p>Content inside.</p>", "openByDefault": false }

accordion-grid — grid of collapsible Q&A or key concept cards:
  { "columns": 2, "items": [{ "title": "Card Title", "html": "<p>Card content.</p>" }] }
  Use for "Check for Understanding" sections, key concept grids, or FAQ-style content.

math — standalone LaTeX equation:
  { "latex": "F = m \\\\cdot a", "display": true }
  Use for any equation shown on its own line. For inline math within prose, use <span data-math="..."> inside a text block.

divider — horizontal rule between major sections:
  { "style": "solid" }

RULES:
- Each <h2> heading signals a new section and should start a new text block.
- "Lesson Overview" and "Learning Objectives" are text blocks (not callouts).
- "Key Vocabulary" sections → vocab block.
- Biblical references, scripture quotes, faith reflections → callout with variant "biblical".
- Study tips, engineering journal prompts → callout with variant "tip".
- "Check for Understanding" or review questions → accordion-grid (each question is a card).
- If you see a diagram, chart, or photograph → image block with a descriptive caption.
- Preserve all bullet lists as <ul><li> HTML inside text blocks.
- Bold key terms with <strong>. Do not use markdown (**) — use HTML tags.
- If you cannot read text clearly, write [illegible] so it can be fixed manually.
- Do NOT invent content. Only extract what is visible in the screenshots.
- IMPORTANT: All double-quote characters inside HTML string values MUST be written as &quot; — never use a raw " inside an HTML attribute or text value, as it will break JSON parsing.

Return ONLY valid JSON — a bare array [...] with no explanation, no markdown fences.
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _natural_key(path: Path):
    """Natural sort: 1, 2, 10 instead of 1, 10, 2. Handles letter prefixes (B1, B2, B10)."""
    parts = re.split(r"(\d+)", path.stem)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


CHUNK_SIZE = 12  # conservative — large lessons have big screenshots that generate long JSON


def load_all_screenshots(folder: Path) -> list[tuple[str, str, str]]:
    """Return sorted list of (filename, mime_type, base64_data) for all screenshots."""
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in exts],
        key=_natural_key,
    )
    if not files:
        raise FileNotFoundError(f"No screenshots found in {folder}")

    result = []
    for f in files:
        ext = f.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
        data = base64.standard_b64encode(f.read_bytes()).decode()
        result.append((f.name, mime, data))
        print(f"  Loaded: {f.name} ({len(data) // 1024} KB encoded)")
    return result


def _encode_images(raw_list: list[tuple]) -> list[dict]:
    return [
        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
        for _, mime, data in raw_list
    ]


def call_claude_vision_chunk(
    lesson_id: str,
    lesson_title: str,
    images: list[dict],
    chunk_index: int,
    total_chunks: int,
) -> list[dict]:
    """Send one chunk of screenshots to Claude Vision and return parsed block array."""
    if not ANTHROPIC_KEY:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Export it before running:\n"
            "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'"
        )

    if total_chunks > 1:
        chunk_note = (
            f"\nNOTE: This is chunk {chunk_index + 1} of {total_chunks}. "
            f"Extract only the content visible in these screenshots. "
            + ("Start from the beginning of the lesson." if chunk_index == 0
               else "Continue from where the previous chunk ended — do NOT repeat earlier content.")
        )
    else:
        chunk_note = ""

    content = images + [{
        "type": "text",
        "text": (
            f"Lesson ID: {lesson_id}\n"
            f"Lesson Title: {lesson_title}\n"
            + chunk_note + "\n\n"
            + BLOCK_SCHEMA_PROMPT
        ),
    }]

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": content}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    label = f"chunk {chunk_index + 1}/{total_chunks}" if total_chunks > 1 else "all"
    print(f"\n  Sending {len(images)} screenshot(s) to Claude Vision ({label})...")
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read())

    raw = result["content"][0]["text"].strip()
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines()
            if not line.strip().startswith("```")
        ).strip()

    try:
        blocks = json.loads(raw)
    except json.JSONDecodeError as e:
        debug_path = Path(__file__).parent.parent / f"_vision_raw_{lesson_id}_chunk{chunk_index}.txt"
        debug_path.write_text(raw, encoding="utf-8")
        raise ValueError(
            f"JSON parse error in chunk {chunk_index + 1}: {e}\n"
            f"Raw response saved to {debug_path} for inspection"
        )
    if not isinstance(blocks, list):
        raise ValueError(f"Expected JSON array from Claude Vision (chunk {chunk_index + 1})")

    import uuid
    for b in blocks:
        b.setdefault("id", str(uuid.uuid4()))
        b.setdefault("meta", {"spacing": "md", "qcStatus": "pending"})

    return blocks


def call_claude_vision(lesson_id: str, lesson_title: str, raw_images: list[tuple]) -> list[dict]:
    """Chunk if needed, call Vision on each chunk, merge results. Retries on JSON parse errors."""
    total = len(raw_images)
    chunks = [raw_images[i:i + CHUNK_SIZE] for i in range(0, total, CHUNK_SIZE)]
    n_chunks = len(chunks)

    all_blocks = []
    for i, chunk in enumerate(chunks):
        images = _encode_images(chunk)
        last_err = None
        for attempt in range(3):
            try:
                blocks = call_claude_vision_chunk(lesson_id, lesson_title, images, i, n_chunks)
                if attempt > 0:
                    print(f"    [retry {attempt}] chunk {i+1} succeeded")
                all_blocks.extend(blocks)
                break
            except ValueError as e:
                last_err = e
                print(f"    [retry {attempt+1}/3] chunk {i+1} parse error — retrying...")
                time.sleep(3)
        else:
            raise last_err
        if i < n_chunks - 1:
            time.sleep(2)

    return all_blocks


def fetch_lesson_title(lesson_id: str) -> str:
    url = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {PLATFORM_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("title") or data.get("topic") or lesson_id
    except Exception:
        return lesson_id


def patch_lesson(lesson_id: str, blocks: list[dict]) -> bool:
    payload = json.dumps({"blocks": blocks, "contentSource": "platform"}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lesson_id", help="Lesson ID, e.g. C-007")
    parser.add_argument("--patch",   action="store_true", help="PATCH blocks to live platform after extraction")
    parser.add_argument("--yes",     action="store_true", help="Skip confirmation prompt (for batch use)")
    parser.add_argument("--out",     help="Save extracted JSON to this file path")
    parser.add_argument("--folder",  help="Custom screenshot folder (default: screenshots/{lesson_id}/)")
    args = parser.parse_args()

    lesson_id = args.lesson_id.upper()
    folder    = Path(args.folder) if args.folder else SCREENSHOTS_ROOT / lesson_id

    if not folder.exists():
        print(f"Screenshot folder not found: {folder}")
        print(f"Create it and add numbered screenshots (01.png, 02.png, …)")
        sys.exit(1)

    print(f"\nScreenshot Import: {lesson_id}")
    print(f"Folder: {folder}")

    # Load screenshots
    raw_images = load_all_screenshots(folder)
    n_chunks = (len(raw_images) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"  {len(raw_images)} screenshot(s) loaded → {n_chunks} chunk(s) of up to {CHUNK_SIZE}")

    # Get lesson title for context
    print(f"  Fetching lesson title...")
    title = fetch_lesson_title(lesson_id)
    print(f"  Title: {title}")

    # Send to Claude Vision (chunked automatically if >CHUNK_SIZE images)
    blocks = call_claude_vision(lesson_id, title, raw_images)
    print(f"\n  Extracted {len(blocks)} block(s):")
    for b in blocks:
        btype = b.get("type", "?")
        summary = ""
        if btype == "text":
            html = b.get("data", {}).get("html", "")
            first = html[:60].replace("\n", " ")
            summary = f" → {first!r}"
        elif btype == "vocab":
            n = len(b.get("data", {}).get("items", []))
            summary = f" → {n} term(s)"
        elif btype == "callout":
            summary = f" [{b.get('data',{}).get('variant','?')}]"
        elif btype == "image":
            summary = f" → {b.get('data',{}).get('caption','')[:50]!r}"
        elif btype == "math":
            summary = f" → {b.get('data',{}).get('latex','')[:40]!r}"
        print(f"    {btype}{summary}")

    # Save to file
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(blocks, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Saved to {out_path}")

    # Patch live
    if args.patch:
        if not args.yes:
            confirm = input(f"\n  Patch {lesson_id} on live platform with {len(blocks)} blocks? [y/N] ")
            if confirm.strip().lower() != "y":
                print("  Skipped.")
                return
        ok = patch_lesson(lesson_id, blocks)
        print(f"  {'✓ Patched' if ok else '⚠ Patch failed'}: {lesson_id}")
    else:
        print(f"\n  Run with --patch to push to platform, or --out blocks.json to save.")

    # Always print the JSON so it can be reviewed
    print(f"\n{'='*60}")
    print(json.dumps(blocks, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
