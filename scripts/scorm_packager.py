"""
Genesis K-12 SCORM Packager

Builds a full-lesson SCORM 1.2 ZIP per lesson:
  - Reads lesson text from Google Doc tab
  - Formats it as styled HTML (sections, vocab table, scripture callouts)
  - Embeds the three interactives (vocab grid, OCV widget, concept activity)
    as iframes at the right points in the lesson
  - Packages everything with imsmanifest.xml for LearnWorlds import

Output: scripts/scorm/[lesson-id].zip

Usage:
  python scorm_packager.py --lesson-id C-025
  python scorm_packager.py --all              # all lessons with interactives
  python scorm_packager.py --lesson-id C-025 --dry-run
  python scorm_packager.py --local-draft path/to/draft.txt --lesson-id C-025
"""

import argparse, json, os, re, sys, zipfile
import google.auth
from googleapiclient.discovery import build

MANIFEST_PATH    = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
INTERACTIVES_DIR = os.path.join(os.path.dirname(__file__), "interactives")
SCORM_DIR        = os.path.join(os.path.dirname(__file__), "scorm")

DOC_IDS = {
    "creationeering": "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
    "mousetrap":      "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
}

NAVY = "#1e3a5f"
GOLD = "#c9a227"


# ── IMSMANIFEST ──────────────────────────────────────────────────────────────

def build_manifest(lesson_id, title):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{lesson_id}" version="1.3"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2
    http://www.adlnet.org/xsd/adlcp_rootv1p2">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="{lesson_id}-ORG">
    <organization identifier="{lesson_id}-ORG">
      <title>{title}</title>
      <item identifier="ITEM_LESSON" identifierref="RES_LESSON">
        <title>{title}</title>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES_LESSON" type="webcontent"
              adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
      <file href="flashcards.html"/>
      <file href="accordion.html"/>
      <file href="ocv.html"/>
      <file href="concept.html"/>
    </resource>
  </resources>
