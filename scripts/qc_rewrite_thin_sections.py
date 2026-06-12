"""
qc_rewrite_thin_sections.py

Gemini-powered content enrichment for lessons that passed structural fixing
but still have thin/placeholder text blocks.

Targets:
  - All lessons currently marked BROKEN or DEGRADED in lesson_quality_audit.json
    (excluding pure thin stubs with ≤3 blocks — those need human drafts)

For each lesson:
  1. Fetch current blocks from the platform API
  2. Identify thin text blocks (short length or placeholder content)
  3. Send all text blocks + lesson metadata to Gemini 2.5 Flash
  4. Gemini returns enriched HTML for each thin block (identified by block ID)
  5. Merge enriched blocks back into the full block list
  6. PATCH the lesson via API

Non-text blocks (vocab, image, embed, callout, divider, tabs) are never touched.

Run:
  python scripts/qc_rewrite_thin_sections.py --dry-run              # preview which blocks are thin
  python scripts/qc_rewrite_thin_sections.py --save                 # apply enrichment
  python scripts/qc_rewrite_thin_sections.py --lesson C-040 --save  # single lesson
  python scripts/qc_rewrite_thin_sections.py --lesson C-040 --dry-run
"""

import argparse, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
API_KEY       = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
AUDIT_PATH    = Path(__file__).parent / "lesson_quality_audit.json"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"

GEMINI_MODEL  = "gemini-2.5-flash"
GEMINI_URL    = (
    f"https://generativelanguage.googleapis.com/v1beta"
    f"/models/{GEMINI_MODEL}:generateContent"
)

STRIP_RE = re.compile(r"<[^>]+>")

PLACEHOLDER_RE = re.compile(
    r"Plain\s*:?\s*language explanation"
    r"|Plain\s*language\s*explanation"
    r"|Engineering analogy"
    r"|Faith or stewardship connection"
    r"|Multiscale Modeling connection"
    r"|OCV application"
    r"|Term\s*:\s*Definition"
    r"|\[IMAGE NEEDED",
    re.IGNORECASE,
)


def strip_tags(html: str) -> str:
    return STRIP_RE.sub("", html or "").strip()


def is_thin(html: str) -> bool:
    text = strip_tags(html)
    if len(text) < 160:
        return True
    if PLACEHOLDER_RE.search(text):
        return True
    return False


# ── API helpers ───────────────────────────────────────────────────────────────

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
                        env[k.strip()] = v.strip().strip("\"'")
    return env


def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  fetch error: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list) -> bool:
    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


def get_lesson_meta(lesson_id: str) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return next((l for l in manifest["lessons"] if l["id"] == lesson_id), {})


# ── Gemini enrichment ─────────────────────────────────────────────────────────

ENRICH_SYSTEM = """\
You are enriching a Genesis K-12 Academy middle school engineering lesson (grades 6–8).
Students are in homeschool settings. Lessons are faith-integrated but content-first.

You will receive the current lesson text blocks as HTML. Some blocks are thin (short or
contain unfilled template labels). Your job:
  1. Leave FULL blocks (>160 chars of real content) UNCHANGED — return the same HTML.
  2. Rewrite THIN blocks so each section has 2-4 complete paragraphs of substantive content.
  3. Remove any template placeholder text ("Plain: language explanation", etc.) and replace
     with real engineering explanation appropriate for the lesson topic.
  4. Keep all headings (h2, h3) exactly as they are — only change paragraph/list content.
  5. Use concrete analogies, engineering examples, and cause-and-effect language.
  6. Faith references are welcome where natural, but never forced.
  7. No markdown — pure HTML only (<p>, <ul>, <li>, <strong>, <em>).
  8. Return a JSON object: { "blocks": [ { "id": "...", "html": "..." }, ... ] }
     — one entry per input block. IDs must match exactly.
     Return ONLY the JSON, no explanation, no markdown fencing.\
"""

