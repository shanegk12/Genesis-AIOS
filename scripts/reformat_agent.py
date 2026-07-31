"""
Genesis K-12 Reformat Agent

Reads imported lessons flagged as 'needs_reformat' in qc_reports.json,
fetches their raw markdown-as-text content from the platform, rewrites it
into clean TipTap-compatible HTML using proper widget structure, then PATCHes
the lesson back.

Uses Gemini 2.5 Pro for the rewrite. Widget schemas are injected so Gemini
produces markup that round-trips cleanly through the TipTap editor.

Usage:
  python scripts/reformat_agent.py                     # reformat all flagged lessons
  python scripts/reformat_agent.py --lesson-id C-001   # one lesson
  python scripts/reformat_agent.py --dry-run           # preview, don't PATCH
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone
from widget_schemas import WIDGET_REFERENCE

REPORTS_PATH  = os.path.join(os.path.dirname(__file__), "qc_reports.json")
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")

LIVE_URL = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
def _get_platform_key() -> str:
    """Load platform API key from env or .env - never hardcode in source."""
    import os as _os
    from pathlib import Path as _Path
    k = (_os.environ.get('PIPELINE_KEY')
         or _os.environ.get('PLATFORM_KEY')
         or _os.environ.get('ADMIN_API_KEY', ''))
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=', 'ADMIN_API_KEY=')):
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


API_KEY  = _get_platform_key()

GEMINI_MODEL = "gemini-2.5-pro"
GEMINI_URL   = (f"https://generativelanguage.googleapis.com/v1beta"
                f"/models/{GEMINI_MODEL}:generateContent")

REFORMAT_PROMPT = """You are a curriculum formatter for Genesis K-12 Academy's middle school engineering course.

