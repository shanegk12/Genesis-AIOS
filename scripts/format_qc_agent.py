"""
Genesis K-12 Format QC Agent

Post-import formatting quality check. Fetches lesson HTML from the platform API,
checks it against visual presets calibrated from LW lesson screenshots.

Writes results to scripts/qc_reports.json. Sends email summary.
Does NOT block imports or modify lessons.

Usage:
  python scripts/format_qc_agent.py                     # check all imported lessons
  python scripts/format_qc_agent.py --lesson-id C-001   # check one lesson
  python scripts/format_qc_agent.py --all-statuses      # include already-clean lessons
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

MANIFEST_PATH  = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
REPORTS_PATH   = os.path.join(os.path.dirname(__file__), "qc_reports.json")

LIVE_URL  = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
API_KEY   = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"

EXEMPT_HEADINGS = {
    "lesson overview", "learning objective", "learning objectives",
    "key vocabulary", "vocabulary", "assessment", "quiz",
    "works cited", "references", "summary of key concepts",
    "engineering journal", "technical documentation",
}

WORD_WALL_PARAS = 4
WORD_WALL_WORDS = 200
ACCORDION_IMAGE_THRESHOLD = 2  # paragraphs before image required
TAB_IMAGE_THRESHOLD = 2


# ── Markdown detection ────────────────────────────────────────────────────────

def is_markdown_content(html: str) -> bool:
    """True if lesson HTML contains raw markdown or has no heading structure."""
    has_markdown = bool(
        re.search(r'<p[^>]*>\s*#{1,4}\s', html) or
        re.search(r'<p[^>]*>\s*\*\*', html) or
        re.search(r'<p[^>]*>\s*\*\s', html)
    )
    # Also flag content with no <h2>/<h3> but substantial text (unstructured import)
    has_headings = bool(re.search(r'<h[23][^>]*>', html))
    word_count   = len(re.sub(r'<[^>]+>', '', html).split())
    is_unstructured = not has_headings and word_count > 300
    return has_markdown or is_unstructured


# ── HTML analysis ─────────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    return re.sub(r'<[^>]+>', '', html).strip()


def analyze_html(html: str) -> list[dict]:
    """
    Split HTML into sections by H2/H3 and extract structural stats.
    Returns list of section dicts.
    """
    # Split by heading tags while keeping the delimiters
    parts = re.split(r'(<h[23][^>]*>.*?</h[23]>)', html, flags=re.DOTALL)
    sections = []
    current: dict | None = None

    for part in parts:
        h_match = re.match(r'<h[23][^>]*>(.*?)</h[23]>', part, re.DOTALL)
        if h_match:
            heading = _strip_tags(h_match.group(1))
            current = {
                'heading':       heading,
                'heading_lower': heading.lower(),
                'html':          '',
                'paras':         0,
                'images':        0,
                'widgets':       0,
                'words':         0,
                'accordions':    [],
                'tabs':          [],
            }
            sections.append(current)
        elif current is not None:
            current['html'] += part

    for sec in sections:
        _analyze_section(sec)

    return sections


def _analyze_section(sec: dict):
    h = sec['html']

    # Paragraphs + word count (excluding those inside accordions/tabs/widgets)
    stripped = re.sub(r'<details[^>]*>.*?</details>', '', h, flags=re.DOTALL)
    stripped = re.sub(r'<div[^>]*tab-group-block[^>]*>.*?</div>\s*</div>', '', stripped, flags=re.DOTALL)

    for p_match in re.finditer(r'<p[^>]*>(.*?)</p>', stripped, re.DOTALL):
        text = _strip_tags(p_match.group(1))
        if text and not text.startswith('[IMAGE NEEDED'):
            sec['paras'] += 1
            sec['words'] += len(text.split())

    # Images (direct — not inside accordions/tabs, counted separately)
    stripped_for_img = re.sub(r'<details[^>]*>.*?</details>', '', h, flags=re.DOTALL)
    sec['images'] = len(re.findall(r'<img\s', stripped_for_img))

    # Carousels count as images
    carousels = len(re.findall(r'data-carousel', h))
    sec['images'] += carousels
    sec['widgets'] += carousels

    # Callouts + columns (matches blocksToHtml class names)
    sec['widgets'] += len(re.findall(r'callout-block', h))
    sec['widgets'] += len(re.findall(r'data-columns', h))

    # Accordions (blocksToHtml generates <details class="accordion-block">)
    for acc_match in re.finditer(r'<details[^>]*>(.*?)</details>', h, re.DOTALL):
        acc_html = acc_match.group(1)
        title_m  = re.search(r'<summary[^>]*>(.*?)</summary>', acc_html, re.DOTALL)
        title    = _strip_tags(title_m.group(1)) if title_m else ''
        body_paras  = len(re.findall(r'<p[^>]*>.*?</p>', acc_html, re.DOTALL))
        body_images = len(re.findall(r'<img\s', acc_html))
        sec['accordions'].append({'title': title, 'paras': body_paras, 'images': body_images})
        sec['widgets'] += 1

    # Tab panels
    seen_tab_groups = set()
    for tab_m in re.finditer(r'<div[^>]*data-tab-panel="([^"]*)"[^>]*>(.*?)</div>', h, re.DOTALL):
        label     = tab_m.group(1)
        tab_html  = tab_m.group(2)
        tab_paras = len(re.findall(r'<p[^>]*>.*?</p>', tab_html, re.DOTALL))
        tab_imgs  = len(re.findall(r'<img\s', tab_html))
        sec['tabs'].append({'label': label, 'paras': tab_paras, 'images': tab_imgs})
        group_pos = tab_m.start()
        # Count each tab group once as a widget
        bucket = group_pos // 500
        if bucket not in seen_tab_groups:
            sec['widgets'] += 1
            seen_tab_groups.add(bucket)


# ── Preset checks ─────────────────────────────────────────────────────────────

def run_checks(html: str, sections: list[dict]) -> list[dict]:
    issues = []

    # Placeholder content check — whole HTML
    if re.search(r'Content goes here', html, re.IGNORECASE):
        issues.append({
            'rule':        'placeholder-content',
            'location':    'Document',
            'description': 'Lesson contains unreplaced placeholder text ("Content goes here…")',
        })

    for sec in sections:
        if any(ex in sec['heading_lower'] for ex in EXEMPT_HEADINGS):
            continue

        has_visual = sec['images'] > 0 or sec['widgets'] > 0

        # Section image coverage
        if not has_visual and sec['paras'] > 0:
            issues.append({
                'rule':        'section-image',
                'location':    f'Section: {sec["heading"]}',
                'description': f'No image or widget in this section ({sec["paras"]} paragraphs)',
            })

        # Word wall (only flag once even if section-image already flagged)
        elif not has_visual and (sec['words'] > WORD_WALL_WORDS or sec['paras'] > WORD_WALL_PARAS):
            issues.append({
                'rule':        'word-wall',
                'location':    f'Section: {sec["heading"]}',
                'description': (f'{sec["words"]} words / {sec["paras"]} paragraphs'
                                f' with no visual break'),
            })

        # Accordion image
        for acc in sec['accordions']:
            if acc['paras'] > ACCORDION_IMAGE_THRESHOLD and acc['images'] == 0:
                issues.append({
                    'rule':        'accordion-image',
                    'location':    f'Accordion: {acc["title"] or "(untitled)"}',
                    'description': (f'Accordion has {acc["paras"]} paragraphs'
                                    f' but no image reference'),
                })

        # Tab image
        for tab in sec['tabs']:
            if tab['paras'] > TAB_IMAGE_THRESHOLD and tab['images'] == 0:
                issues.append({
                    'rule':        'tab-image',
                    'location':    f'Tab: {tab["label"] or "(untitled)"}',
                    'description': (f'Tab panel has {tab["paras"]} paragraphs'
                                    f' but no image reference'),
                })

    return issues


# ── Platform API ──────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str) -> dict | None:
    url = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"  API error {e.code} for {lesson_id}")
        return None
    except Exception as e:
        print(f"  Fetch error for {lesson_id}: {e}")
        return None


# ── Report I/O ────────────────────────────────────────────────────────────────

def load_reports() -> dict:
    if os.path.exists(REPORTS_PATH):
        with open(REPORTS_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {'generated_at': '', 'reports': {}}


def save_reports(data: dict):
    data['generated_at'] = datetime.now(timezone.utc).isoformat()
    with open(REPORTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Core QC run ───────────────────────────────────────────────────────────────

def check_lesson(lesson_id: str, title: str, reports: dict) -> str:
    """Fetch lesson, run checks, update report. Returns status string."""
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        print(f"  [{lesson_id}] Not found on platform — skipping")
        return 'skipped'

    content = lesson.get('content', '')
    if not content:
        print(f"  [{lesson_id}] No content — skipping")
        return 'skipped'

    now = datetime.now(timezone.utc).isoformat()

    # Markdown-as-text detection (fast path)
    if is_markdown_content(content):
        report = {
            'lessonId':  lesson_id,
            'title':     title or lesson.get('title', lesson_id),
            'checkedAt': now,
            'status':    'needs_reformat',
            'issues':    [{'rule': 'needs-reformat', 'location': 'Document',
                           'description': 'Content contains raw markdown — run reformat agent first'}],
            'fixedAt':   None,
        }
        reports['reports'][lesson_id] = report
        print(f"  [{lesson_id}] needs_reformat (raw markdown detected)")
        return 'needs_reformat'

    # Full widget/layout checks
    sections = analyze_html(content)
    issues   = run_checks(content, sections)

    if not issues:
        status = 'clean'
    else:
        existing = reports['reports'].get(lesson_id, {})
        # Preserve 'fixed' status if dev agent already resolved it
        status = 'needs_fix' if existing.get('status') != 'fixed' else 'fixed'

    report = {
        'lessonId':  lesson_id,
        'title':     title or lesson.get('title', lesson_id),
        'checkedAt': now,
        'status':    status,
        'issues':    issues,
        'fixedAt':   reports['reports'].get(lesson_id, {}).get('fixedAt'),
    }
    reports['reports'][lesson_id] = report

    flag = f"  [{lesson_id}] {status} — {len(issues)} issue(s)"
    if issues:
        for iss in issues:
            flag += f"\n    • [{iss['rule']}] {iss['location']}: {iss['description']}"
    print(flag)
    return status


# ── Notification ──────────────────────────────────────────────────────────────

def send_summary(counts: dict):
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from notify import send_email
        total   = counts['total']
        flagged = counts['needs_fix']
        reformat = counts['needs_reformat']
        clean   = counts['clean']
        skipped = counts['skipped']
        body = f"""
