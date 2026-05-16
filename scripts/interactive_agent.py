"""
Genesis K-12 Interactive Agent

Generates self-contained HTML interactives for a lesson:
  1. vocab.html   — two-column checkmark vocabulary grid
  2. ocv.html     — Objective / Constraint / Variable tab widget
  3. concept.html — Claude API (claude-opus-4-7) custom JS activity

Saves to: scripts/interactives/[lesson-id]/
Updates manifest with interactive_status + interactive_files

Usage:
  python interactive_agent.py --draft-file path/to/draft.txt \\
      --lesson-id C-030 --topic "Procurement" --doc creationeering
  python interactive_agent.py --lesson-id C-030   # re-run on already-done lesson
  python interactive_agent.py --skip-concept       # vocab + OCV only (no Claude API)
  python interactive_agent.py --dry-run            # list targets, no generation
"""

import argparse, json, os, re, sys, urllib.request, urllib.error

MANIFEST_PATH    = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
INTERACTIVES_DIR = os.path.join(os.path.dirname(__file__), "interactives")

CLAUDE_MODEL = "claude-opus-4-7"
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"

NAVY = "#1e3a5f"
GOLD = "#c9a227"


# ── ENV ──────────────────────────────────────────────────────────────────────

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


# ── PARSERS ──────────────────────────────────────────────────────────────────

def parse_vocab(draft):
    """Extract (term, definition) pairs from Key Vocabulary section."""
    # Handle both plain and markdown-header formats (###, ##, or no prefix)
    section_end = r'(?:The Beginning|Learning Objectives|Engineering Journal|Technical Documentation|Summary of Key Concepts|Works Cited|Part \d)'
    match = re.search(
        r'Key Vocabulary\s*\n(.*?)(?=\n#{0,6}\s*' + section_end + r')',
        draft, re.DOTALL | re.IGNORECASE
    )
    section = match.group(1) if match else draft[:3000]

    def clean_cell(s):
        s = s.strip()
        s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
        s = re.sub(r'\*(.+?)\*',     r'\1', s)
        s = re.sub(r'`(.+?)`',       r'\1', s)
        return s.strip()

    # Try markdown table: | term | definition |
    vocab = []
    for row in re.findall(r'\|([^|\n]+)\|([^|\n]+)\|', section):
        term, defn = clean_cell(row[0]), clean_cell(row[1])
        if not term or not defn:
            continue
        if re.match(r'^[-:\s]+$', term) or term.lower() in ('term', 'definition', 'word'):
            continue
        vocab.append((term, defn))
    if vocab:
        return vocab

    # Try "Term: Definition" colon pairs
    for line in section.splitlines():
        line = line.strip()
        if ':' in line and len(line) < 300:
            parts = line.split(':', 1)
            term, defn = parts[0].strip(), parts[1].strip()
            if term and defn and len(term) < 60 and not term.startswith(('http', 'www')):
                vocab.append((term, defn))
    if vocab:
        return vocab[:12]

    return []


