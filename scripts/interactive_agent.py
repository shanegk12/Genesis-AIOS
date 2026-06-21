"""
Genesis K-12 Interactive Agent

Generates 4 self-contained HTML interactives per lesson:
  1. flashcards.html — flip-card vocab deck (term → definition)
  2. accordion.html  — collapsible Part sections for lesson navigation
  3. ocv.html        — Objective / Constraint / Variable tab widget
  4. concept.html    — Claude API (claude-opus-4-7) custom JS activity

All outputs are fully self-contained HTML (no external dependencies).
Saved to: scripts/interactives/[lesson-id]/
Manifest updated with interactive_status + interactive_files

Usage:
  python interactive_agent.py --lesson-id C-030
  python interactive_agent.py --lesson-id C-030 --skip-concept  # no Claude API
  python interactive_agent.py --draft-file path/to/draft.txt --lesson-id C-030 \\
      --topic "Procurement" --phase "Procurement" --doc creationeering
  python interactive_agent.py --lesson-id C-030 --dry-run
"""

import argparse, json, os, re, sys, urllib.request, urllib.error

MANIFEST_PATH    = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
INTERACTIVES_DIR = os.path.join(os.path.dirname(__file__), "interactives")

CLAUDE_MODEL = "claude-sonnet-4-6"
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

def clean_cell(s):
    s = s.strip()
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'\*(.+?)\*',     r'\1', s)
    s = re.sub(r'`(.+?)`',       r'\1', s)
    return s.strip()


def parse_vocab(draft):
    """Extract (term, definition) pairs from Key Vocabulary section."""
    section_end = r'(?:The Beginning|Learning Objectives|Engineering Journal|Technical Documentation|Summary of Key Concepts|Works Cited|Part \d)'
    match = re.search(
        r'Key Vocabulary\s*\n(.*?)(?=\n#{0,6}\s*' + section_end + r')',
        draft, re.DOTALL | re.IGNORECASE
    )
    section = match.group(1) if match else draft[:3000]

    # Markdown table rows
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

    # "Term: Definition" fallback
    for line in section.splitlines():
        line = line.strip()
        if ':' in line and len(line) < 300:
            parts = line.split(':', 1)
            term, defn = parts[0].strip(), parts[1].strip()
            if term and defn and len(term) < 60 and not term.startswith('http'):
                vocab.append((term, defn))
    return vocab[:12]


def parse_parts(draft):
    """
    Extract (title, content) tuples for each Part section.
    Handles both plain text ("Part 1: ...") and markdown ("### Part 1: ...").
    """
    pattern = re.compile(
        r'(?:^|\n)#{0,6}\s*(Part \d+[:\s][^\n]+)\n(.*?)(?=\n#{0,6}\s*Part \d+|\n#{0,6}\s*(?:Engineering Journal|Technical Documentation|Summary of Key Concepts|Works Cited)|\Z)',
        re.DOTALL | re.IGNORECASE
    )
    parts = []
    for m in pattern.finditer(draft):
        title   = clean_cell(m.group(1)).strip()
        content = m.group(2).strip()
        # Strip markdown from content
        content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)
        content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
        content = re.sub(r'\*(.+?)\*',     r'\1', content)
        content = re.sub(r'^[*\-]\s+',     '',    content, flags=re.MULTILINE)
        if len(content.strip()) > 50:
            parts.append((title, content.strip()))
    return parts


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
    start = 0
    for marker in ['The Beginning', 'Part 1', 'Part One']:
        idx = draft.find(marker)
        if idx > 0:
            start = idx
            break
    return draft[start:start + chars].strip()