<p><strong>Format QC complete.</strong> {total} lessons checked.</p>
<table>
  <tr><th>Status</th><th>Count</th></tr>
  <tr><td>Clean</td><td>{clean}</td></tr>
  <tr><td>Needs fix</td><td>{flagged}</td></tr>
  <tr><td>Needs reformat</td><td>{reformat}</td></tr>
  <tr><td>Skipped</td><td>{skipped}</td></tr>
</table>
<p>Dev fix agent will run next to address flagged lessons.</p>
"""
        send_email(f"GK12 Format QC — {flagged} lessons need fix, {reformat} need reformat", body)
    except Exception as e:
        print(f"Notify failed: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Format QC Agent")
    parser.add_argument('--lesson-id', help='Check a single lesson ID')
    parser.add_argument('--all-statuses', action='store_true',
                        help='Re-check clean lessons too (default: skip clean)')
    parser.add_argument('--no-notify', action='store_true', help='Skip email notification')
    args = parser.parse_args()

    with open(MANIFEST_PATH, encoding='utf-8') as f:
        manifest = json.load(f)

    lessons_to_check = [
        l for l in manifest['lessons']
        if l['status'] == 'done'
        and (args.lesson_id is None or l['id'] == args.lesson_id)
    ]

    if not lessons_to_check:
        print("No lessons to check.")
        return

    reports = load_reports()
    counts  = {'total': 0, 'clean': 0, 'needs_fix': 0, 'needs_reformat': 0, 'skipped': 0}

    print(f"Format QC: checking {len(lessons_to_check)} lessons...")
    for lesson in lessons_to_check:
        lid    = lesson['id']
        title  = lesson.get('tab', lid)

        # Skip already-clean unless --all-statuses
        existing_status = reports['reports'].get(lid, {}).get('status')
        if existing_status == 'clean' and not args.all_statuses and args.lesson_id is None:
            continue

        counts['total'] += 1
        status = check_lesson(lid, title, reports)
        counts[status] = counts.get(status, 0) + 1
        time.sleep(0.1)  # gentle rate limiting

    save_reports(reports)
    print(f"\nDone. {counts}")

    if not args.no_notify and counts['total'] > 0:
        send_summary(counts)


if __name__ == '__main__':
    main()