</manifest>"""


# ── GOOGLE DOCS READ ──────────────────────────────────────────────────────────

def read_tab_content(doc_id, tab_title):
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/documents.readonly"])
    svc = build("docs", "v1", credentials=creds)
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title.strip().lower():
            body = tab.get("documentTab", {}).get("body", {})
            parts = []
            for element in body.get("content", []):
                for pe in element.get("paragraph", {}).get("elements", []):
                    parts.append(pe.get("textRun", {}).get("content", ""))
            return "".join(parts)
    raise ValueError(f"Tab '{tab_title}' not found")


# ── LESSON TEXT → HTML ────────────────────────────────────────────────────────

SECTION_HEADERS = [
    "Lesson Overview", "Learning Objectives", "Key Vocabulary",
    "The Beginning", "Part ", "Engineering Journal",
    "Technical Documentation", "Summary of Key Concepts", "Works Cited",
]

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def is_section_header(line):
    clean = re.sub(r'^#{1,6}\s*', '', line).strip()
    return any(clean.startswith(h) for h in SECTION_HEADERS)

def format_vocab_table(lines):
    """Convert plain vocab table lines into HTML table rows."""
    rows = ""
    header_done = False
    for line in lines:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if not cells:
            continue
        # Strip markdown bold from cells
        cells = [re.sub(r'\*\*(.+?)\*\*', r'\1', c) for c in cells]
        if re.match(r'^[-:\s]+$', cells[0]):
            continue
        if not header_done and cells[0].lower() in ('term', 'word'):
            rows += f"<tr><th>{esc(cells[0])}</th><th>{esc(cells[1]) if len(cells) > 1 else 'Definition'}</th></tr>\n"
            header_done = True
        else:
            rows += f"<tr><td>{esc(cells[0])}</td><td>{esc(cells[1]) if len(cells) > 1 else ''}</td></tr>\n"
    return f'<table class="vocab-table">\n{rows}</table>'

def draft_to_html(draft_text, lesson_id, topic, has_flashcards, has_accordion, has_ocv_html, has_concept_html):
    lines = draft_text.splitlines()
    html_parts = []
    in_vocab   = False
    vocab_lines = []
    in_para    = False
    concept_placed = False

    def flush_para():
        nonlocal in_para
        if in_para:
            html_parts.append("</p>")
            in_para = False

    def flush_vocab():
        nonlocal in_vocab, vocab_lines
        if in_vocab and vocab_lines:
            if has_vocab_html:
                html_parts.append(
                    '<div class="interactive-embed">'
                    '<iframe src="vocab.html" title="Key Vocabulary" '
                    'style="width:100%;height:420px;border:none;border-radius:8px;"></iframe>'
                    '</div>'
                )
            else:
                html_parts.append(format_vocab_table(vocab_lines))
            in_vocab   = False
            vocab_lines = []

    i = 0
    while i < len(lines):
        raw  = lines[i]
        line = re.sub(r'^#{1,6}\s*', '', raw).strip()

        # Blank line
        if not raw.strip():
            flush_para()
            i += 1
            continue

        # Section headers
        if is_section_header(raw) or is_section_header(line):
            flush_para()
            flush_vocab()

            # Place concept interactive before Engineering Journal
            if not concept_placed and has_concept_html and line.startswith("Engineering Journal"):
                html_parts.append(
                    '<div class="interactive-embed">'
                    '<h3 style="color:' + NAVY + ';margin-bottom:8px;">Concept Activity</h3>'
                    '<iframe src="concept.html" title="Concept Interactive" '
                    'style="width:100%;height:520px;border:none;border-radius:8px;"></iframe>'
                    '</div>'
                )
                concept_placed = True

            # OCV embed after Part sections that mention OCV
            if has_ocv_html and line.startswith("Engineering Journal"):
                html_parts.append(
                    '<div class="interactive-embed">'
                    '<h3 style="color:' + NAVY + ';margin-bottom:8px;">OCV Method</h3>'
                    '<iframe src="ocv.html" title="OCV Method" '
                    'style="width:100%;height:380px;border:none;border-radius:8px;"></iframe>'
                    '</div>'
                )

            if line.startswith("Key Vocabulary"):
                html_parts.append(f'<h2 id="vocab">{esc(line)}</h2>')
                if has_flashcards:
                    html_parts.append(
                        '<div class="interactive-embed">'
                        '<iframe src="flashcards.html" title="Vocabulary Flashcards" '
                        'style="width:100%;height:360px;border:none;border-radius:8px;"></iframe>'
                        '</div>'
                    )
                in_vocab = True
            elif line.startswith("The Beginning"):
                html_parts.append(f'<h2 class="section-faith">{esc(line)}</h2>')
            elif line.startswith("Part "):
                html_parts.append(f'<h2 class="section-part">{esc(line)}</h2>')
            elif line.startswith("Engineering Journal"):
                html_parts.append(f'<h2 class="section-journal">{esc(line)}</h2>')
            elif line.startswith("Summary"):
                html_parts.append(f'<h2 class="section-summary">{esc(line)}</h2>')
            elif line.startswith("Works Cited"):
                html_parts.append(f'<h2 class="section-cited">{esc(line)}</h2>')
            else:
                html_parts.append(f'<h2>{esc(line)}</h2>')
            i += 1
            continue

        # Scripture callout (pattern: "Book Chapter:Verse" anywhere in line)
        if re.search(r'\b\w+ \d+:\d+\b', line) and len(line) < 200:
            flush_para()
            flush_vocab()
            html_parts.append(f'<blockquote class="scripture">{esc(line)}</blockquote>')
            i += 1
            continue

        # Vocab table rows
        if in_vocab and "|" in raw:
            vocab_lines.append(raw)
            i += 1
            continue
        elif in_vocab:
            flush_vocab()

        # Bullet items
        if raw.startswith("- ") or raw.startswith("* "):
            flush_para()
            content = raw[2:].strip()
            html_parts.append(f'<li>{esc(content)}</li>')
            i += 1
            continue

        # Regular paragraph text
        if not in_para:
            html_parts.append("<p>")
            in_para = True
        else:
            html_parts.append(" ")
        html_parts.append(esc(line))
        i += 1

    flush_para()
    flush_vocab()

    # Place concept at end if never placed
    if not concept_placed and has_concept_html:
        html_parts.append(
            '<div class="interactive-embed">'
            '<h3 style="color:' + NAVY + ';margin-bottom:8px;">Concept Activity</h3>'
            '<iframe src="concept.html" title="Concept Interactive" '
            'style="width:100%;height:520px;border:none;border-radius:8px;"></iframe>'
            '</div>'
        )

    # Accordion embed at end of lesson if not already placed inline
    if has_accordion:
        html_parts.append(
            '<div class="interactive-embed">'
            '<h3 style="color:' + NAVY + ';margin-bottom:8px;">Review Sections</h3>'
            '<iframe src="accordion.html" title="Lesson Sections" '
            'style="width:100%;height:480px;border:none;border-radius:8px;"></iframe>'
            '</div>'
        )

    body = "\n".join(html_parts)
    return build_lesson_html(topic, body)


def build_lesson_html(topic, body_content):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(topic)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Georgia, sans-serif; background: #f7f9fc;
          color: #2d3748; line-height: 1.7; font-size: 16px; }}
  .lesson-wrap {{ max-width: 820px; margin: 0 auto; padding: 32px 24px 64px; }}
  .lesson-title {{ font-size: 1.9rem; font-weight: 800; color: {NAVY};
                   border-bottom: 4px solid {GOLD}; padding-bottom: 12px; margin-bottom: 28px; }}
  h2 {{ font-size: 1.25rem; font-weight: 700; color: {NAVY}; margin: 32px 0 12px;
        padding-left: 12px; border-left: 4px solid {GOLD}; }}
  h2.section-faith  {{ border-color: #8b5cf6; color: #5b21b6; }}
  h2.section-part   {{ border-color: {GOLD}; }}
  h2.section-journal {{ border-color: #059669; color: #065f46; }}
  h2.section-summary {{ border-color: {NAVY}; }}
  h2.section-cited   {{ border-color: #9ca3af; font-size: 1rem; }}
  p  {{ margin-bottom: 16px; }}
  li {{ margin-left: 24px; margin-bottom: 8px; }}
  ul, ol {{ margin-bottom: 16px; }}
  blockquote.scripture {{
    background: #ede9fe; border-left: 4px solid #7c3aed;
    padding: 14px 18px; border-radius: 0 8px 8px 0;
    margin: 20px 0; color: #4c1d95; font-style: italic; font-size: 0.95rem;
  }}
  .vocab-table {{ width: 100%; border-collapse: collapse; margin: 16px 0 24px; }}
  .vocab-table th {{ background: {NAVY}; color: #fff; padding: 10px 14px; text-align: left;
                     font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .vocab-table td {{ padding: 10px 14px; border-bottom: 1px solid #dde3ee; font-size: 0.9rem; }}
  .vocab-table td:first-child {{ font-weight: 700; color: {NAVY}; width: 30%; }}
  .vocab-table tr:last-child td {{ border-bottom: none; }}
  .interactive-embed {{
    background: #fff; border: 1px solid #dde3ee; border-radius: 10px;
    padding: 20px; margin: 28px 0; box-shadow: 0 2px 8px rgba(30,58,95,0.08);
  }}
  iframe {{ display: block; }}
</style>
</head>
<body>
<div class="lesson-wrap">
<div class="lesson-title">{esc(topic)}</div>
{body_content}
</div>
</body>
</html>"""


