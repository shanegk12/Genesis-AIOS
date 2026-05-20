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

import argparse, base64, json, os, sys, time, urllib.request, urllib.error
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

Return ONLY valid JSON — a bare array [...] with no explanation, no markdown fences.
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_screenshots(folder: Path) -> list[dict]:
    """Return sorted list of base64-encoded image dicts for the Claude API."""
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in exts],
        key=lambda f: f.name,
    )
    if not files:
        raise FileNotFoundError(f"No screenshots found in {folder}")
    if len(files) > 20:
        print(f"  Warning: {len(files)} screenshots found; Claude Vision limit is 20. Using first 20.")
        files = files[:20]

    images = []
    for f in files:
        ext = f.suffix.lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
        data = base64.standard_b64encode(f.read_bytes()).decode()
        images.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": data},
        })
        print(f"  Loaded: {f.name} ({len(data) // 1024} KB encoded)")
    return images


def call_claude_vision(lesson_id: str, lesson_title: str, images: list[dict]) -> list[dict]:
    """Send screenshots to Claude Vision and return parsed block array."""
    if not ANTHROPIC_KEY:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Export it before running:\n"
            "  $env:ANTHROPIC_API_KEY = 'sk-ant-...'"
        )

    content = images + [{
        "type": "text",
        "text": (
            f'Lesson ID: {lesson_id}\n'
            f'Lesson Title: {lesson_title}\n\n'
            + BLOCK_SCHEMA_PROMPT
        ),
    }]

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 8192,
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

    print(f"\n  Sending {len(images)} screenshot(s) to Claude Vision...")
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())

    raw = result["content"][0]["text"].strip()

    # Strip markdown fences if Claude wrapped the JSON
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines()
            if not line.strip().startswith("```")
        ).strip()

    blocks = json.loads(raw)
    if not isinstance(blocks, list):
        raise ValueError("Expected a JSON array from Claude Vision")

    # Inject IDs and ensure meta
    import uuid
    for b in blocks:
        b.setdefault("id", str(uuid.uuid4()))
        b.setdefault("meta", {"spacing": "md", "qcStatus": "pending"})

    return blocks


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
    images = load_screenshots(folder)
    print(f"  {len(images)} screenshot(s) loaded")

    # Get lesson title for context
    print(f"  Fetching lesson title...")
    title = fetch_lesson_title(lesson_id)
    print(f"  Title: {title}")

    # Send to Claude Vision
    blocks = call_claude_vision(lesson_id, title, images)
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
        confirm = input(f"\n  Patch {lesson_id} on live platform with {len(blocks)} blocks? [y/N] ")
        if confirm.strip().lower() == "y":
            ok = patch_lesson(lesson_id, blocks)
            print(f"  {'✓ Patched' if ok else '⚠ Patch failed'}: {lesson_id}")
        else:
            print("  Skipped.")
    else:
        print(f"\n  Run with --patch to push to platform, or --out blocks.json to save.")

    # Always print the JSON so it can be reviewed
    print(f"\n{'='*60}")
    print(json.dumps(blocks, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