def parse_ocv(draft):
    """Extract Objective / Constraint / Variable text from draft."""
    ocv = {}
    patterns = {
        'objective':  r'[Oo]bjective[:\s]+([^\n]+(?:\n(?!\s*[A-Z][a-z]|\s*Constraint|\s*Variable)[^\n]+)*)',
        'constraint': r'[Cc]onstraint[s]?[:\s]+([^\n]+(?:\n(?!\s*[A-Z][a-z]|\s*Objective|\s*Variable)[^\n]+)*)',
        'variable':   r'[Vv]ariable[s]?[:\s]+([^\n]+(?:\n(?!\s*[A-Z][a-z]|\s*Objective|\s*Constraint)[^\n]+)*)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, draft)
        if m:
            ocv[key] = m.group(1).strip()[:400]
    return ocv


def get_lesson_excerpt(draft, chars=1800):
    """Return a meaningful excerpt: skip boilerplate headers, grab meat of lesson."""
    start = 0
    for marker in ['The Beginning', 'Part 1', 'Part One']:
        idx = draft.find(marker)
        if idx > 0:
            start = idx
            break
    return draft[start:start + chars].strip()


# ── HTML GENERATORS ───────────────────────────────────────────────────────────

def generate_vocab_html(vocab, topic):
    if not vocab:
        return None

    items = ""
    for term, defn in vocab:
        term_esc = term.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        defn_esc = defn.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        items += f"""
    <div class="vocab-item">
      <div class="check">&#10003;</div>
      <div class="content">
        <div class="term">{term_esc}</div>
        <div class="defn">{defn_esc}</div>
      </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Key Vocabulary</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f7f9fc; padding: 20px; }}
  h2 {{ color: {NAVY}; font-size: 1rem; font-weight: 700; margin-bottom: 16px;
       text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 2px solid {GOLD};
       padding-bottom: 6px; display: inline-block; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .vocab-item {{ background: #fff; border: 1px solid #dce4ee; border-radius: 8px;
                 padding: 14px 12px; display: flex; align-items: flex-start; gap: 10px;
                 transition: box-shadow 0.15s; }}
  .vocab-item:hover {{ box-shadow: 0 2px 8px rgba(30,58,95,0.12); }}
  .check {{ color: {GOLD}; font-size: 1.3rem; font-weight: 900; flex-shrink: 0; margin-top: 1px; }}
  .term  {{ font-weight: 700; color: {NAVY}; font-size: 0.88rem; margin-bottom: 5px; }}
  .defn  {{ color: #4a5568; font-size: 0.83rem; line-height: 1.45; }}
  @media (max-width: 560px) {{ .grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h2>Key Vocabulary</h2>
<div class="grid">{items}
</div>
</body>
</html>"""


def generate_ocv_html(ocv, topic):
    objective  = ocv.get('objective',  'Define what success looks like — the measurable goal of your design.')
    constraint = ocv.get('constraint', 'Identify fixed limits: budget, materials, time, size, or safety requirements.')
    variable   = ocv.get('variable',   'Identify what you can adjust to move closer to your objective within the constraints.')

    def esc(s):
        return s.replace('<', '&lt;').replace('>', '&gt;')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OCV Method</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f7f9fc; padding: 20px; }}
  h2 {{ color: {NAVY}; font-size: 1rem; font-weight: 700; margin-bottom: 14px;
       text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 2px solid {GOLD};
       padding-bottom: 6px; display: inline-block; }}
  .tabs {{ display: flex; gap: 4px; margin-bottom: 0; }}
  .tab {{ padding: 10px 22px; cursor: pointer; font-weight: 600; color: #666;
          font-size: 0.88rem; border-radius: 6px 6px 0 0; border: 1px solid #dce4ee;
          border-bottom: none; background: #eef2f7; transition: all 0.15s; }}
  .tab.active {{ background: {NAVY}; color: #fff; border-color: {NAVY}; }}
  .tab:hover:not(.active) {{ background: #dce4ee; }}
  .panel {{ display: none; background: #fff; border: 1px solid #dce4ee;
            border-radius: 0 6px 6px 6px; padding: 22px; }}
  .panel.active {{ display: block; }}
  .label {{ font-weight: 700; color: {GOLD}; font-size: 0.78rem; text-transform: uppercase;
            letter-spacing: 0.06em; margin-bottom: 10px; }}
  .panel p {{ color: #3a4558; font-size: 0.9rem; line-height: 1.6; }}
  .your-turn {{ margin-top: 16px; background: #f0f4fa; border-left: 3px solid {GOLD};
                padding: 12px 14px; border-radius: 0 6px 6px 0; }}
  .your-turn span {{ font-size: 0.82rem; color: #5a6a7e; font-style: italic; }}
  textarea {{ width: 100%; margin-top: 8px; padding: 8px; border: 1px solid #c5cfe0;
              border-radius: 6px; font-size: 0.85rem; resize: vertical; font-family: inherit;
              min-height: 60px; color: #2d3748; }}
</style>
</head>
<body>
<h2>OCV Method</h2>
<div class="tabs">
  <div class="tab active" onclick="show('obj',this)">Objective</div>
  <div class="tab" onclick="show('con',this)">Constraints</div>
  <div class="tab" onclick="show('var',this)">Variables</div>
</div>
<div id="obj" class="panel active">
  <div class="label">Objective</div>
  <p>{esc(objective)}</p>
  <div class="your-turn">
    <span>Your turn: Write your own objective for this lesson's design problem.</span>
    <textarea placeholder="My objective is..."></textarea>
  </div>
</div>
<div id="con" class="panel">
  <div class="label">Constraints</div>
  <p>{esc(constraint)}</p>
  <div class="your-turn">
    <span>List two constraints that apply to your design.</span>
    <textarea placeholder="1. &#10;2. "></textarea>
  </div>
</div>
<div id="var" class="panel">
  <div class="label">Variables</div>
  <p>{esc(variable)}</p>
  <div class="your-turn">
    <span>What is one variable you would change first, and why?</span>
    <textarea placeholder="I would change..."></textarea>
  </div>
</div>
<script>
function show(id, tab) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  tab.classList.add('active');
}}
</script>
</body>
</html>"""


# ── CLAUDE API ────────────────────────────────────────────────────────────────

CONCEPT_PROMPT = """You are building a self-contained HTML/JavaScript interactive activity for a Genesis K-12 Academy Middle School {course} lesson on "{topic}" (Creationeering phase: {phase}).

Create an engaging interactive that reinforces one core concept from this lesson. Requirements:
- FULLY self-contained single HTML file — no CDN links, no external scripts or stylesheets
- Works inside an iframe (no parent/window references)
- Appropriate for 6th-8th grade; intuitive without written instructions
- Takes 3-5 minutes to complete
- Provides clear feedback or a score at the end
- GK12 color palette: navy #1e3a5f, gold #c9a227, white #ffffff, light gray #f7f9fc
- Faith reference optional and brief if included — do not force it

Good interactive types for engineering topics:
- Drag-and-drop sorting or matching game
- Step-through simulation with "what happens next?" prompts
- Trade-off slider (adjust one variable, see cost/benefit update live)
- Quiz with immediate feedback and explanation
- Build-your-own flowchart or decision tree

Lesson excerpt for context:
{excerpt}

Output ONLY the complete HTML file from <!DOCTYPE html> to </html>. No explanation, no code fences."""


def call_claude_for_interactive(api_key, topic, phase, doc, excerpt):
    course_label = "Creationeering" if doc == "creationeering" else "Mousetrap Build"
    prompt = CONCEPT_PROMPT.format(
        course=course_label,
        topic=topic,
        phase=phase,
        excerpt=excerpt,
    )

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        CLAUDE_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["content"][0]["text"].strip()
        # Strip code fences if present
        text = re.sub(r'^```html\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^```\s*',     '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$',     '', text.strip())
        return text if text.startswith('<!') else None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"  Claude API error {e.code}: {body[:300]}")
        return None
    except Exception as e:
        print(f"  Claude API error: {e}")
        return None


# ── MANIFEST ──────────────────────────────────────────────────────────────────

def update_manifest(lesson_id, files, status):
    if not os.path.exists(MANIFEST_PATH):
        return
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    for m in data["lessons"]:
        if m["id"] == lesson_id:
            m["interactive_status"] = status
            m["interactive_files"]  = files
            break
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── CORE ──────────────────────────────────────────────────────────────────────

def run_interactive(draft_text, lesson_id, topic, phase, doc, api_key, skip_concept=False):
    out_dir = os.path.join(INTERACTIVES_DIR, lesson_id)
    os.makedirs(out_dir, exist_ok=True)

    files = {}
    errors = []

    # 1. Vocab grid
    vocab = parse_vocab(draft_text)
    if vocab:
        html = generate_vocab_html(vocab, topic)
        path = os.path.join(out_dir, "vocab.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        files["vocab"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
        print(f"  Vocab:    {len(vocab)} terms  -> {path}")
    else:
        print(f"  Vocab:    no terms parsed — skipping")
        errors.append("vocab_parse_failed")

    # 2. OCV tab widget
    ocv = parse_ocv(draft_text)
    ocv_html = generate_ocv_html(ocv, topic)
    path = os.path.join(out_dir, "ocv.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ocv_html)
    files["ocv"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
    found = [k for k in ('objective', 'constraint', 'variable') if k in ocv]
    print(f"  OCV:      {found or 'defaults'} -> {path}")

    # 3. Concept interactive via Claude API
    if not skip_concept:
        if not api_key:
            print(f"  Concept:  SKIPPED — ANTHROPIC_API_KEY not set")
            errors.append("no_api_key")
        else:
            excerpt = get_lesson_excerpt(draft_text)
            print(f"  Concept:  calling Claude ({CLAUDE_MODEL})...")
            html = call_claude_for_interactive(api_key, topic, phase, doc, excerpt)
            if html:
                path = os.path.join(out_dir, "concept.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                files["concept"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
                print(f"  Concept:  {len(html):,} chars -> {path}")
            else:
                print(f"  Concept:  Claude returned no valid HTML")
                errors.append("concept_failed")

    status = "done" if not errors else ("partial" if files else "failed")
    update_manifest(lesson_id, files, status)
    print(f"  Status:   {status}  ({len(files)} files written)")
    return status


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Interactive Agent")
    parser.add_argument("--draft-file",   help="Path to draft text file")
    parser.add_argument("--lesson-id",    required=True, help="Lesson ID (e.g. C-030)")
    parser.add_argument("--topic",        help="Lesson topic")
    parser.add_argument("--phase",        help="Creationeering phase")
    parser.add_argument("--doc",          choices=["creationeering", "mousetrap"])
    parser.add_argument("--skip-concept", action="store_true",
                        help="Skip Claude API concept interactive (vocab + OCV only)")
    parser.add_argument("--dry-run",      action="store_true",
                        help="Show what would be generated without making API calls")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

    # Load lesson metadata from manifest if not provided
    if not all([args.topic, args.phase, args.doc]):
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            manifest = json.load(f)
        lesson = next((l for l in manifest["lessons"] if l["id"] == args.lesson_id), None)
        if not lesson:
            print(f"Lesson {args.lesson_id} not found in manifest")
            sys.exit(1)
        args.topic = args.topic or lesson["topic"]
        args.phase = args.phase or lesson["phase"]
        args.doc   = args.doc   or lesson["doc"]

    # Load draft from file or Google Doc
    if args.draft_file:
        if not os.path.exists(args.draft_file):
            print(f"Draft file not found: {args.draft_file}")
            sys.exit(1)
        with open(args.draft_file, encoding="utf-8") as f:
            draft_text = f.read()
    else:
        # Pull from Google Doc via rerun_qc helper
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from rerun_qc import read_tab_content, DOC_IDS
            with open(MANIFEST_PATH, encoding="utf-8") as f:
                manifest = json.load(f)
            lesson = next(l for l in manifest["lessons"] if l["id"] == args.lesson_id)
            doc_id = DOC_IDS[lesson["doc"]]
            print(f"Reading tab '{lesson['tab']}' from Google Doc...")
            draft_text = read_tab_content(doc_id, lesson["tab"])
            if len(draft_text.strip()) < 200:
                print(f"Tab content too short ({len(draft_text)} chars). Check the Google Doc.")
                sys.exit(1)
            print(f"Read {len(draft_text):,} chars from Google Doc")
        except Exception as e:
            print(f"Could not read from Google Doc: {e}")
            print("Re-run with --draft-file to provide a local draft.")
            sys.exit(1)

    print(f"\nInteractives: [{args.lesson_id}] {args.topic}")
    print(f"  Course: {args.doc}  Phase: {args.phase}")
    if args.dry_run:
        vocab = parse_vocab(draft_text)
        ocv   = parse_ocv(draft_text)
        print(f"  Would generate: vocab ({len(vocab)} terms), OCV ({list(ocv.keys()) or 'defaults'})")
        if not args.skip_concept:
            print(f"  Would call Claude API: {'yes' if api_key else 'NO — ANTHROPIC_API_KEY missing'}")
        return

    status = run_interactive(
        draft_text, args.lesson_id, args.topic, args.phase, args.doc,
        api_key, skip_concept=args.skip_concept
    )
    sys.exit(0 if status in ("done", "partial") else 1)


if __name__ == "__main__":
    main()
