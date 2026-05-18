"""
Genesis K-12 Dev Fix Agent

Reads qc_reports.json for lessons flagged as 'needs_fix', fetches each lesson
from the platform API, makes targeted content fixes, then PATCHes back.

Fix strategy:
  accordion-image / tab-image  → programmatic: insert [IMAGE NEEDED: ...] placeholder
  section-image / word-wall    → Gemini: generate a contextual callout to break up text
  placeholder-content          → Gemini: write real content for empty widgets

Usage:
  python scripts/dev_fix_agent.py                     # fix all needs_fix lessons
  python scripts/dev_fix_agent.py --lesson-id C-001   # fix one lesson
  python scripts/dev_fix_agent.py --dry-run           # preview fixes, don't PATCH
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

REPORTS_PATH = os.path.join(os.path.dirname(__file__), "qc_reports.json")

LIVE_URL = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
API_KEY  = "gk12-pipeline-2026"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = (f"https://generativelanguage.googleapis.com/v1beta"
                f"/models/{GEMINI_MODEL}:generateContent")


# ── Env ───────────────────────────────────────────────────────────────────────

def _load_env() -> dict:
    env = {}
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


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
        print(f"  [DRY RUN] would PATCH {lesson_id} ({len(content)} chars)")
        return True
    url     = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    payload = json.dumps({"content": content}).encode("utf-8")
    req     = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return result.get("ok", False)
    except Exception as e:
        print(f"  PATCH error {lesson_id}: {e}")
        return False


# ── Gemini ────────────────────────────────────────────────────────────────────

def _gemini(api_key: str, prompt: str) -> str:
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
    }).encode("utf-8")
    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p["text"] for p in parts if "text" in p).strip()


def gemini_callout(api_key: str, lesson_title: str, section_heading: str,
                   section_text: str) -> str:
    """Generate a short callout HTML block to break up a word wall."""
    prompt = f"""You write curriculum for Genesis K-12 Academy's middle school engineering course.

Lesson: {lesson_title}
Section: {section_heading}

Section text (first 600 chars):
{section_text[:600]}

Write ONE short callout block to break up this text. Choose the most appropriate type:
- Tip (practical advice)
- Note (important clarification)
- Key Point (core concept summary)
- Biblical Connection (faith tie-in, only if natural)

Return ONLY a raw HTML snippet — no markdown, no explanation. Use this exact format:
<div data-callout="TYPE" class="callout-block callout-TYPE">
  <p>2-3 concise sentences relevant to this section. Written for 6th-8th grade.</p>
</div>

TYPE must be one of: tip, info, success, biblical"""

    try:
        result = _gemini(api_key, prompt)
        # Validate it returned a callout div
        if 'data-callout' in result:
            return result
        return ''
    except Exception as e:
        print(f"    Gemini callout error: {e}")
        return ''


def gemini_widget_content(api_key: str, lesson_title: str, widget_label: str,
                          widget_type: str) -> str:
    """Generate real content for an empty accordion or tab."""
    prompt = f"""You write curriculum for Genesis K-12 Academy's middle school engineering course.

Lesson: {lesson_title}
{widget_type.capitalize()} title: {widget_label}

This {widget_type} contains only placeholder text. Write 2-3 paragraphs of real curriculum content
appropriate for 6th-8th grade. Keep sentences short and concrete. No jargon without explanation.

