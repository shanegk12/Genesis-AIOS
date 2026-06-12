"""
Genesis K-12 QC — Enrich Underdeveloped Lessons

Targets lessons that are critically thin (≤5 blocks or all-text) and enriches them:
  1. Reads lesson source from Google Docs via rerun_qc.read_tab_content()
  2. Runs interactive_agent to generate HTML interactives (flashcards, accordion, OCV, concept)
  3. Uploads generated HTML to Firebase Storage via the ADC-authenticated session
  4. Patches lesson with embed blocks pointing to the uploaded interactives

Additionally enriches text-wall lessons (all text, many blocks) by:
  - Adding a Gemini-generated callout block after every 4th text block
  - Breaking up large text blocks (>800 chars) into shorter ones

Usage:
  python scripts/qc_enrich_lessons.py --dry-run           # preview only
  python scripts/qc_enrich_lessons.py --save              # live run
  python scripts/qc_enrich_lessons.py --lesson-id C-023   # single lesson
  python scripts/qc_enrich_lessons.py --thin-only         # only thin lessons
  python scripts/qc_enrich_lessons.py --text-walls-only   # only text-wall lessons
"""

import argparse, json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

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
INTERACTIVES_DIR = Path(__file__).parent / "interactives"
LOG_PATH = Path(__file__).parent / "enrich_log.json"

STORAGE_BUCKET = "genesis-modularity.firebasestorage.app"
UPLOAD_API_BASE = f"https://storage.googleapis.com/upload/storage/v1/b/{STORAGE_BUCKET}/o"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Lessons by category
THIN_LESSONS = [
    "C-011",  # 0 blocks
    "C-023",  # 1 block
    "M-013",  # 1 block
    "C-024",  # 2 blocks
    "M-009",  # 5 blocks
    "M-061",  # 5 blocks
]

TEXT_WALL_LESSONS = [
    "M-010",  # 11 text-only
    "C-035",  # 30 text-only
    "C-054",  # 34 text-only
]

EMBED_HEIGHT = 520


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


def load_manifest() -> list[dict]:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("lessons", [])


def get_lesson_meta(lesson_id: str) -> dict:
    manifest = load_manifest()
    return next((l for l in manifest if l["id"] == lesson_id), {})


# ── Interactive generation ─────────────────────────────────────────────────────

def run_interactive_agent(lesson_id: str, api_key: str | None) -> Path | None:
    """Run interactive_agent.py for a lesson. Returns the interactives dir or None."""
    out_dir = INTERACTIVES_DIR / lesson_id
    out_dir.mkdir(parents=True, exist_ok=True)

    script = Path(__file__).parent / "interactive_agent.py"
    cmd = [sys.executable, str(script), "--lesson-id", lesson_id]
    if not api_key:
        cmd.append("--skip-concept")

    env = os.environ.copy()
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    print(f"    Running interactive_agent for {lesson_id}...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            cwd=str(Path(__file__).parent.parent),
        )
        print(f"    {result.stdout[-500:] if result.stdout else '(no output)'}")
        if result.stderr:
            print(f"    STDERR: {result.stderr[-300:]}")
        if result.returncode not in (0, 1):
            print(f"    Agent returned code {result.returncode}")
            return None
    except subprocess.TimeoutExpired:
        print(f"    Timeout running interactive_agent")
        return None
    except Exception as e:
        print(f"    Error running interactive_agent: {e}")
        return None

    # Check which files were created
    files = list(out_dir.glob("*.html"))
    if files:
        print(f"    Generated: {[f.name for f in files]}")
        return out_dir
    print(f"    No HTML files generated")
    return None


def upload_interactive_to_storage(session, lesson_id: str, local_path: Path, filename: str) -> str | None:
    """Upload an HTML file to Firebase Storage at interactives/{lessonId}/{filename}."""
    storage_path = f"interactives/{lesson_id}/{filename}"
    content = local_path.read_bytes()
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
        print(f"    Storage upload error: {e}")
        return None