You will receive lesson content that was imported as raw text (markdown syntax is visible as literal characters like ##, **, *). Your job is to reformat it into clean, structured HTML that works with our TipTap-based lesson editor.

{widget_reference}

## Formatting rules

1. Convert ## headings to <h2>, ### to <h3>, #### to <h4>
2. Convert **bold** to <strong>, *italic* to <em>
3. Convert bullet lists (* item) to <ul><li>...</li></ul>
4. Convert numbered lists to <ol><li>...</li></ul>
5. Wrap loose paragraphs in <p> tags
6. These sections should NEVER contain widgets — keep as plain text:
   - Lesson Overview, Learning Objectives, Key Vocabulary, Works Cited,
     Summary of Key Concepts, Engineering Journal, Technical Documentation
7. For all OTHER content sections: use widgets intelligently:
   - If a section lists 2-4 sub-topics with equal depth → use Tabs
   - If a section has "deep dive" or optional content → use Accordion
   - If a section has a term+definition pair → use Columns (2-col)
   - If a section has a formula/equation on one side and explanation on other → use Columns (left-heavy)
   - Add a Callout (tip/info/success/biblical) in any section that has >3 paragraphs of plain text
   - Add [IMAGE NEEDED: description] placeholders where visuals would help — at minimum one per non-exempt H2 section
   - Use "biblical" callout variant for any scripture or faith content

8. Key Vocabulary: convert term+definition pairs to 2-column grid using Columns widget
9. Preserve ALL content — do not summarize or cut anything
10. Return ONLY the HTML — no markdown, no explanation, no preamble

## Lesson content to reformat:

Title: {title}
Course: {course}

{content}"""


# ── Env ───────────────────────────────────────────────────────────────────────

def _load_env() -> dict:
    env = {}
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


# ── Gemini ────────────────────────────────────────────────────────────────────

def _gemini_reformat(api_key: str, title: str, course: str, content: str) -> str:
    prompt = REFORMAT_PROMPT.format(
        widget_reference=WIDGET_REFERENCE,
        title=title,
        course=course,
        content=content[:20000],
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":    0.3,
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingBudget": 2048},
        },
    }).encode("utf-8")

    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())

    parts = data["candidates"][0]["content"].get("parts", [])
    text  = "\n".join(
        p["text"] for p in parts
        if not p.get("thought", False) and "text" in p
    ).strip()

    # Strip any accidental markdown fences
    text = re.sub(r'^```html?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text


# ── Platform API ──────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str) -> dict | None:
    url = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  Fetch error {lesson_id}: {e}")
        return None


def patch_lesson(lesson_id: str, content: str, dry_run: bool) -> bool:
    if dry_run:
        preview = content[:400].replace('\n', ' ')
        print(f"  [DRY RUN] would parse-html {lesson_id} ({len(content)} chars):\n    {preview}...")
        return True
    # Use parse-html action so blocks + content are updated atomically
    url     = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    payload = json.dumps({"action": "parse-html", "html": content}).encode("utf-8")
    req     = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            block_count = result.get("blockCount", "?")
            print(f"    Saved: {block_count} blocks")
            return result.get("ok", False)
    except Exception as e:
        print(f"  parse-html error {lesson_id}: {e}")
        return False


# ── Report I/O ────────────────────────────────────────────────────────────────

def load_reports() -> dict:
    if not os.path.exists(REPORTS_PATH):
        print("qc_reports.json not found — run format_qc_agent.py first")
        sys.exit(1)
    with open(REPORTS_PATH, encoding='utf-8') as f:
        return json.load(f)


def save_reports(data: dict):
    with open(REPORTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _get_course(lesson_id: str) -> str:
    try:
        with open(MANIFEST_PATH, encoding='utf-8') as f:
            manifest = json.load(f)
        for l in manifest['lessons']:
            if l['id'] == lesson_id:
                return 'Creationeering' if l['id'].startswith('C-') else 'Mousetrap Build'
    except Exception:
        pass
    return 'Creationeering' if lesson_id.startswith('C-') else 'Mousetrap Build'


# ── Notification ──────────────────────────────────────────────────────────────

def send_summary(reformatted: list, failed: list):
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from notify import send_email
        body = f"""
<p><strong>Reformat Agent complete.</strong></p>
<p>Reformatted: {len(reformatted)} &nbsp;|&nbsp; Failed: {len(failed)}</p>
<p>Run <code>format_qc_agent.py</code> next to check formatting on reformatted lessons.</p>
{'<p>Failed (manual review): ' + ', '.join(failed) + '</p>' if failed else ''}
"""
        send_email(
            f"GK12 Reformat — {len(reformatted)} lessons reformatted",
            body,
        )
    except Exception as e:
        print(f"Notify failed: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Reformat Agent")
    parser.add_argument('--lesson-id', help='Reformat a single lesson ID')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview output, do not PATCH')
    parser.add_argument('--no-notify', action='store_true')
    args = parser.parse_args()

    env     = _load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        sys.exit(1)

    reports = load_reports()
    all_reports = reports.get('reports', {})

    to_reformat = {
        lid: r for lid, r in all_reports.items()
        if r.get('status') == 'needs_reformat'
        and (args.lesson_id is None or lid == args.lesson_id)
    }

    if not to_reformat:
        print("No lessons flagged as needs_reformat.")
        print("Run format_qc_agent.py first, or check qc_reports.json.")
        return

    print(f"Reformat Agent: {len(to_reformat)} lessons"
          + (" [DRY RUN]" if args.dry_run else "") + "...")

    reformatted, failed = [], []

    for lesson_id, report in to_reformat.items():
        title  = report.get('title', lesson_id)
        course = _get_course(lesson_id)
        print(f"\n  [{lesson_id}] {title}")

        lesson = fetch_lesson(lesson_id)
        if not lesson:
            print(f"    Not found on platform")
            failed.append(lesson_id)
            continue

        content = lesson.get('content', '')
        if not content:
            print(f"    No content to reformat")
            failed.append(lesson_id)
            continue

        try:
            print(f"    Calling Gemini ({len(content)} chars in)...")
            new_html = _gemini_reformat(api_key, title, course, content)
            print(f"    Gemini returned {len(new_html)} chars")

            ok = patch_lesson(lesson_id, new_html, args.dry_run)
            if ok:
                reformatted.append(lesson_id)
                if not args.dry_run:
                    report['status']       = 'reformatted'
                    report['reformattedAt'] = datetime.now(timezone.utc).isoformat()
                    # Clear old needs_reformat issue so QC re-checks fresh
                    report['issues'] = []
            else:
                failed.append(lesson_id)

        except Exception as e:
            print(f"    Error: {e}")
            failed.append(lesson_id)

        time.sleep(2)  # rate limiting between Gemini calls

    if not args.dry_run:
        save_reports(reports)

    print(f"\nDone. Reformatted: {reformatted or 'none'}. Failed: {failed or 'none'}.")
    print("Next step: run format_qc_agent.py to validate reformatted lessons.")

    if not args.no_notify and not args.dry_run:
        send_summary(reformatted, failed)


if __name__ == '__main__':
    main()