# ── PACKAGER ──────────────────────────────────────────────────────────────────

def package_lesson(lesson, draft_text, dry_run=False):
    lesson_id = lesson["id"]
    topic     = lesson["topic"]
    idir      = os.path.join(INTERACTIVES_DIR, lesson_id)

    # Detect which interactives exist
    has = {
        t: os.path.exists(os.path.join(idir, f"{t}.html"))
        for t in ("flashcards", "accordion", "ocv", "concept")
    }

    zip_path = os.path.join(SCORM_DIR, f"{lesson_id}.zip")

    if dry_run:
        print(f"  Would create: {zip_path}")
        print(f"  Interactives present: {[t for t, v in has.items() if v]}")
        return None

    # Build lesson HTML
    index_html = draft_to_html(draft_text, lesson_id, topic,
                                has["flashcards"], has["accordion"],
                                has["ocv"], has["concept"])
    manifest_xml = build_manifest(lesson_id, topic)

    os.makedirs(SCORM_DIR, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("imsmanifest.xml", manifest_xml)
        zf.writestr("index.html",      index_html)
        for itype in ("flashcards", "accordion", "ocv", "concept"):
            html_path = os.path.join(idir, f"{itype}.html")
            if os.path.exists(html_path):
                zf.write(html_path, f"{itype}.html")
            else:
                zf.writestr(f"{itype}.html",
                    f'<html><body style="padding:20px;color:#888;">'
                    f'[{itype} interactive not yet generated]</body></html>')

    size_kb = os.path.getsize(zip_path) // 1024
    rel     = os.path.relpath(zip_path, os.path.dirname(MANIFEST_PATH))
    print(f"  Created: {zip_path} ({size_kb}KB)  interactives={[t for t,v in has.items() if v]}")
    return rel


def update_manifest_scorm(data, lesson_id, scorm_rel):
    for m in data["lessons"]:
        if m["id"] == lesson_id:
            m["scorm_status"] = "done" if scorm_rel else "failed"
            m["scorm_file"]   = scorm_rel
            break
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 SCORM Packager")
    parser.add_argument("--lesson-id",    help="Package one lesson")
    parser.add_argument("--all",          action="store_true",
                        help="Package all done lessons (with or without interactives)")
    parser.add_argument("--local-draft",  help="Use a local draft file instead of Google Doc")
    parser.add_argument("--dry-run",      action="store_true")
    args = parser.parse_args()

    if not args.lesson_id and not args.all:
        parser.error("Provide --lesson-id or --all")

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    targets = []
    if args.all:
        targets = [l for l in data["lessons"]
                   if l["status"] == "done" and l.get("scorm_status") != "done"]
    else:
        lesson = next((l for l in data["lessons"] if l["id"] == args.lesson_id), None)
        if not lesson:
            print(f"Lesson {args.lesson_id} not found")
            sys.exit(1)
        targets = [lesson]

    if not targets:
        print("No lessons need packaging.")
        return

    print(f"SCORM packaging: {len(targets)} lesson(s)\n")

    for lesson in targets:
        print(f"[{lesson['id']}] {lesson['tab']}")

        if args.local_draft and len(targets) == 1:
            with open(args.local_draft, encoding="utf-8") as f:
                draft = f.read()
        else:
            try:
                doc_id = DOC_IDS[lesson["doc"]]
                draft  = read_tab_content(doc_id, lesson["tab"])
                print(f"  Read {len(draft):,} chars from Google Doc")
            except Exception as e:
                print(f"  Could not read Google Doc: {e}. Skipping.")
                continue

        rel = package_lesson(lesson, draft, args.dry_run)
        if not args.dry_run:
            update_manifest_scorm(data, lesson["id"], rel)

    print("\nDone.")


if __name__ == "__main__":
    main()