# ── HTML GENERATORS ───────────────────────────────────────────────────────────

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_flashcards_html(vocab, topic):
    if not vocab:
        return None

    cards_js = json.dumps([{"term": esc(t), "def": esc(d)} for t, d in vocab])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vocabulary Flashcards</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f7f9fc;
          padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }}
  h2 {{ color: {NAVY}; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.06em;
       margin-bottom: 18px; border-bottom: 2px solid {GOLD}; padding-bottom: 6px; }}
  .counter {{ font-size: 0.82rem; color: #64748b; margin-bottom: 14px; }}
  .scene {{ width: 100%; max-width: 520px; height: 200px; perspective: 1000px; cursor: pointer; }}
  .card  {{ width: 100%; height: 100%; position: relative;
            transform-style: preserve-3d; transition: transform 0.45s ease; }}
  .card.flipped {{ transform: rotateY(180deg); }}
  .face  {{ position: absolute; width: 100%; height: 100%; backface-visibility: hidden;
            border-radius: 14px; display: flex; flex-direction: column;
            align-items: center; justify-content: center; padding: 24px; text-align: center; }}
  .front {{ background: {NAVY}; color: #fff; box-shadow: 0 4px 16px rgba(30,58,95,0.25); }}
  .back  {{ background: {GOLD}; color: {NAVY}; transform: rotateY(180deg);
            box-shadow: 0 4px 16px rgba(201,162,39,0.3); }}
  .face-label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.08em;
                 opacity: 0.6; margin-bottom: 10px; }}
  .face-text  {{ font-size: 1.1rem; font-weight: 700; line-height: 1.4; }}
  .back .face-text {{ font-size: 0.95rem; font-weight: 400; }}
  .hint {{ font-size: 0.75rem; color: #94a3b8; margin-top: 12px; }}
  .nav {{ display: flex; gap: 12px; margin-top: 18px; align-items: center; }}
  .btn {{ background: {NAVY}; color: #fff; border: none; border-radius: 8px;
          padding: 10px 22px; font-size: 0.88rem; font-weight: 600;
          cursor: pointer; transition: background 0.15s; }}
  .btn:hover {{ background: #152b47; }}
  .btn:disabled {{ background: #cbd5e1; cursor: default; }}
  .progress {{ display: flex; gap: 5px; margin-top: 14px; flex-wrap: wrap; justify-content: center; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #dde3ee; transition: background 0.2s; }}
  .dot.seen {{ background: {GOLD}; }}
  .dot.current {{ background: {NAVY}; }}
</style>
</head>
<body>
<h2>Vocabulary Flashcards</h2>
<div class="counter" id="counter"></div>
<div class="scene" onclick="flip()">
  <div class="card" id="card">
    <div class="face front">
      <div class="face-label">Term</div>
      <div class="face-text" id="front-text"></div>
    </div>
    <div class="face back">
      <div class="face-label">Definition</div>
      <div class="face-text" id="back-text"></div>
    </div>
  </div>
</div>
<div class="hint" id="hint">Click card to reveal definition</div>
<div class="nav">
  <button class="btn" id="prev-btn" onclick="go(-1)">&#8592; Prev</button>
  <button class="btn" id="next-btn" onclick="go(1)">Next &#8594;</button>
</div>
<div class="progress" id="progress"></div>
<script>
const cards = {cards_js};
let cur = 0, flipped = false, seen = new Set();

function render() {{
  const c = cards[cur];
  document.getElementById('front-text').textContent = c.term;
  document.getElementById('back-text').textContent  = c.def;
  document.getElementById('counter').textContent    = `Card ${{cur + 1}} of ${{cards.length}}`;
  document.getElementById('prev-btn').disabled = cur === 0;
  document.getElementById('next-btn').disabled = cur === cards.length - 1;
  document.getElementById('hint').textContent = flipped ? 'Click to flip back' : 'Click card to reveal definition';
  renderDots();
}}

function renderDots() {{
  const p = document.getElementById('progress');
  p.innerHTML = cards.map((_, i) => {{
    let cls = 'dot';
    if (i === cur) cls += ' current';
    else if (seen.has(i)) cls += ' seen';
    return `<div class="${{cls}}"></div>`;
  }}).join('');
}}

function flip() {{
  flipped = !flipped;
  document.getElementById('card').classList.toggle('flipped', flipped);
  if (flipped) seen.add(cur);
  document.getElementById('hint').textContent = flipped ? 'Click to flip back' : 'Click card to reveal definition';
  renderDots();
}}

function go(dir) {{
  flipped = false;
  document.getElementById('card').classList.remove('flipped');
  cur = Math.max(0, Math.min(cards.length - 1, cur + dir));
  render();
}}

render();
</script>
</body>
</html>"""


def generate_accordion_html(parts, topic):
    if not parts:
        return None

    items = ""
    for i, (title, content) in enumerate(parts):
        open_attr  = ' open' if i == 0 else ''
        paragraphs = "".join(
            f"<p>{esc(p.strip())}</p>" for p in content.split("\n\n") if p.strip()
        )
        items += f"""
  <details class="panel"{open_attr}>
    <summary>{esc(title)}</summary>
    <div class="panel-body">{paragraphs}</div>
  </details>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lesson Sections</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f7f9fc; padding: 20px; }}
  h2 {{ color: {NAVY}; font-size: 1rem; text-transform: uppercase; letter-spacing: 0.06em;
       margin-bottom: 16px; border-bottom: 2px solid {GOLD}; padding-bottom: 6px;
       display: inline-block; }}
  .panel {{ background: #fff; border: 1px solid #dce4ee; border-radius: 10px;
            margin-bottom: 10px; overflow: hidden; }}
  .panel summary {{
    padding: 14px 18px; font-weight: 700; color: {NAVY}; font-size: 0.92rem;
    cursor: pointer; list-style: none; display: flex; align-items: center;
    justify-content: space-between; user-select: none;
    transition: background 0.15s;
  }}
  .panel summary:hover {{ background: #f0f4fa; }}
  .panel summary::after {{ content: '+'; font-size: 1.3rem; color: {GOLD};
                            font-weight: 900; transition: transform 0.2s; }}
  .panel[open] summary::after {{ content: '−'; }}
  .panel[open] summary {{ background: {NAVY}; color: #fff; border-radius: 10px 10px 0 0; }}
  .panel[open] summary::after {{ color: {GOLD}; }}
  .panel-body {{ padding: 18px 20px; border-top: 1px solid #dce4ee; }}
  .panel-body p {{ color: #374151; font-size: 0.9rem; line-height: 1.65;
                   margin-bottom: 12px; }}
  .panel-body p:last-child {{ margin-bottom: 0; }}
</style>
</head>
<body>
<h2>Lesson Sections</h2>
<div id="accordion">{items}
</div>
</body>
</html>"""


def generate_ocv_html(ocv, topic):
    objective  = ocv.get('objective',  'Define what success looks like — the measurable goal of your design.')
    constraint = ocv.get('constraint', 'Identify fixed limits: budget, materials, time, size, or safety requirements.')
    variable   = ocv.get('variable',   'Identify what you can adjust to move closer to your objective within the constraints.')

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
       text-transform: uppercase; letter-spacing: 0.06em;
       border-bottom: 2px solid {GOLD}; padding-bottom: 6px; display: inline-block; }}
  .tabs {{ display: flex; gap: 4px; margin-bottom: 0; }}
  .tab  {{ padding: 10px 22px; cursor: pointer; font-weight: 600; color: #666;
           font-size: 0.88rem; border-radius: 6px 6px 0 0; border: 1px solid #dce4ee;
           border-bottom: none; background: #eef2f7; transition: all 0.15s; }}
  .tab.active  {{ background: {NAVY}; color: #fff; border-color: {NAVY}; }}
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
              border-radius: 6px; font-size: 0.85rem; resize: vertical;
              font-family: inherit; min-height: 60px; color: #2d3748; }}
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
- GK12 color palette: navy {navy}, gold {gold}, white #ffffff, light gray #f7f9fc
- Faith reference optional and brief if included — do not force it

Good interactive types for engineering topics:
- Drag-and-drop sorting or matching game
- Step-through simulation with "what happens next?" prompts
- Trade-off slider (adjust one variable, see cost/benefit update live)
- Quiz with immediate feedback and explanation
- Build-your-own flowchart or decision tree

Lesson excerpt for context:
{{excerpt}}

Output ONLY the complete HTML file from <!DOCTYPE html> to </html>. No explanation, no code fences."""


def call_claude_for_interactive(api_key, topic, phase, doc, excerpt):
    course_label = "Creationeering" if doc == "creationeering" else "Mousetrap Build"
    prompt = CONCEPT_PROMPT.format(
        course=course_label, topic=topic, phase=phase,
        navy=NAVY, gold=GOLD
    ).replace("{excerpt}", excerpt)

    payload = json.dumps({
        "model":      CLAUDE_MODEL,
        "max_tokens": 8192,
        "messages":   [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        CLAUDE_URL, data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["content"][0]["text"].strip()
        text = re.sub(r'^```html\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^```\s*',     '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$',     '', text.strip())
        return text if text.startswith('<!') else None
    except urllib.error.HTTPError as e:
        print(f"  Claude API error {e.code}: {e.read().decode('utf-8')[:300]}")
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

    files  = {}
    errors = []

    # 1. Flashcards
    vocab = parse_vocab(draft_text)
    if vocab:
        html = generate_flashcards_html(vocab, topic)
        path = os.path.join(out_dir, "flashcards.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        files["flashcards"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
        print(f"  Flashcards: {len(vocab)} cards -> {path}")
    else:
        print(f"  Flashcards: no vocab parsed — skipping")
        errors.append("vocab_parse_failed")

    # 2. Accordion (Part sections)
    parts = parse_parts(draft_text)
    if parts:
        html = generate_accordion_html(parts, topic)
        path = os.path.join(out_dir, "accordion.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        files["accordion"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
        print(f"  Accordion:  {len(parts)} sections -> {path}")
    else:
        print(f"  Accordion:  no Part sections found — skipping")
        errors.append("parts_parse_failed")

    # 3. OCV tab widget
    ocv     = parse_ocv(draft_text)
    ocv_html = generate_ocv_html(ocv, topic)
    path = os.path.join(out_dir, "ocv.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ocv_html)
    files["ocv"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
    found = [k for k in ('objective', 'constraint', 'variable') if k in ocv]
    print(f"  OCV:        {found or 'defaults'} -> {path}")

    # 4. Concept interactive via Claude API
    if not skip_concept:
        if not api_key:
            print(f"  Concept:    SKIPPED — ANTHROPIC_API_KEY not set")
            errors.append("no_api_key")
        else:
            excerpt = get_lesson_excerpt(draft_text)
            print(f"  Concept:    calling Claude ({CLAUDE_MODEL})...")
            html = call_claude_for_interactive(api_key, topic, phase, doc, excerpt)
            if html:
                path = os.path.join(out_dir, "concept.html")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                files["concept"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
                print(f"  Concept:    {len(html):,} chars -> {path}")
            else:
                print(f"  Concept:    Claude returned no valid HTML")
                errors.append("concept_failed")

    status = "done" if not errors else ("partial" if files else "failed")
    update_manifest(lesson_id, files, status)
    print(f"  Status:     {status}  ({len(files)} files written)")
    return status


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Interactive Agent")
    parser.add_argument("--draft-file",   help="Path to draft text file")
    parser.add_argument("--lesson-id",    required=True)
    parser.add_argument("--topic",        help="Lesson topic")
    parser.add_argument("--phase",        help="Creationeering phase")
    parser.add_argument("--doc",          choices=["creationeering", "mousetrap"])
    parser.add_argument("--skip-concept", action="store_true",
                        help="Skip Claude API (flashcards + accordion + OCV only)")
    parser.add_argument("--dry-run",      action="store_true")
    args = parser.parse_args()

    env     = load_env()
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

    # Fill from manifest if not provided
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

    # Load draft
    if args.draft_file:
        if not os.path.exists(args.draft_file):
            print(f"Draft file not found: {args.draft_file}")
            sys.exit(1)
        with open(args.draft_file, encoding="utf-8") as f:
            draft_text = f.read()
    else:
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
                print(f"Tab content too short. Check the Google Doc.")
                sys.exit(1)
            print(f"Read {len(draft_text):,} chars from Google Doc")
        except Exception as e:
            print(f"Could not read from Google Doc: {e}")
            sys.exit(1)

    print(f"\nInteractives: [{args.lesson_id}] {args.topic}")
    print(f"  Course: {args.doc}  Phase: {args.phase}")

    if args.dry_run:
        vocab = parse_vocab(draft_text)
        parts = parse_parts(draft_text)
        ocv   = parse_ocv(draft_text)
        print(f"  Flashcards: {len(vocab)} vocab terms")
        print(f"  Accordion:  {len(parts)} Part sections")
        print(f"  OCV:        {list(ocv.keys()) or 'defaults'}")
        if not args.skip_concept:
            print(f"  Concept:    {'Claude API ready' if api_key else 'NO KEY — ANTHROPIC_API_KEY missing'}")
        return

    status = run_interactive(
        draft_text, args.lesson_id, args.topic, args.phase, args.doc,
        api_key, skip_concept=args.skip_concept
    )
    sys.exit(0 if status in ("done", "partial") else 1)


if __name__ == "__main__":
    main()
