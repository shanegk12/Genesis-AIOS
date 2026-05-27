"""
Genesis K-12 QC — Generate Interactives from Platform Lesson Content

For thin lessons that lack Google Docs sources, this script:
  1. Fetches lesson title + blocks from the platform API
  2. Asks Gemini to generate flashcards.html and concept.html from that content
  3. Saves HTML files to scripts/interactives/{lessonId}/
  4. Uploads to Firebase Storage via ADC session
  5. Patches lesson with embed blocks

Usage:
  python scripts/qc_gen_platform_interactives.py --dry-run
  python scripts/qc_gen_platform_interactives.py --save
  python scripts/qc_gen_platform_interactives.py --lesson-id C-011 --save
"""

import argparse, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

LIVE_URL     = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
INTERACTIVES_DIR = Path(__file__).parent / "interactives"
LOG_PATH = Path(__file__).parent / "platform_interactives_log.json"

STORAGE_BUCKET  = "genesis-modularity.firebasestorage.app"
UPLOAD_API_BASE = f"https://storage.googleapis.com/upload/storage/v1/b/{STORAGE_BUCKET}/o"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

EMBED_HEIGHT = 520

# Thin lessons without Google Docs interactive generation
TARGET_LESSONS = ["C-011", "C-023", "M-013", "C-024", "M-009"]


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


def gen_id() -> str:
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


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


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html).strip()


def extract_text_content(lesson: dict) -> str:
    """Extract all text from lesson blocks into a single string."""
    parts = []
    title = lesson.get("title", "")
    if title:
        parts.append(f"Lesson: {title}")

    for block in lesson.get("blocks", []):
        btype = block.get("type", "")
        data  = block.get("data", {})

        if btype in ("text", "heading"):
            text = strip_tags(data.get("html", ""))
            if text:
                parts.append(text)
        elif btype == "vocab":
            for item in data.get("items", []):
                term = item.get("term", "")
                defn = item.get("definition", "")
                if term:
                    parts.append(f"{term}: {defn}")
        elif btype == "callout":
            text = strip_tags(data.get("html", ""))
            if text:
                parts.append(text)

    return "\n\n".join(parts)


def gemini_generate(api_key: str, prompt: str, max_retries: int = 3) -> str | None:
    """Call Gemini and return the text response, with retry on 503."""
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 8192},
    }).encode("utf-8")
    url = f"{GEMINI_URL}?key={api_key}"

    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            parts = data["candidates"][0]["content"]["parts"]
            return " ".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip()
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                print(f"    503 rate limit, retrying in {wait}s...")
                time.sleep(wait)
                continue
            body = e.read().decode("utf-8", errors="replace")
            print(f"    Gemini HTTP {e.code}: {body[:200]}")
            return None
        except Exception as e:
            print(f"    Gemini error: {e}")
            return None
    return None