Return ONLY raw HTML paragraphs — no markdown, no preamble:
<p>...</p>
<p>...</p>"""

    try:
        result = _gemini(api_key, prompt)
        if '<p>' in result:
            return result
        return ''
    except Exception as e:
        print(f"    Gemini content error: {e}")
        return ''


# ── Programmatic fixes ────────────────────────────────────────────────────────

def _image_placeholder(context_label: str) -> str:
    """Generate a [IMAGE NEEDED] placeholder paragraph."""
    return (f'<p><em>[IMAGE NEEDED: Photo or diagram illustrating'
            f' {context_label.lower()}]</em></p>')


def fix_accordion_image(html: str, acc_title: str) -> str:
    """Insert image placeholder before the closing accordion body div."""
    # Match the accordion with this title
    pattern = (
        r'(<details[^>]*data-accordion[^>]*>.*?'
        r'<summary[^>]*>' + re.escape(acc_title) + r'</summary>'
        r'.*?<div class="accordion-body">)(.*?)(</div>\s*</details>)'
    )
    def replacer(m):
        body = m.group(2)
        # Only add if not already has [IMAGE NEEDED]
        if '[IMAGE NEEDED' in body:
            return m.group(0)
        placeholder = _image_placeholder(acc_title)
        return m.group(1) + body + placeholder + m.group(3)

    return re.sub(pattern, replacer, html, flags=re.DOTALL)


def fix_tab_image(html: str, tab_label: str) -> str:
    """Insert image placeholder before the closing tab panel div."""
    pattern = (
        r'(<div[^>]*data-tab-panel="' + re.escape(tab_label) + r'"[^>]*>)'
        r'(.*?)(</div>)'
    )
    def replacer(m):
        body = m.group(2)
        if '[IMAGE NEEDED' in body:
            return m.group(0)
        placeholder = _image_placeholder(tab_label)
        return m.group(1) + body + placeholder + m.group(3)

    # Only replace the first match (tab panels may repeat label in TOC)
    return re.sub(pattern, replacer, html, count=1, flags=re.DOTALL)


def fix_placeholder_content(html: str, widget_label: str, widget_type: str,
                             api_key: str, lesson_title: str) -> str:
    """Replace 'Content goes here…' in a widget with real Gemini-generated content."""
    new_content = gemini_widget_content(api_key, lesson_title, widget_label, widget_type)
    if not new_content:
        return html
    return html.replace(
        'Content goes here…',
        new_content,
        1  # replace first occurrence only
    )


def fix_word_wall(html: str, section_heading: str, api_key: str,
                  lesson_title: str) -> str:
    """Insert a Gemini-generated callout after the last paragraph in a word-wall section."""
    # Extract section text for context
    section_match = re.search(
        r'<h[23][^>]*>' + re.escape(section_heading) + r'</h[23]>(.*?)(?=<h[23]|$)',
        html, re.DOTALL
    )
    if not section_match:
        return html

    section_html = section_match.group(1)
    section_text = re.sub(r'<[^>]+>', '', section_html)

    callout_html = gemini_callout(api_key, lesson_title, section_heading, section_text)
    if not callout_html:
        # Fallback: add a simple image placeholder
        callout_html = _image_placeholder(section_heading)

    # Insert after the 3rd paragraph in the section
    paras = list(re.finditer(r'</p>', section_html))
    if len(paras) >= 3:
        insert_after = section_match.start(1) + paras[2].end()
        return html[:insert_after] + '\n' + callout_html + html[insert_after:]

    return html


# ── Main fix loop ─────────────────────────────────────────────────────────────

RULE_ORDER = ['placeholder-content', 'word-wall', 'accordion-image',
              'tab-image', 'section-image']


def fix_lesson(lesson_id: str, report: dict, api_key: str, dry_run: bool) -> bool:
    """Apply all fixes for one lesson. Returns True if successfully patched."""
    print(f"\n  Fixing [{lesson_id}] {report.get('title', '')}...")
    issues = report.get('issues', [])
    if not issues:
        return True

    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return False

    html         = lesson.get('content', '')
    lesson_title = lesson.get('title', lesson_id)
    if not html:
        print(f"    No content to fix")
        return False

    original_html = html
    applied = []

    # Sort issues by rule priority
    sorted_issues = sorted(issues, key=lambda i: RULE_ORDER.index(i['rule'])
                           if i['rule'] in RULE_ORDER else 99)

    for issue in sorted_issues:
        rule     = issue['rule']
        location = issue.get('location', '')

        if rule == 'accordion-image':
            # Extract accordion title from "Accordion: Title"
            acc_title = location.replace('Accordion: ', '').strip()
            html = fix_accordion_image(html, acc_title)
            applied.append(f"accordion-image: {acc_title}")

        elif rule == 'tab-image':
            tab_label = location.replace('Tab: ', '').strip()
            html = fix_tab_image(html, tab_label)
            applied.append(f"tab-image: {tab_label}")

        elif rule == 'placeholder-content':
            # Determine widget type from location
            wtype = 'accordion' if 'Accordion' in location else 'tab'
            label = re.sub(r'^(Accordion|Tab):\s*', '', location).strip()
            html  = fix_placeholder_content(html, label, wtype, api_key, lesson_title)
            applied.append(f"placeholder-content: {label}")

        elif rule in ('word-wall', 'section-image'):
            section = location.replace('Section: ', '').strip()
            html = fix_word_wall(html, section, api_key, lesson_title)
            applied.append(f"{rule}: {section}")

    if html == original_html:
        print(f"    No changes produced (patterns may not match — manual review needed)")
        return False

    print(f"    Applied: {', '.join(applied)}")

    success = patch_lesson(lesson_id, html, dry_run)
    if success:
        print(f"    Patched OK")
    else:
        print(f"    PATCH failed")
    return success


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


# ── Notification ──────────────────────────────────────────────────────────────

def send_summary(fixed: list, failed: list):
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from notify import send_email
        rows_fixed  = ''.join(f'<tr><td>{l}</td></tr>' for l in fixed)
        rows_failed = ''.join(f'<tr><td>{l}</td></tr>' for l in failed)
        body = f"""
<p><strong>Dev Fix Agent complete.</strong></p>
<p>Fixed: {len(fixed)} &nbsp;|&nbsp; Failed: {len(failed)}</p>
{'<table><tr><th>Fixed</th></tr>' + rows_fixed + '</table>' if fixed else ''}
{'<table><tr><th>Could not fix (manual review)</th></tr>' + rows_failed + '</table>' if failed else ''}
"""
        send_email(
            f"GK12 Dev Fix — {len(fixed)} fixed, {len(failed)} need manual review",
            body,
        )
    except Exception as e:
        print(f"Notify failed: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Dev Fix Agent")
    parser.add_argument('--lesson-id', help='Fix a single lesson ID')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview fixes without PATCHing the platform')
    parser.add_argument('--no-notify', action='store_true', help='Skip email')
    args = parser.parse_args()

    env     = _load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        sys.exit(1)

    reports = load_reports()
    all_reports = reports.get('reports', {})

    to_fix = {
        lid: r for lid, r in all_reports.items()
        if r.get('status') == 'needs_fix'
        and (args.lesson_id is None or lid == args.lesson_id)
    }

    if not to_fix:
        print("No lessons flagged as needs_fix. Run format_qc_agent.py first.")
        return

    print(f"Dev Fix: processing {len(to_fix)} lessons"
          + (" [DRY RUN]" if args.dry_run else "") + "...")

    fixed, failed = [], []

    for lesson_id, report in to_fix.items():
        ok = fix_lesson(lesson_id, report, api_key, args.dry_run)
        if ok:
            fixed.append(lesson_id)
            if not args.dry_run:
                report['status']  = 'fixed'
                report['fixedAt'] = datetime.now(timezone.utc).isoformat()
        else:
            failed.append(lesson_id)
        time.sleep(0.5)

    if not args.dry_run:
        save_reports(reports)

    print(f"\nDone. Fixed: {fixed or 'none'}. Failed: {failed or 'none'}.")

    if not args.no_notify and not args.dry_run:
        send_summary(fixed, failed)


if __name__ == '__main__':
    main()
