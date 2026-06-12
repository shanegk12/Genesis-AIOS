"""
Genesis K-12 QC — Image Text Overlay Audit

Scans every lesson image block with Gemini Vision to detect text that has been
burned into the image graphic itself (scripture verses, faith callout text,
captions overlaid on illustrations).

Why this matters:
  - Scripture/faith text on images was an early generation pattern. Since then,
    that content lives in bordered-note/callout blocks instead.
  - Images should be clean illustrations — no overlaid text.
  - Technical diagram labels (axis labels, flowchart nodes, legend items) are fine
    and will NOT be flagged.

Output: qc_image_text_audit_report.json — list of flagged blocks ready for
regen by the cloud pipeline.

Usage:
  python scripts/qc_image_text_audit.py --dry-run          # list image blocks only
  python scripts/qc_image_text_audit.py                    # scan all lessons
  python scripts/qc_image_text_audit.py --lesson-id C-025  # single lesson
  python scripts/qc_image_text_audit.py --course C         # Creationeering only
  python scripts/qc_image_text_audit.py --course M         # Mousetrap only
  python scripts/qc_image_text_audit.py --skip-done        # resume interrupted run

Requires:
  GEMINI_API_KEY in .env or environment
"""

import argparse, base64, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
REPORT_PATH   = Path(__file__).parent / "qc_image_text_audit_report.json"

GEMINI_MODEL  = "gemini-2.5-flash"
GEMINI_URL    = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

MAX_IMAGE_BYTES = 4 * 1024 * 1024  # skip images > 4MB

# Scripture book names used for nearby-block detection
SCRIPTURE_PATTERN = re.compile(
    r"\b(Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles"
    r"|Ezra|Nehemiah|Esther|Job|Psalm|Psalms|Proverbs|Ecclesiastes|Isaiah|Jeremiah|Lamentations"
    r"|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai"
    r"|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|Galatians|Ephesians"
    r"|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|Hebrews|James|Peter|Jude"
    r"|Revelation)\b"
)

VISION_PROMPT = """\
Look carefully at this image. Determine whether any text, words, or numbers are \
overlaid, embedded, or burned into the image graphic itself.

IMPORTANT distinctions:
- FLAG: Scripture verses printed across a landscape or illustration \
  (e.g., "Jeremiah 33:3 — Call to me and I will answer you")
- FLAG: Faith quotes or motivational text overlaid on a photo or illustration
- FLAG: A caption sentence baked into the image artwork itself
- DO NOT FLAG: Axis labels, legend entries, flowchart node labels, table headers, \
  equation variables — these are functional diagram labels, not overlaid text
- DO NOT FLAG: Small watermarks or "Genesis K-12" branding text

Respond ONLY with valid JSON, no explanation:
{
  "has_text_overlay": true/false,
  "text_content": "exact text found on image, or empty string",
  "text_type": "scripture|callout|caption|technical|none",
  "confidence": "high|medium|low",
  "notes": "one sentence describing what you found, or empty string"
}

text_type key:
  scripture — a Bible verse or book:chapter:verse reference
  callout   — a faith quote, heading, or motivational phrase burned onto the image
  caption   — a descriptive caption sentence baked into the image graphic
  technical — functional diagram text (axis, legend, flowchart label) — not flagged
  none      — no text overlay detected"""


# ── Helpers ────────────────────────────────────────────────────────────────────

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


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        print(f"[WARN] Manifest not found at {MANIFEST_PATH} — run lessons_manifest build first")
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # Manifest is either a list or {"meta": ..., "lessons": [...]}
    return data if isinstance(data, list) else data.get("lessons", [])


def load_report() -> dict:
    if REPORT_PATH.exists():
        with open(REPORT_PATH, encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {"flagged": [], "checked": {}, "summary": {}}


def save_report(report: dict):
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)


def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  [WARN] HTTP {e.code} fetching {lesson_id}")
        return None
    except Exception as e:
        print(f"  [WARN] fetch error: {e}")
        return None