FLASHCARDS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Flashcards</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;padding:20px;color:#222}}
h1{{text-align:center;color:#1B2A5C;font-size:1.1rem;margin-bottom:16px}}
.deck{{max-width:600px;margin:0 auto}}
.card-wrap{{perspective:900px;margin-bottom:14px}}
.card{{position:relative;height:130px;transform-style:preserve-3d;transition:transform .45s;cursor:pointer}}
.card.flipped{{transform:rotateY(180deg)}}
.front,.back{{position:absolute;inset:0;border-radius:10px;display:flex;align-items:center;
  justify-content:center;padding:18px;text-align:center;backface-visibility:hidden;
  box-shadow:0 2px 8px rgba(0,0,0,.12)}}
.front{{background:#1B2A5C;color:#fff;font-weight:600;font-size:.95rem}}
.back{{background:#fff;color:#1B2A5C;transform:rotateY(180deg);font-size:.88rem;line-height:1.5}}
.hint{{text-align:center;color:#888;font-size:.75rem;margin-bottom:12px}}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="hint">Tap a card to flip it</p>
<div class="deck" id="deck"></div>
<script>
const cards = {cards_json};
const deck = document.getElementById('deck');
cards.forEach(c => {{
  const wrap = document.createElement('div');
  wrap.className = 'card-wrap';
  wrap.innerHTML = `<div class="card"><div class="front">${{c.term}}</div><div class="back">${{c.definition}}</div></div>`;
  wrap.querySelector('.card').addEventListener('click', e => e.currentTarget.classList.toggle('flipped'));
  deck.appendChild(wrap);
}});
</script>
</body>
</html>"""

CONCEPT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Concept Overview</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;padding:20px;color:#222;max-width:680px;margin:0 auto}}
h1{{color:#1B2A5C;font-size:1.15rem;margin-bottom:4px}}
.sub{{color:#C9A84C;font-size:.82rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px}}
.section{{background:#fff;border-radius:10px;padding:16px;margin-bottom:12px;
  box-shadow:0 2px 6px rgba(0,0,0,.08)}}
.section h2{{color:#1B2A5C;font-size:.95rem;margin-bottom:8px;padding-bottom:4px;
  border-bottom:2px solid #C9A84C}}
.section p{{font-size:.87rem;line-height:1.6;color:#333}}
.takeaway{{background:#1B2A5C;color:#fff;border-radius:10px;padding:16px;margin-top:4px}}
.takeaway h2{{color:#C9A84C;font-size:.95rem;margin-bottom:8px}}
.takeaway p{{font-size:.87rem;line-height:1.6}}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="sub">Concept Overview</div>
{sections}
</body>
</html>"""


def generate_flashcards_html(api_key: str, lesson_id: str, title: str, content: str) -> str | None:
    prompt = f"""You are writing flashcard content for Genesis K-12 Academy's middle school engineering curriculum.

Lesson: {title}
Content:
{content[:3000]}

Generate 8-12 flashcards. Each card should test one key concept, term, or idea from this lesson.
Return ONLY a JSON array, no markdown fences:
[
  {{"term": "...", "definition": "..."}},
  ...
]
Keep definitions to 1-2 sentences. Age appropriate for 6th-8th grade."""

    raw = gemini_generate(api_key, prompt)
    if not raw:
        return None

    raw = re.sub(r"^```json\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        cards = json.loads(raw)
    except Exception as e:
        print(f"    JSON parse error for flashcards: {e}")
        return None

    return FLASHCARDS_TEMPLATE.format(
        title=title,
        cards_json=json.dumps(cards, ensure_ascii=False),
    )


def generate_concept_html(api_key: str, lesson_id: str, title: str, content: str) -> str | None:
    prompt = f"""You are writing an interactive concept overview for Genesis K-12 Academy's middle school engineering curriculum.

Lesson: {title}
Content:
{content[:3000]}

Generate 3-5 thematic sections that organize the key concepts, plus a "Key Takeaway" section.
Return ONLY a JSON array, no markdown fences:
[
  {{"heading": "Section Title", "body": "2-3 sentence paragraph"}},
  ...
]
The last item should have heading "Key Takeaway".
Age appropriate for 6th-8th grade. Clear, concrete language."""

    raw = gemini_generate(api_key, prompt)
    if not raw:
        return None

    raw = re.sub(r"^```json\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        sections_data = json.loads(raw)
    except Exception as e:
        print(f"    JSON parse error for concept: {e}")
        return None

    sections_html = ""
    for sec in sections_data:
        heading = sec.get("heading", "")
        body    = sec.get("body", "")
        css_cls = "takeaway" if heading == "Key Takeaway" else "section"
        sections_html += f'<div class="{css_cls}"><h2>{heading}</h2><p>{body}</p></div>\n'

    return CONCEPT_TEMPLATE.format(title=title, sections=sections_html)


def upload_to_storage(session, lesson_id: str, content: bytes, filename: str) -> str | None:
    storage_path = f"interactives/{lesson_id}/{filename}"
    encoded = urllib.parse.quote(storage_path, safe="")
    try:
        resp = session.post(
            f"{UPLOAD_API_BASE}?uploadType=media&name={encoded}",
            data=content,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
        if resp.status_code in (200, 201):
            return f"/api/interactive/{lesson_id}/{filename}"
        print(f"    Storage upload failed {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"    Storage error: {e}")
        return None


def process_lesson(lesson_id: str, api_key: str, session, dry_run: bool) -> str:
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return "fetch_error"

    title   = lesson.get("title", lesson_id)
    blocks  = lesson.get("blocks", [])
    content = extract_text_content(lesson)

    existing_embeds = {
        b.get("data", {}).get("src", "")
        for b in blocks if b.get("type") == "embed"
    }

    print(f"\n  [{lesson_id}] {title} ({len(blocks)} blocks, {len(content)} chars)")

    if dry_run:
        print(f"    Would generate flashcards.html + concept.html")
        return "would_generate"

    # Generate HTML
    print(f"    Generating flashcards...", end=" ", flush=True)
    flashcards_html = generate_flashcards_html(api_key, lesson_id, title, content)
    print("OK" if flashcards_html else "FAILED")
    time.sleep(2)

    print(f"    Generating concept...", end=" ", flush=True)
    concept_html = generate_concept_html(api_key, lesson_id, title, content)
    print("OK" if concept_html else "FAILED")
    time.sleep(2)

    if not flashcards_html and not concept_html:
        return "generation_failed"

    # Save locally
    out_dir = INTERACTIVES_DIR / lesson_id
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    if concept_html:
        (out_dir / "concept.html").write_text(concept_html, encoding="utf-8")
        files.append(("concept.html", concept_html.encode("utf-8")))
    if flashcards_html:
        (out_dir / "flashcards.html").write_text(flashcards_html, encoding="utf-8")
        files.append(("flashcards.html", flashcards_html.encode("utf-8")))

    # Upload to storage
    new_embeds = []
    for fname, content_bytes in files:
        url = f"/api/interactive/{lesson_id}/{fname}"
        if url in existing_embeds:
            print(f"    {fname}: already embedded (refreshing storage)")
            upload_to_storage(session, lesson_id, content_bytes, fname)
            time.sleep(0.5)
            continue
        print(f"    Uploading {fname}...", end=" ", flush=True)
        uploaded = upload_to_storage(session, lesson_id, content_bytes, fname)
        if uploaded:
            label = fname.replace(".html", "").replace("-", " ").title()
            new_embeds.append({"url": url, "label": label})
            print("OK")
        else:
            print("FAILED")
        time.sleep(0.5)

    if not new_embeds:
        return "no_new_embeds"

    # Patch lesson
    new_blocks = list(blocks)
    for e in new_embeds:
        new_blocks.append({
            "id": gen_id(),
            "type": "embed",
            "data": {"src": e["url"], "height": EMBED_HEIGHT, "label": e["label"]},
            "meta": {"spacing": "md", "qcStatus": "pending"},
        })

    ok = patch_lesson(lesson_id, new_blocks)
    if ok:
        print(f"    Patched: added {len(new_embeds)} embed block(s)")
        return "done"
    return "patch_error"


def main():
    parser = argparse.ArgumentParser(description="Generate interactives from platform lesson content")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--save",      action="store_true")
    parser.add_argument("--lesson-id", help="Single lesson ID")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run (pass --save to apply)")
    dry_run = not args.save

    env     = load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found in .env")
        sys.exit(1)

    lessons = [args.lesson_id] if args.lesson_id else TARGET_LESSONS

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\nQC Generate Platform Interactives [{mode}]: {len(lessons)} lesson(s)")
    print("=" * 60)

    session = None
    if not dry_run:
        print("Authenticating with Google...")
        from _gws_auth import get_session
        session = get_session()

    log    = {}
    counts = {"done": 0, "would_generate": 0, "generation_failed": 0, "fetch_error": 0, "error": 0}

    for lid in lessons:
        status = process_lesson(lid, api_key, session, dry_run)
        key = status if status in counts else "error"
        counts[key] += 1
        time.sleep(1)

    if not dry_run and log:
        LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"Done: {counts}")
    if dry_run:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
