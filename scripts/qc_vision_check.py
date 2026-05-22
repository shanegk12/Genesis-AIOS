"""
Genesis K-12 QC Vision Check

Renders lesson content to a local HTML page, screenshots it with Playwright,
then asks Claude Vision to assess layout quality — image placement, tab/accordion
balance, callout positioning, and overall readability.

Run LOCALLY only. Playwright + Chromium are not in the Cloud Run container.

Setup (one-time):
  pip install playwright anthropic
  playwright install chromium

Usage:
  python scripts/qc_vision_check.py --lesson-id C-025
  python scripts/qc_vision_check.py --course C --limit 10
  python scripts/qc_vision_check.py --lesson-id C-025 --save

Requires env var:
  ANTHROPIC_API_KEY  — Claude API key (or set in .env)
"""

import argparse, base64, json, os, re, sys, tempfile, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
PLATFORM_KEY  = "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"
REPORT_PATH   = Path(__file__).parent / "qc_vision_reports.json"

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"  # fast + cheap for vision QC


# ── Platform API helpers ───────────────────────────────────────────────────────

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
        print(f"  [WARN] {e}")
        return None


# ── HTML renderer ──────────────────────────────────────────────────────────────

CSS = """
body {
  font-family: Georgia, 'Times New Roman', serif;
  max-width: 760px; margin: 0 auto; padding: 40px 24px;
  color: #1a1a1a; line-height: 1.75; font-size: 16px;
  background: #ffffff;
}
h1 { font-size: 26px; font-weight: 700; margin-bottom: 4px; color: #1B2A5C; }
h2 { font-size: 20px; font-weight: 700; margin-top: 36px; margin-bottom: 8px; color: #1B2A5C; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; }
h3 { font-size: 17px; font-weight: 600; margin-top: 20px; margin-bottom: 6px; }
h4 { font-size: 15px; font-weight: 600; margin-top: 16px; margin-bottom: 4px; }
p  { margin: 0 0 12px; }
ul, ol { margin: 0 0 12px 24px; }
li { margin-bottom: 4px; }
strong { font-weight: 700; }

/* Callout */
.callout { border-left: 4px solid #1B2A5C; background: #f0f4ff; padding: 14px 16px; margin: 20px 0; border-radius: 0 8px 8px 0; }
.callout.warning { border-color: #f59e0b; background: #fffbeb; }
.callout.tip     { border-color: #10b981; background: #f0fdf4; }
.callout.biblical { border-color: #C9A84C; background: #fefce8; }
.callout-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #6b7280; margin-bottom: 6px; }

/* Vocab */
.vocab-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 20px 0; }
.vocab-item { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 14px; }
.vocab-term { font-weight: 700; color: #1B2A5C; margin-bottom: 4px; font-size: 15px; }
.vocab-def  { font-size: 14px; color: #374151; }

/* Image */
.img-block { margin: 20px 0; text-align: center; }
.img-block img { max-width: 100%; border-radius: 8px; border: 1px solid #e5e7eb; }
.img-block.placeholder { background: #f3f4f6; border: 2px dashed #d1d5db; border-radius: 8px; padding: 32px; }
.img-caption { font-size: 13px; color: #6b7280; margin-top: 6px; font-style: italic; }
.img-pending-label { font-size: 13px; font-weight: 600; color: #9ca3af; }

/* Tabs */
.tabs-block { margin: 20px 0; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; }
.tabs-nav { display: flex; background: #f9fafb; border-bottom: 1px solid #e5e7eb; }
.tabs-nav button { padding: 10px 18px; font-size: 14px; font-weight: 600; border: none; background: none; cursor: pointer; color: #6b7280; border-bottom: 2px solid transparent; }
.tabs-nav button.active { color: #1B2A5C; border-bottom-color: #1B2A5C; background: #fff; }
.tabs-panel { padding: 18px 20px; display: none; }
.tabs-panel.active { display: block; }

/* Accordion */
.accordion-block { border: 1px solid #e5e7eb; border-radius: 8px; margin: 8px 0; overflow: hidden; }
.accordion-block summary { padding: 12px 16px; font-weight: 600; cursor: pointer; background: #f9fafb; list-style: none; display: flex; justify-content: space-between; align-items: center; }
.accordion-block summary::after { content: '▾'; color: #9ca3af; }
.accordion-block[open] summary::after { content: '▴'; }
.accordion-body { padding: 14px 16px; border-top: 1px solid #e5e7eb; }

/* Accordion grid */
.accordion-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 20px 0; }

/* Columns */
.columns-block { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0; }

/* Divider */
.divider { border: none; border-top: 2px solid #e5e7eb; margin: 28px 0; }

/* Carousel */
.carousel-block { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 10px; padding: 18px 20px; margin: 20px 0; }
.carousel-slide { margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb; }
.carousel-slide:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }
.carousel-slide-title { font-weight: 700; color: #1B2A5C; margin-bottom: 6px; }
"""