def call_gemini(api_key: str, lesson_title: str, topic: str, course: str,
                text_blocks: list[dict]) -> dict | None:
    """
    text_blocks: list of {id, html} dicts (text-type blocks only)
    Returns {id: html} map of enriched blocks, or None on failure.
    """
    blocks_json = json.dumps(
        [{"id": b["id"], "html": b["html"]} for b in text_blocks],
        ensure_ascii=False,
    )

    user_prompt = (
        f"LESSON TITLE: {lesson_title}\n"
        f"TOPIC: {topic}\n"
        f"COURSE: {course}\n\n"
        f"TEXT BLOCKS (JSON):\n{blocks_json}\n\n"
        "Enrich the thin blocks and return the full JSON array as described."
    )

    payload = json.dumps({
        "system_instruction": {"parts": [{"text": ENRICH_SYSTEM}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 16384,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode("utf-8")

    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        parts = data["candidates"][0]["content"]["parts"]
        raw = " ".join(p["text"] for p in parts if "text" in p and not p.get("thought")).strip()
        # Strip markdown fencing if Gemini added it despite instructions
        raw = re.sub(r"^```[a-z]*\s*", "", raw, flags=re.IGNORECASE).rstrip("`").strip()
        result = json.loads(raw)
        # result should be {"blocks": [...]} or just [...]
        if isinstance(result, dict) and "blocks" in result:
            items = result["blocks"]
        elif isinstance(result, list):
            items = result
        else:
            print("  Unexpected Gemini response shape")
            return None
        return {item["id"]: item["html"] for item in items if "id" in item and "html" in item}
    except json.JSONDecodeError as e:
        print(f"  Gemini JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"  Gemini error: {e}")
        return None


# ── Per-lesson processing ─────────────────────────────────────────────────────

def process_lesson(lesson_id: str, api_key: str, dry_run: bool) -> str:
    """Returns one of: 'enriched', 'clean', 'fetch_error', 'gemini_error', 'patch_error'"""
    data = fetch_lesson(lesson_id)
    if not data:
        return "fetch_error"

    blocks = data.get("blocks", [])
    meta = get_lesson_meta(lesson_id)
    title = data.get("title", lesson_id)
    topic = meta.get("topic", title)
    course = "Creationeering Middle School" if lesson_id.startswith("C-") else "Mousetrap Build Middle School"

    text_blocks = [b for b in blocks if b.get("type") == "text"]
    thin_blocks = [b for b in text_blocks if is_thin(b.get("data", {}).get("html", ""))]

    if not thin_blocks:
        print(f"  clean (no thin text blocks found)")
        return "clean"

    thin_ids = {b["id"] for b in thin_blocks}
    print(f"  {len(thin_blocks)}/{len(text_blocks)} text blocks are thin")

    if dry_run:
        for b in thin_blocks:
            text = strip_tags(b.get("data", {}).get("html", ""))[:80]
            print(f"    [thin] {repr(text)}")
        return "enriched"

    # Call Gemini with ALL text blocks (gives full context for coherent enrichment)
    text_block_data = [
        {"id": b["id"], "html": b.get("data", {}).get("html", "")}
        for b in text_blocks
    ]
    enriched_map = call_gemini(api_key, title, topic, course, text_block_data)
    if not enriched_map:
        return "gemini_error"

    # Merge: replace only thin block HTML with enriched versions
    new_blocks = []
    changes = 0
    for b in blocks:
        if b.get("type") == "text" and b["id"] in thin_ids and b["id"] in enriched_map:
            enriched_html = enriched_map[b["id"]]
            if enriched_html and enriched_html != b.get("data", {}).get("html", ""):
                new_block = {**b, "data": {**b.get("data", {}), "html": enriched_html}}
                new_blocks.append(new_block)
                changes += 1
                continue
        new_blocks.append(b)

    if changes == 0:
        print(f"  Gemini returned no changes")
        return "clean"

    print(f"  Enriched {changes} block(s)")
    ok = patch_lesson(lesson_id, new_blocks)
    return "enriched" if ok else "patch_error"


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no Gemini calls")
    parser.add_argument("--save",    action="store_true", help="Apply enrichment via Gemini")
    parser.add_argument("--lesson",  help="Single lesson ID (e.g. C-040)")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    env = load_env()
    gemini_key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    if not gemini_key and args.save:
        print("GEMINI_API_KEY not found in .env"); sys.exit(1)

    # Build target list
    if args.lesson:
        lesson_ids = [args.lesson]
    elif AUDIT_PATH.exists():
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        # Include broken + degraded that have real block content (>3 blocks)
        targets = (
            [r for r in audit.get("broken", []) if r["blockCount"] > 3]
            + [r for r in audit.get("degraded", []) if r["blockCount"] > 3]
        )
        lesson_ids = [r["id"] for r in targets]
    else:
        print("No audit file found. Use --lesson."); sys.exit(1)

    total = len(lesson_ids)
    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"{mode} — enriching {total} lessons\n")

    results = {"enriched": 0, "clean": 0, "fetch_error": 0, "gemini_error": 0, "patch_error": 0}

    for idx, lid in enumerate(lesson_ids, 1):
        print(f"[{idx}/{total}] {lid}")
        status = process_lesson(lid, gemini_key or "", args.dry_run)
        results[status] = results.get(status, 0) + 1
        if not args.dry_run and status not in ("fetch_error",):
            time.sleep(1.0)  # Gemini rate limit buffer

    print(f"\n{'='*60}")
    print(f"Results: {results}")
    if args.dry_run:
        print("Run with --save to apply enrichment.")


if __name__ == "__main__":
    main()