def add_embed_blocks(lesson_id: str, lesson: dict, embed_urls: list[tuple[str, str]], dry_run: bool) -> bool:
    """
    Append embed blocks (one per URL) to the lesson's block list.
    embed_urls: list of (url, label) pairs
    """
    blocks = list(lesson.get("blocks", []))

    # Remove any existing embed blocks for this lesson (to avoid duplicates on re-run)
    existing_embed_urls = {
        b.get("data", {}).get("src", "") for b in blocks if b.get("type") == "embed"
    }

    new_blocks = []
    for url, label in embed_urls:
        if url in existing_embed_urls:
            print(f"    Embed already exists: {url}")
            continue
        new_blocks.append({
            "id": gen_id(),
            "type": "embed",
            "data": {
                "src": url,
                "height": EMBED_HEIGHT,
                "label": label,
            },
            "meta": {"spacing": "md", "qcStatus": "pending"},
        })

    if not new_blocks:
        print(f"    No new embed blocks to add")
        return True

    blocks.extend(new_blocks)
    print(f"    Adding {len(new_blocks)} embed block(s)")

    if dry_run:
        return True

    return patch_lesson(lesson_id, blocks)


def process_thin_lesson(lesson_id: str, session, api_key: str | None, dry_run: bool, log: dict) -> str:
    """Generate interactives for a thin lesson, upload, and embed."""
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return "fetch_error"

    title = lesson.get("title", lesson_id)
    print(f"\n  [{lesson_id}] {title}")
    print(f"    Current blocks: {len(lesson.get('blocks', []))}")

    # Generate interactives
    if dry_run:
        print(f"    (dry-run) Would run interactive_agent + upload + embed")
        return "would_enrich"

    out_dir = run_interactive_agent(lesson_id, api_key)
    if not out_dir:
        return "interactive_failed"

    # Prefer concept.html, then flashcards.html, then accordion.html
    preferred_order = ["concept.html", "flashcards.html", "accordion.html", "ocv.html"]
    html_files = list(out_dir.glob("*.html"))
    html_map   = {f.name: f for f in html_files}

    embed_urls = []
    for fname in preferred_order:
        if fname in html_map:
            print(f"    Uploading {fname}...")
            url = upload_interactive_to_storage(session, lesson_id, html_map[fname], fname)
            if url:
                label = fname.replace(".html", "").replace("-", " ").title()
                embed_urls.append((url, label))
                print(f"    Uploaded: {url}")
            time.sleep(0.5)

    if not embed_urls:
        return "upload_failed"

    ok = add_embed_blocks(lesson_id, lesson, embed_urls, dry_run=False)
    status = "enriched" if ok else "patch_error"
    if ok:
        log[lesson_id] = {
            "status": "enriched",
            "type": "thin",
            "embeds": len(embed_urls),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    return status


# ── Text-wall enrichment ───────────────────────────────────────────────────────

def gemini_batch_callouts(api_key: str, lesson_title: str, sections: list[str], max_retries: int = 4) -> list[dict]:
    """Generate all callouts for a lesson in one API call. Returns list of callout dicts."""
    numbered = "\n\n".join(
        f"[{i+1}] {s[:400]}" for i, s in enumerate(sections)
    )
    prompt = f"""You write curriculum callouts for Genesis K-12 Academy's middle school engineering course (6th-8th grade).

Lesson: {lesson_title}

Below are {len(sections)} text sections that each need ONE short callout to break up the reading.
For each section, choose callout_type: "tip", "info", "success", or "biblical"
Content should reinforce or extend — not repeat — the section text. 1-2 sentences max.

Sections:
{numbered}

Return a JSON array with exactly {len(sections)} objects (one per section), in order:
[
  {{"callout_type": "tip", "html": "<p>...</p>"}},
  ...
]
Return ONLY the JSON array. No markdown fences. No explanation."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode("utf-8")
    url = f"{GEMINI_URL}?key={api_key}"

    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            parts = data["candidates"][0]["content"]["parts"]
            text  = " ".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip()
            text  = re.sub(r"^```json\s*", "", text.strip())
            text  = re.sub(r"\s*```$", "", text.strip())
            results = json.loads(text)
            callouts = []
            for r in results:
                callouts.append({
                    "id": gen_id(),
                    "type": "callout",
                    "data": {
                        "calloutType": r.get("callout_type", "info"),
                        "html": r.get("html", "<p>Key point from this section.</p>"),
                    },
                    "meta": {"spacing": "md", "qcStatus": "pending"},
                })
            return callouts
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < max_retries - 1:
                wait = 10 * (2 ** attempt)  # 10s, 20s, 40s
                print(f"    503 rate limit (attempt {attempt+1}), retrying in {wait}s...")
                time.sleep(wait)
                continue
            body = e.read().decode("utf-8", errors="replace")
            print(f"    Batch callout error: HTTP {e.code}: {body[:200]}")
            return []
        except Exception as e:
            print(f"    Batch callout error: {e}")
            return []
    return []


def process_text_wall(lesson_id: str, api_key: str | None, dry_run: bool, log: dict) -> str:
    """Enrich a text-wall lesson by inserting callouts every 4 text blocks."""
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return "fetch_error"

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])
    print(f"\n  [{lesson_id}] {title} ({len(blocks)} blocks)")

    if not api_key:
        print(f"    No Gemini API key — skipping callout generation")
        return "skipped"

    # Collect callout insertion points (after every 4th consecutive text block)
    insertion_points = []  # list of (block_index_after_which_to_insert, section_text)
    consecutive_text = 0

    for i, block in enumerate(blocks):
        if block.get("type") == "text":
            consecutive_text += 1
            if consecutive_text % 4 == 0:
                html = block.get("data", {}).get("html", "")
                text_content = re.sub(r"<[^>]+>", " ", html).strip()
                if text_content:
                    insertion_points.append((i, text_content))
        else:
            consecutive_text = 0

    if not insertion_points:
        print(f"    No long text runs found (need ≥4 consecutive text blocks)")
        return "clean"

    print(f"    Found {len(insertion_points)} callout position(s)")

    if dry_run:
        print(f"    Would generate {len(insertion_points)} callout(s) in one batch call")
        return "would_enrich"

    # Generate all callouts in a single API call
    sections = [text for _, text in insertion_points]
    callouts = gemini_batch_callouts(api_key, title, sections)

    if not callouts:
        print(f"    Callout generation failed")
        return "error"

    # Pair up callouts with insertion points
    pairs = list(zip(insertion_points, callouts))

    # Rebuild block list inserting callouts after the correct positions
    # Process in reverse so indices stay valid
    new_blocks = list(blocks)
    for (insert_after_idx, _), callout in reversed(pairs):
        new_blocks.insert(insert_after_idx + 1, callout)

    print(f"    Added {len(pairs)} callout(s)")
    ok = patch_lesson(lesson_id, new_blocks)
    status = "enriched" if ok else "patch_error"
    if ok:
        log[lesson_id] = {
            "status": "enriched",
            "type": "text_wall",
            "callouts_added": len(pairs),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    return status


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich underdeveloped lessons")
    parser.add_argument("--dry-run",         action="store_true")
    parser.add_argument("--save",            action="store_true")
    parser.add_argument("--lesson-id",       help="Single lesson")
    parser.add_argument("--thin-only",       action="store_true")
    parser.add_argument("--text-walls-only", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run (pass --save to apply)")
    dry_run = not args.save

    env         = load_env()
    api_key     = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    claude_key  = os.environ.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_API_KEY")

    session = None
    if not dry_run:
        print("Authenticating with Google...")
        from _gws_auth import get_session
        session = get_session()

    if args.lesson_id:
        thin_targets  = [args.lesson_id] if args.lesson_id in THIN_LESSONS else []
        wall_targets  = [args.lesson_id] if args.lesson_id in TEXT_WALL_LESSONS else []
        if not thin_targets and not wall_targets:
            # Process as thin by default for unknown lessons
            thin_targets = [args.lesson_id]
    else:
        thin_targets = THIN_LESSONS  if not args.text_walls_only else []
        wall_targets = TEXT_WALL_LESSONS if not args.thin_only      else []

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\nQC Enrich Lessons [{mode}]")
    print(f"  Thin lessons:      {thin_targets}")
    print(f"  Text-wall lessons: {wall_targets}")
    print("=" * 60)

    log    = {}
    counts = {"enriched": 0, "would_enrich": 0, "skipped": 0, "error": 0}

    # Process thin lessons (interactives)
    for lid in thin_targets:
        status = process_thin_lesson(lid, session, claude_key, dry_run, log)
        key    = status if status in counts else "error"
        counts[key] += 1
        time.sleep(1)

    # Process text walls (callouts)
    for lid in wall_targets:
        status = process_text_wall(lid, api_key, dry_run, log)
        key    = status if status in counts else "error"
        counts[key] += 1
        time.sleep(1)

    if not dry_run and log:
        if LOG_PATH.exists():
            try:
                existing = json.loads(LOG_PATH.read_text(encoding="utf-8"))
                existing.update(log)
                log = existing
            except Exception:
                pass
        LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"Done: {counts}")
    if dry_run:
        print("Run with --save to apply.")


if __name__ == "__main__":
    main()