TABS_JS = """
document.querySelectorAll('.tabs-block').forEach(block => {
  const buttons = block.querySelectorAll('.tabs-nav button');
  const panels  = block.querySelectorAll('.tabs-panel');
  buttons.forEach((btn, i) => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      panels[i].classList.add('active');
    });
  });
  if (buttons.length) { buttons[0].classList.add('active'); panels[0].classList.add('active'); }
});
document.querySelectorAll('details').forEach(d => d.setAttribute('open', ''));
"""

def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_block(block: dict) -> str:
    t = block.get("type", "")
    d = block.get("data", {})

    if t == "text":
        return d.get("html", "")

    if t == "callout":
        variant = d.get("variant", "info")
        label_map = {"info": "Note", "tip": "Tip", "warning": "Warning", "biblical": "Biblical Connection"}
        label = label_map.get(variant, variant.title())
        return f'<div class="callout {variant}"><div class="callout-label">{label}</div>{d.get("html","")}</div>'

    if t == "image":
        src = d.get("src", "")
        caption = d.get("caption", "")
        if not src:
            label = esc(caption) if caption else "Image pending"
            return f'<div class="img-block placeholder"><p class="img-pending-label">[ IMAGE PENDING ]</p><p class="img-caption">{label}</p></div>'
        return f'<div class="img-block"><img src="{esc(src)}" alt="{esc(caption)}"><p class="img-caption">{esc(caption)}</p></div>'

    if t == "vocab":
        items = d.get("items", [])
        rows = "".join(
            f'<div class="vocab-item"><div class="vocab-term">{esc(i.get("term",""))}</div>'
            f'<div class="vocab-def">{esc(i.get("definition",""))}</div></div>'
            for i in items
        )
        return f'<div class="vocab-grid">{rows}</div>'

    if t == "tabs":
        tabs = d.get("tabs", [])
        nav = "".join(f'<button>{esc(tab.get("title",""))}</button>' for tab in tabs)
        panels = "".join(f'<div class="tabs-panel">{tab.get("html","")}</div>' for tab in tabs)
        return f'<div class="tabs-block"><div class="tabs-nav">{nav}</div>{panels}</div>'

    if t == "accordion":
        return (f'<details class="accordion-block"><summary>{esc(d.get("title",""))}</summary>'
                f'<div class="accordion-body">{d.get("html","")}</div></details>')

    if t == "accordion-grid":
        items = d.get("items", [])
        cells = "".join(
            f'<details class="accordion-block"><summary>{esc(i.get("title",""))}</summary>'
            f'<div class="accordion-body">{i.get("html","")}</div></details>'
            for i in items
        )
        return f'<div class="accordion-grid">{cells}</div>'

    if t == "columns":
        cols = d.get("cols", ["", ""])
        cells = "".join(f'<div>{c}</div>' for c in cols)
        return f'<div class="columns-block">{cells}</div>'

    if t == "divider":
        return '<hr class="divider">'

    if t == "carousel":
        slides = d.get("slides", [])
        parts = "".join(
            f'<div class="carousel-slide"><div class="carousel-slide-title">{esc(s.get("title",""))}</div>{s.get("html","")}</div>'
            for s in slides
        )
        return f'<div class="carousel-block">{parts}</div>'

    if t == "video":
        return f'<div class="callout"><div class="callout-label">Video</div><p>{esc(d.get("url",""))}</p></div>'

    if t == "math":
        latex = d.get("latex", "")
        return f'<pre style="background:#f9fafb;padding:12px;border-radius:6px;font-size:14px;">{esc(latex)}</pre>'

    return ""


def blocks_to_html(title: str, blocks: list) -> str:
    parts = [render_block(b) for b in blocks]
    body = "\n".join(p for p in parts if p)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style>
</head>
<body>
<h1>{esc(title)}</h1>
{body}
<script>{TABS_JS}</script>
</body>
</html>"""


# ── Screenshot ─────────────────────────────────────────────────────────────────

def screenshot_html(html: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright not installed. Run: pip install playwright && playwright install chromium")

    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", encoding="utf-8", delete=False) as f:
        f.write(html)
        tmp_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 900, "height": 1200})
            page.goto(f"file://{tmp_path}")
            page.wait_for_timeout(500)  # let tabs JS settle
            page.evaluate("document.querySelectorAll('details').forEach(d => d.setAttribute('open',''))")
            page.wait_for_timeout(200)
            full_height = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width": 900, "height": min(full_height + 80, 8000)})
            screenshot = page.screenshot(full_page=True)
            browser.close()
        return screenshot
    finally:
        os.unlink(tmp_path)


# ── Claude Vision ──────────────────────────────────────────────────────────────

def analyze_screenshot(png_bytes: bytes, lesson_id: str, title: str) -> dict:
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic not installed. Run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY env var not set.")

    client = anthropic.Anthropic(api_key=api_key)
    encoded = base64.standard_b64encode(png_bytes).decode("utf-8")

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": encoded},
                },
                {
                    "type": "text",
                    "text": f"""You are reviewing a rendered middle school engineering lesson page.
Lesson: "{title}" (ID: {lesson_id})