def fetch_image_bytes(url: str) -> tuple[bytes | None, str]:
    """Fetch image bytes from a URL. Returns (bytes, mime_type) or (None, '')."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GK12-QC/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            return resp.read(), mime
    except Exception:
        return None, ""


def check_image_for_text(img_bytes: bytes, mime_type: str, api_key: str) -> dict:
    """Send image bytes to Gemini Vision. Returns parsed JSON result."""
    if len(img_bytes) > MAX_IMAGE_BYTES:
        return {"error": f"Image too large ({len(img_bytes) // 1024}KB)"}

    # Normalize MIME
    if mime_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        mime_type = "image/jpeg"

    b64 = base64.b64encode(img_bytes).decode("utf-8")
    payload = json.dumps({
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": b64}},
                {"text": VISION_PROMPT},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 300,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{GEMINI_URL}?key={api_key}",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        parts = data["candidates"][0]["content"]["parts"]
        raw = " ".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip()

        match = re.search(r"\{[\s\S]*?\}", raw)
        if match:
            return json.loads(match.group())
        return {"error": f"No JSON in response: {raw[:100]}"}

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def has_faith_block_nearby(blocks: list, img_idx: int, window: int = 3) -> bool:
    """
    Returns True if a faith/scripture callout block exists within `window`
    blocks of the image — meaning the verse has already been moved to content.
    """
    start = max(0, img_idx - window)
    end   = min(len(blocks), img_idx + window + 1)
    for b in blocks[start:end]:
        btype = b.get("type", "")
        bdata = b.get("data", {})
        html  = bdata.get("html", "") + bdata.get("text", "")
        if btype in ("callout", "bordered-note") and SCRIPTURE_PATTERN.search(html):
            return True
        # Also catch plain text blocks that contain a scripture reference like "John 3:16"
        if re.search(r"[A-Z][a-z]+\s+\d+:\d+", html):
            return True
    return False


# ── Per-lesson processing ──────────────────────────────────────────────────────

def process_lesson(lesson_id: str, api_key: str, dry_run: bool) -> list[dict]:
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return []

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    image_blocks = [
        (i, b) for i, b in enumerate(blocks)
        if b.get("type") == "image" and b.get("data", {}).get("src", "")
    ]

    if not image_blocks:
        return []

    print(f"\n  [{lesson_id}] {title}")
    print(f"  {len(image_blocks)} image block(s) to check")

    if dry_run:
        for idx, block in image_blocks:
            data = block.get("data", {})
            print(f"    Block {idx}: {data.get('src','')[:70]}…")
        return []

    flagged: list[dict] = []

    for idx, block in image_blocks:
        data = block.get("data", {})
        src  = data.get("src", "")
        alt  = data.get("alt", "") or data.get("caption", "")

        print(f"    Block {idx}: fetching…", end=" ", flush=True)
        img_bytes, mime = fetch_image_bytes(src)
        if not img_bytes:
            print("fetch failed — skipping")
            continue

        kb = len(img_bytes) // 1024
        print(f"{kb}KB — analyzing…", end=" ", flush=True)
        result = check_image_for_text(img_bytes, mime, api_key)

        if "error" in result:
            print(f"ERROR: {result['error'][:80]}")
            continue

        has_overlay = result.get("has_text_overlay", False)
        text_type   = result.get("text_type", "none")
        confidence  = result.get("confidence", "low")
        detected    = result.get("text_content", "")
        notes       = result.get("notes", "")

        # Only flag scripture, callout, or caption overlays — technical labels are fine
        should_flag = has_overlay and text_type in ("scripture", "callout", "caption")

        if should_flag:
            faith_nearby = has_faith_block_nearby(blocks, idx)
            entry = {
                "lessonId":         lesson_id,
                "lessonTitle":      title,
                "blockIdx":         idx,
                "imageUrl":         src,
                "alt":              alt,
                "detectedText":     detected,
                "textType":         text_type,
                "confidence":       confidence,
                "notes":            notes,
                "faithBlockNearby": faith_nearby,
                "action":           "regen_without_text",
            }
            flagged.append(entry)
            nearby_note = " ✓ faith block nearby" if faith_nearby else " ⚠ no nearby faith block"
            print(f"FLAGGED [{text_type}/{confidence}]{nearby_note}")
            print(f'      → "{detected[:80]}"')
        else:
            label = f"[{text_type}]" if has_overlay else "clean"
            print(f"ok {label} ({confidence})")

        time.sleep(0.4)  # rate limit Gemini

    return flagged


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Audit lesson images for burned-in text overlays")
    parser.add_argument("--dry-run",    action="store_true", help="List image blocks, skip Gemini Vision calls")
    parser.add_argument("--lesson-id", help="Check a single lesson")
    parser.add_argument("--course",    choices=["C", "M"], help="Check only C- or M- lessons")
    parser.add_argument("--skip-done", action="store_true", help="Skip lessons already recorded in the report")
    args = parser.parse_args()

    env     = load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    if not api_key and not args.dry_run:
        print("GEMINI_API_KEY not found in environment or .env")
        sys.exit(1)

    # Build lesson list
    if args.lesson_id:
        lessons = [args.lesson_id]
    else:
        manifest = load_manifest()
        if not manifest:
            sys.exit(1)
        if args.course:
            lessons = [l["id"] for l in manifest if l["id"].startswith(args.course + "-")]
        else:
            lessons = [l["id"] for l in manifest]

    # Resume support
    report = load_report()
    if args.skip_done:
        done    = set(report.get("checked", {}).keys())
        lessons = [l for l in lessons if l not in done]
        if done:
            print(f"[skip-done] Skipping {len(done)} already-checked lessons")

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\nGenesis K-12 QC — Image Text Overlay Audit [{mode}]")
    print(f"Scanning {len(lessons)} lesson(s) for scripture/callout text burned into images")
    print("=" * 68)

    all_flagged: list[dict] = list(report.get("flagged", []))
    checked: dict            = dict(report.get("checked", {}))

    for lesson_id in lessons:
        flagged = process_lesson(lesson_id, api_key or "", args.dry_run)
        all_flagged.extend(flagged)
        if not args.dry_run:
            checked[lesson_id] = {
                "checkedAt":    datetime.now(timezone.utc).isoformat(),
                "flaggedCount": len(flagged),
                "flaggedBlocks": [f["blockIdx"] for f in flagged],
            }
        time.sleep(0.3)

    # Persist report
    if not args.dry_run:
        scripture_count = sum(1 for f in all_flagged if f["textType"] == "scripture")
        callout_count   = sum(1 for f in all_flagged if f["textType"] == "callout")
        caption_count   = sum(1 for f in all_flagged if f["textType"] == "caption")

        report = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "flagged":     all_flagged,
            "checked":     checked,
            "summary": {
                "totalLessonsChecked": len(checked),
                "totalFlagged":        len(all_flagged),
                "byType": {
                    "scripture": scripture_count,
                    "callout":   callout_count,
                    "caption":   caption_count,
                },
            },
        }
        save_report(report)
        print(f"\nReport saved → {REPORT_PATH}")

    # Print summary
    print(f"\n{'=' * 68}")
    new_flagged = [f for f in all_flagged if f["lessonId"] in (lessons if not args.skip_done else lessons)]
    print(f"Done. {len(new_flagged)} image(s) flagged across {len(lessons)} lesson(s).")

    if new_flagged:
        print("\nFlagged images (need regen without text overlay):")
        for f in new_flagged:
            faith = " [faith block nearby ✓]" if f.get("faithBlockNearby") else " [⚠ check content]"
            print(f"  [{f['lessonId']}] block {f['blockIdx']} — {f['textType']}/{f['confidence']}{faith}")
            if f["detectedText"]:
                print(f'    text: "{f["detectedText"][:80]}"')

    if args.dry_run:
        print("\nRun without --dry-run to call Gemini Vision on each image.")
    else:
        print(f"\nNext step: feed {REPORT_PATH.name} to the cloud regen pipeline.")
        print("  --action regen_without_text  (add PIPELINE_KEY dispatch to Cloud Tasks)")


if __name__ == "__main__":
    main()