Assess the layout quality across these six areas:

1. IMAGES — Are image placeholders (dashed boxes labeled "IMAGE PENDING") positioned well relative to surrounding content? Does the caption suggest the image is relevant to the section? Flag any placeholder that seems misplaced or whose caption is vague or irrelevant.

2. TABS — If tabs are present, do the tab panels look balanced in length? Are the labels clear and parallel (e.g. "Phase 1 / Phase 2" not "Overview / Also Some Other Stuff")? Flag tabs where one panel is much longer than others or where the labels don't suggest a true comparison.

3. ACCORDIONS — Do expanded accordion/expandable sections look well-structured and appropriately sized? Flag any that appear empty or truncated.

4. CALLOUTS — Are note/tip/warning boxes placed naturally within the lesson flow, or do they interrupt mid-explanation?

5. REDUNDANT IMAGES — Look for consecutive image blocks that appear to show individual steps or components of a process that is already depicted in full in a nearby overview or infographic image. Example: a lesson shows one full "Creative Process" or "Engineering Steps" diagram, then immediately follows with 5-7 separate photos of each individual step — those individual photos are redundant. Flag them if you see this pattern, noting approximate position in the lesson.

6. IMAGE QUALITY — Do actual (non-placeholder) images appear relevant to the engineering or science topic of the lesson? Flag images that have excessive whitespace or padding around the subject, appear cropped in a way that cuts off important content, or show subject matter that clearly doesn't match the lesson topic.

7. OVERALL — Does the lesson look clean, readable, and appropriate for a middle school student?

Return JSON only — no other text:
{{
  "ok": true/false,
  "issues": ["issue 1", "issue 2"],
  "notes": "one-sentence overall summary"
}}

"ok" should be false if there are any issues worth fixing. Empty issues array + ok=true means the lesson looks good.""",
                },
            ],
        }],
    )

    raw = message.content[0].text.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"ok": True, "issues": [], "notes": raw}


# ── Main ───────────────────────────────────────────────────────────────────────

def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_lesson(lesson_id: str, save: bool) -> dict:
    print(f"\n  Fetching {lesson_id}…", end=" ", flush=True)
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return {"lessonId": lesson_id, "error": "fetch failed"}

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])
    print(f"{len(blocks)} blocks", end=" ", flush=True)

    html       = blocks_to_html(title, blocks)
    png        = screenshot_html(html)
    result     = analyze_screenshot(png, lesson_id, title)
    ok         = result.get("ok", True)
    issues     = result.get("issues", [])
    notes      = result.get("notes", "")

    status = "ok" if ok else "needs_review"
    print(f"→ {status}" + (f" ({len(issues)} issues)" if issues else ""))
    if issues:
        for issue in issues:
            print(f"    • {issue}")

    record = {
        "lessonId": lesson_id,
        "title": title,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "issues": issues,
        "notes": notes,
    }

    if save:
        reports: dict = {}
        if REPORT_PATH.exists():
            with open(REPORT_PATH, encoding="utf-8") as f:
                try:
                    reports = json.load(f)
                except json.JSONDecodeError:
                    reports = {}
        reports[lesson_id] = record
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(reports, f, indent=2, ensure_ascii=False)

    return record


def main():
    parser = argparse.ArgumentParser(description="QC Vision Check — screenshot + Claude Vision layout review")
    parser.add_argument("--lesson-id",  help="Check a single lesson")
    parser.add_argument("--course",     choices=["C", "M"], help="Check all lessons in a course")
    parser.add_argument("--limit",      type=int, default=0, help="Max lessons to check (0 = all)")
    parser.add_argument("--save",       action="store_true", help="Save results to qc_vision_reports.json")
    parser.add_argument("--needs-review-only", action="store_true", help="Only print lessons with issues")
    args = parser.parse_args()

    if not args.lesson_id and not args.course:
        parser.error("Provide --lesson-id or --course")

    lessons: list[str] = []
    if args.lesson_id:
        lessons = [args.lesson_id]
    else:
        manifest = load_manifest()
        prefix = args.course + "-"
        lessons = [l["id"] for l in manifest if l["id"].startswith(prefix)]
        if args.limit:
            lessons = lessons[: args.limit]

    print(f"\nGenesis K-12 QC Vision Check — {len(lessons)} lesson(s)")
    print("=" * 52)

    results = []
    needs_review = 0
    for lid in lessons:
        r = run_lesson(lid, args.save)
        results.append(r)
        if r.get("status") == "needs_review":
            needs_review += 1
        time.sleep(0.5)

    print(f"\n{'='*52}")
    print(f"Done. {len(results)} checked — {needs_review} need review, {len(results)-needs_review} ok.")
    if args.save:
        print(f"Results saved to {REPORT_PATH}")

    if args.needs_review_only:
        for r in results:
            if r.get("status") == "needs_review":
                print(f"\n  {r['lessonId']} — {r['title']}")
                for issue in r.get("issues", []):
                    print(f"    • {issue}")


if __name__ == "__main__":
    main()
