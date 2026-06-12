"""
rewrite_lessons_gdoc.py

Rewrites pipeline-generated lesson blocks using Google Doc tabs as the
canonical source, with QC'd first-unit lessons (C-001–C-019) as the style
reference for tone, structure, and block usage.

Approach per lesson:
  1. Find the matching tab in the Google Doc by lesson ID / title mapping
  2. Extract the full text of that tab
  3. Fetch 3 exemplar QC'd lessons from the platform (style reference)
  4. Call Claude to generate Block[] JSON in the same voice and structure
  5. Quality-check output (min blocks, no "Part N:", no "Junior Creationeers")
  6. Save locally and PATCH the platform

Target lessons: C-020 through C-089, M-001 through M-070
Preserved:      C-001–C-019 (QC'd from screenshots), M-002–M-006 (screenshot-imported)

Usage:
  python scripts/rewrite_lessons_gdoc.py --list-tabs           # show tab mapping
  python scripts/rewrite_lessons_gdoc.py --dry-run             # preview
  python scripts/rewrite_lessons_gdoc.py --save --lesson C-025 # single lesson
  python scripts/rewrite_lessons_gdoc.py --save --course C     # all Creationeering C-020+
  python scripts/rewrite_lessons_gdoc.py --save --course M     # all Mousetrap
  python scripts/rewrite_lessons_gdoc.py --save                # everything
"""

import argparse, json, os, re, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from _gws_auth import get_session

# ── Config ────────────────────────────────────────────────────────────────────

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
DOCS_API_BASE = "https://docs.googleapis.com/v1/documents"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"
LOG_PATH      = Path(__file__).parent / "rewrite_gdoc_log.json"
OUTPUT_DIR    = Path(__file__).parent / "rewritten_lessons"

CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"

# Lessons NOT to rewrite — human-checked or screenshot-imported
# Creationeering: first unit C-001–C-019 (QC'd from LW screenshots)
# Mousetrap: all lessons with a screenshot folder in screenshots/Mousetrap/
PRESERVE = (
    {f"C-{i:03d}" for i in range(1, 20)}
    | {"M-002", "M-003", "M-004", "M-005", "M-006",   # screenshot-imported, batch 1
       "M-011", "M-012", "M-014", "M-018", "M-019"}    # screenshot-imported, batch 2
)

# Exemplar lessons — first 5 QC'd lessons as the canonical style reference
STYLE_EXEMPLARS = ["C-001", "C-002", "C-003", "C-004", "C-005"]


def load_env() -> dict:
    env = {}
    for name in [".env", ".env.local"]:
        p = Path(__file__).parent.parent / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
    return env


def _get_platform_key() -> str:
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
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


# ── Google Docs helpers ───────────────────────────────────────────────────────

def list_tabs(session, doc_id: str) -> list[dict]:
    """Return list of {tabId, title, index} for all tabs in a document."""
    resp = session.get(
        f"{DOCS_API_BASE}/{doc_id}",
        params={"includeTabsContent": "false", "fields": "tabs.tabProperties"},
    )
    resp.raise_for_status()
    data = resp.json()
    tabs = []
    for tab in data.get("tabs", []):
        props = tab.get("tabProperties", {})
        tabs.append({
            "tabId":    props.get("tabId", ""),
            "title":    props.get("title", ""),
            "index":    props.get("index", 0),
        })
    return sorted(tabs, key=lambda t: t["index"])


def get_tab_text(session, doc_id: str, tab_id: str) -> str:
    """Fetch one tab's content and return as plain text."""
    resp = session.get(
        f"{DOCS_API_BASE}/{doc_id}",
        params={"includeTabsContent": "true"},
    )
    resp.raise_for_status()
    data = resp.json()

    for tab in data.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("tabId") != tab_id:
            continue
        doc_tab = tab.get("documentTab", {})
        content = doc_tab.get("body", {}).get("content", [])
        return _extract_text(content)

    return ""


def _extract_text(content: list) -> str:
    """Recursively extract plain text from a Google Docs content array."""
    lines = []
    for element in content:
        if "paragraph" in element:
            para = element["paragraph"]
            parts = []
            for el in para.get("elements", []):
                tr = el.get("textRun", {})
                parts.append(tr.get("content", ""))
            line = "".join(parts)
            if line.strip():
                lines.append(line.rstrip("\n"))
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    cell_text = _extract_text(cell.get("content", []))
                    if cell_text.strip():
                        lines.append(cell_text)
        elif "sectionBreak" in element:
            lines.append("")
    return "\n".join(lines)


_SKIP_TABS = {"syllabus", "syllabus and instructional guide", "overview", "table of contents",
               "toc", "introduction", "course overview", "instructor notes"}

_STRIP_PREFIXES = re.compile(
    r"^(?:lesson|build \d+|business activity|activity|unit \d+|module \d+)\s*:\s*",
    re.IGNORECASE,
)

def _normalize(s: str) -> str:
    """Lowercase, strip punctuation and common prefixes for fuzzy comparison."""
    s = _STRIP_PREFIXES.sub("", s).lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def build_tab_map(session, env: dict) -> dict[str, tuple[str, str]]:
    """
    Return {lesson_id: (doc_id, tab_id)} by matching tab titles to lesson topics.

    Creationeering tabs: descriptive titles ("Entrepreneurship", "What is Synthesis?")
    Mousetrap tabs: prefixed ("Build 1: Little Moe Prototype Car", "Lesson: Friction")

    Matching priority:
    1. Exact lesson ID in tab title ("C-025")
    2. Digit-only ("25" → "C-025")
    3. Normalized title vs normalized lesson topic (fuzzy)
    4. Normalized title vs normalized lesson title

    Also loads a manual override file tab_map_override.json if present.
    """
    c_doc = env.get("GOOGLE_DOC_CREATIONEERING_LESSON_BOOK", "")
    m_doc = env.get("GOOGLE_DOC_MOUSETRAP_COURSE", "")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lessons = manifest["lessons"]

    # Build lookup tables for matching
    by_id     = {l["id"]: l for l in lessons}
    by_topic  = {_normalize(l.get("topic", "") or ""): l["id"] for l in lessons if l.get("topic")}
    by_title  = {_normalize(l.get("title", "") or ""): l["id"] for l in lessons if l.get("title")}

    tab_map: dict[str, tuple[str, str]] = {}
    unmatched: list[str] = []

    for doc_id, prefix in [(c_doc, "C"), (m_doc, "M")]:
        if not doc_id:
            continue
        try:
            tabs = list_tabs(session, doc_id)
        except Exception as e:
            print(f"  [WARN] Could not list tabs for doc {doc_id}: {e}")
            continue

        for tab in tabs:
            raw_title = tab["title"].strip()
            tab_id    = tab["tabId"]

            # Skip known non-lesson tabs
            if _normalize(raw_title) in _SKIP_TABS or raw_title.lower().startswith("syllabus"):
                continue

            # Strategy 1: exact lesson ID ("C-025")
            if raw_title.upper() in by_id:
                tab_map[raw_title.upper()] = (doc_id, tab_id)
                continue

            # Strategy 2: digit-only ("25" → "C-025")
            if raw_title.strip().isdigit():
                lid = f"{prefix}-{int(raw_title):03d}"
                if lid in by_id:
                    tab_map[lid] = (doc_id, tab_id)
                    continue

            # Strategy 3: normalized title vs topic
            norm = _normalize(raw_title)
            lid = by_topic.get(norm) or by_title.get(norm)
            if lid:
                tab_map[lid] = (doc_id, tab_id)
                continue

            # Strategy 4: partial match — tab title is substring of topic or vice versa
            matched = False
            for norm_topic, lid in by_topic.items():
                if norm and (norm in norm_topic or norm_topic in norm):
                    tab_map[lid] = (doc_id, tab_id)
                    matched = True
                    break
            if matched:
                continue

            unmatched.append(f"{prefix}: {raw_title!r}")

    if unmatched:
        print(f"  [INFO] {len(unmatched)} tabs could not be auto-matched. "
              f"Create tab_map_override.json to manually assign them.")
        unmatched_path = Path(__file__).parent / "tab_map_unmatched.txt"
        unmatched_path.write_text("\n".join(unmatched), encoding="utf-8")

    # Apply manual overrides if present
    override_path = Path(__file__).parent / "tab_map_override.json"
    if override_path.exists():
        overrides = json.loads(override_path.read_text(encoding="utf-8"))
        for lesson_id, tab_info in overrides.items():
            tab_map[lesson_id] = (tab_info["doc_id"], tab_info["tab_id"])
        print(f"  Applied {len(overrides)} manual override(s) from tab_map_override.json")

    return tab_map


# ── Platform API ──────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str, key: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  Fetch error {lesson_id}: {e}")
        return None


def patch_lesson(lesson_id: str, blocks: list, key: str) -> bool:
    """PATCH lesson blocks, preserving any existing embed blocks (interactives)."""
    # Fetch existing blocks to rescue embed blocks before overwriting
    existing = fetch_lesson(lesson_id, key)
    if existing:
        existing_embeds = [b for b in existing.get("blocks", []) if b.get("type") == "embed"]
        if existing_embeds:
            # Remove any embed blocks already in new blocks (avoid duplication)
            blocks = [b for b in blocks if b.get("type") != "embed"] + existing_embeds

    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


def blocks_to_reference(blocks: list, max_chars: int = 3000) -> str:
    """Return a faithful JSON representation of the first N blocks for style reference.
    Uses the actual Firestore block structure so Claude can mirror it exactly."""
    # Trim blocks to fit within max_chars while keeping complete blocks
    result = []
    total = 0
    for b in blocks:
        serialized = json.dumps(b, ensure_ascii=False)
        if total + len(serialized) > max_chars:
            break
        result.append(b)
        total += len(serialized)
    return json.dumps(result, indent=2, ensure_ascii=False)


# ── Claude generation ─────────────────────────────────────────────────────────

BLOCK_SCHEMA = """
REQUIRED JSON SCHEMA — every block MUST use this exact structure:

text:     {"id":"abc","type":"text","data":{"html":"<h2>Title</h2><p>Body.</p>"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"doc-rewrite"}}
callout:  {"id":"abc","type":"callout","data":{"variant":"tip","html":"<p>Content.</p>"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"doc-rewrite"}}
          variant options: "tip" | "info" | "warning" | "biblical"
vocab:    {"id":"abc","type":"vocab","data":{"items":[{"term":"Word","definition":"Meaning"}],"columns":1},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"doc-rewrite"}}
image:    {"id":"abc","type":"image","data":{"src":"","width":"100%","caption":"What this shows"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"doc-rewrite"}}
divider:  {"id":"abc","type":"divider","data":{"style":"solid"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"doc-rewrite"}}
accordion:{"id":"abc","type":"accordion","data":{"title":"Section","html":"<p>Content.</p>","openByDefault":false},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"doc-rewrite"}}

CRITICAL: Use "data" with the fields shown above. NEVER use "content" or "html" at the top level.
Every block meta MUST include "qcNote":"doc-rewrite" so reviewers can identify pipeline-generated blocks.

BLOCK TYPE USAGE RULES — READ CAREFULLY:

text: PRIMARY block type. Use for all lesson content — paragraphs, headings, lists.
      Use <h2> for major sections, <h3> for sub-sections, <p> for body, <ul><li> for lists.

callout: Use SPARINGLY — max 3 per lesson. Only when content genuinely stands apart:
      "tip" = actionable study tip or engineering insight
      "info" = important context students must not miss
      "warning" = common mistake or misconception
      "biblical" = direct scripture quote or faith reflection

vocab: Exactly ONE per lesson, placed after the intro section.
       Only include terms actually used and defined in the lesson.

image: Leave src empty — images are generated separately. Write a specific, descriptive caption
       that tells exactly what the image should show. Max 3 per lesson.

divider: Between MAJOR sections only. Max 3–4 per lesson.

accordion: Use ONLY when content is genuinely supplementary/optional — a student could skip it
           without losing the lesson's core. NOT for primary content. Max 1–2 per lesson.

accordion-grid: *** ALMOST NEVER USE THIS ***
           ONLY appropriate for a "Check Your Understanding" section with 4–6 discrete
           Q&A pairs at the END of a lesson. Do not use it for content delivery, vocabulary,
           or summarizing concepts. If in doubt, use a text block with a <ul> list instead.

tabs: Do not use unless the doc explicitly has side-by-side comparison content.
"""

REWRITE_SYSTEM = """You are writing lesson content for Genesis K-12 Academy — \
a faith-based middle school engineering curriculum for grades 6-8. \
Your job is to transform raw Google Doc lesson content into a structured JSON \
Block array that matches the style, tone, and structure of the provided example lessons.

Voice and tone rules:
- Address students directly: "you", "your design", "as you build" — never "Junior Creationeers"
- Warm, encouraging, clear — like a knowledgeable mentor explaining to a curious 12-year-old
- Faith integration woven naturally into content — not as standalone labeled sections
- Engineering analogies woven into explanations — not as "Engineering analogy:" labels
- No "Part N:" section structure — use descriptive h2/h3 headings instead
- Sentence length: mix short punchy sentences with longer explanatory ones
- Grade 6-8 reading level; define jargon when introduced

Block structure rules (match the examples exactly):
- text blocks: h2 for major sections, h3 for sub-sections, <p> for paragraphs, <ul>/<li> for lists
- callout blocks: "tip" for study tips / actionable insights, "info" for important context,
  "biblical" for scripture or faith reflection, "warning" for common mistakes
- vocab block: one per lesson, placed after the intro section
- image blocks: place where a diagram or photo would help; leave src empty
- accordion: only for genuinely optional/supplementary content — max 1–2 per lesson
- divider: between major sections

Quality requirements:
- Minimum 15 blocks for a full lesson
- Must include: at least one text block, one vocab block (if terms exist), one callout block
- No markdown in HTML values — only HTML tags
- All block IDs should be short random alphanumeric strings (8-10 chars)
- Return ONLY valid JSON: a bare array [...] with no explanation"""


def is_activity_lesson(title: str) -> bool:
    return bool(re.match(r"^(BA|Business Activity|Activity)\s*:", title.strip(), re.IGNORECASE))


ACTIVITY_BLOCK_SCHEMA = """
REQUIRED JSON SCHEMA — every block MUST use this exact structure:

text:          {"id":"abc","type":"text","data":{"html":"<h2>Title</h2><p>Body.</p>"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"activity-rewrite","activityType":"business-activity"}}
callout:       {"id":"abc","type":"callout","data":{"variant":"tip","html":"<p>Content.</p>"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"activity-rewrite","activityType":"business-activity"}}
               variant options: "tip" | "info" | "warning" | "biblical"
accordion-grid:{"id":"abc","type":"accordion-grid","data":{"columns":2,"items":[{"title":"Role Name","html":"<p>Responsibility description.</p>"}]},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"activity-rewrite","activityType":"business-activity"}}
image:         {"id":"abc","type":"image","data":{"src":"","width":"100%","caption":"What this shows"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"activity-rewrite","activityType":"business-activity"}}
divider:       {"id":"abc","type":"divider","data":{"style":"solid"},"meta":{"spacing":"md","qcStatus":"pending","qcNote":"activity-rewrite","activityType":"business-activity"}}

CRITICAL: Every block meta MUST include:
  "qcNote": "activity-rewrite"
  "activityType": "business-activity"
These flags allow the gradebook and admin tools to identify activity lessons.

BLOCK TYPE RULES FOR ACTIVITIES:

text: Use for all instructional prose, objectives, and step-by-step directions.
      Fill-in-the-blank fields become: <p>[Student fills in: brief description of what goes here]</p>
      Example: Company Name blank → <p>[Student fills in: your company name]</p>

callout: Use for:
      "tip" = helpful hints for completing the activity
      "info" = important context or definitions the student needs
      "warning" = common mistakes to avoid
      "biblical" = scripture or stewardship connection
      Max 3 per activity.

accordion-grid: PRIMARY block for tables with role/responsibility pairs, comparison charts,
      or any multi-column structured data from the original doc.
      Each row becomes one item: {"title": "Role or Label", "html": "<p>Description or [Student fills in: ...]</p>"}
      Set columns:2 for two-column tables, columns:1 for single-column lists.

image: Leave src empty. Only include if the activity explicitly references a diagram or example.

divider: Between major activity sections only.
"""

ACTIVITY_REWRITE_SYSTEM = """You are converting a student activity worksheet for Genesis K-12 Academy \
— a faith-based middle school engineering curriculum for grades 6-8.

Your job is to transform a Google Doc activity worksheet into a structured JSON Block array \
that preserves the instructional intent while making it clear and engaging for students.

Activity conversion rules:
- Preserve the STRUCTURE of the activity — objectives, parts, steps, tables
- Address students directly: "you", "your team", "your design" — warm mentor tone
- Tables with roles/columns → accordion-grid blocks (each row = one item)
- Fill-in-the-blank fields → text blocks with [Student fills in: description] placeholders
- Objectives → callout block with variant "info" at the top
- Faith or stewardship connections → callout block with variant "biblical"
- Keep instructions clear and step-by-step — students act on these during class
- Grade 6-8 reading level; brief definitions for any business/engineering terms used

Every block must include "activityType": "business-activity" in its meta — this wires the lesson \
into the gradebook and autograding system.

Return ONLY valid JSON — a bare array [...]. No explanation, no markdown."""


def build_activity_prompt(lesson_id: str, title: str, raw_text: str) -> str:
    return ACTIVITY_BLOCK_SCHEMA + f"""

Convert the activity worksheet below into a structured Block[] array.

LESSON ID: {lesson_id}
ACTIVITY TITLE: {title}

RAW CONTENT FROM GOOGLE DOC:
{raw_text[:4000]}

Rules:
- Minimum 8 blocks (activities are shorter than narrative lessons)
- Every table → accordion-grid block
- Every fill-in field → [Student fills in: ...] placeholder in a text block
- Objective section → callout "info" block at top
- Return ONLY valid JSON — a bare array [...]. No explanation, no markdown."""


def build_rewrite_prompt(lesson_id: str, title: str, raw_text: str,
                          exemplar_summaries: list[tuple[str, str]]) -> str:
    examples_section = "\n\n".join(
        f"EXAMPLE {lid} ({etitle}):\n{summary}"
        for lid, etitle, summary in exemplar_summaries
    )
    return BLOCK_SCHEMA + f"""

Here are {len(exemplar_summaries)} reference lessons pulled directly from the live platform (Firestore).
These are the QC-approved first unit lessons — match their style, tone, block types, and structure exactly.

{examples_section}

---

Now rewrite the lesson below using the SAME block structure, tone, and voice as the reference lessons above.
The reference lessons are the gold standard — mirror how they open sections, weave in faith, integrate analogies, and vary block types.

LESSON ID: {lesson_id}
LESSON TITLE: {title}

RAW CONTENT FROM GOOGLE DOC:
{raw_text[:4000]}

Generate a complete Block[] array for this lesson. Follow all rules from your system prompt.
Return ONLY valid JSON — a bare array [...]. No explanation, no markdown."""


def call_claude(system: str, user: str, api_key: str) -> str | None:
    payload = json.dumps({
        "model":      CLAUDE_MODEL,
        "max_tokens": 8192,
        "system":     system,
        "messages":   [{"role": "user", "content": user}],
    }).encode("utf-8")

    for attempt in range(3):
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
            return data["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            code = e.code
            body = e.read().decode("utf-8")[:300]
            if code in (429, 529) and attempt < 2:
                wait = 60 * (attempt + 1)
                print(f"  Claude rate limit ({code}) — waiting {wait}s before retry {attempt + 2}/3...")
                time.sleep(wait)
                continue
            print(f"  Claude API error {code}: {body}")
            return None
        except Exception as e:
            print(f"  Claude API error: {e}")
            return None
    return None


# ── Quality validation ────────────────────────────────────────────────────────

def validate_blocks(blocks: list) -> tuple[bool, str]:
    """Basic sanity checks on generated blocks. Returns (ok, reason)."""
    if len(blocks) < 10:
        return False, f"only {len(blocks)} blocks (minimum 10)"

    has_text = any(b.get("type") == "text" for b in blocks)
    if not has_text:
        return False, "no text blocks"

    all_text = " ".join(
        re.sub(r"<[^>]+>", " ", b.get("data", {}).get("html", ""))
        for b in blocks if b.get("type") == "text"
    )

    if re.search(r"\bJunior Creatione\w*", all_text, re.IGNORECASE):
        return False, "contains 'Junior Creationeers' text"

    if re.search(r"\bPart\s+\d+\s*:", all_text, re.IGNORECASE):
        return False, "contains 'Part N:' structure"

    return True, "ok"


def validate_activity_blocks(blocks: list) -> tuple[bool, str]:
    """Relaxed validation for activity-mode lessons."""
    if len(blocks) < 8:
        return False, f"only {len(blocks)} blocks (activity minimum 8)"

    has_text = any(b.get("type") in ("text", "accordion-grid") for b in blocks)
    if not has_text:
        return False, "no text or accordion-grid blocks"

    for b in blocks:
        if b.get("meta", {}).get("activityType") != "business-activity":
            return False, "missing activityType meta on block"

    return True, "ok"


def _fix_encoding(s: str) -> str:
    """Fix double-encoded UTF-8 (e.g. ™ showing as â„¢)."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except Exception:
        return s


def _normalize_block(b: dict) -> dict:
    """Normalize blocks Claude sometimes returns with 'content' instead of data.html."""
    btype = b.get("type", "")
    if "data" not in b or not b["data"]:
        raw = b.pop("content", "") or b.pop("html", "") or ""
        raw = _fix_encoding(raw) if raw else raw
        if btype == "text":
            b["data"] = {"html": raw}
        elif btype == "callout":
            b["data"] = {"variant": b.pop("variant", "info"), "html": raw}
        elif btype == "image":
            b["data"] = {"src": b.pop("src", ""), "width": "100%", "caption": b.pop("caption", raw)}
        elif btype == "divider":
            b["data"] = {"style": "solid"}
        elif btype == "vocab":
            items = b.pop("items", b.pop("terms", []))
            b["data"] = {"items": items, "columns": 1}
        elif btype in ("accordion", "accordion-grid"):
            b["data"] = {"title": b.pop("title", ""), "html": raw, "openByDefault": False}
        else:
            b["data"] = {}
    else:
        # Fix encoding in existing data html
        for field in ("html",):
            if field in b["data"] and isinstance(b["data"][field], str):
                b["data"][field] = _fix_encoding(b["data"][field])
    return b


def parse_blocks(raw: str) -> list | None:
    """Extract and parse the JSON array from Claude's response."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw.strip())

    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return None
    try:
        blocks = json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return None

    if not isinstance(blocks, list):
        return None

    import random, string, datetime
    today = datetime.date.today().isoformat()
    result = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        b = _normalize_block(b)
        if not b.get("id"):
            b["id"] = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
        meta = b.get("meta") or {}
        meta.setdefault("spacing", "md")
        meta.setdefault("qcStatus", "pending")
        meta["qcNote"] = f"doc-rewrite {today}"   # stamp every block from this pipeline
        b["meta"] = meta
        result.append(b)

    return result if result else None


# ── Per-lesson orchestration ──────────────────────────────────────────────────

def process_lesson(lesson_id: str, session, tab_map: dict, exemplar_summaries: list,
                   env: dict, key: str, dry_run: bool) -> dict:

    if lesson_id not in tab_map:
        return {"id": lesson_id, "status": "no_tab_match"}

    doc_id, tab_id = tab_map[lesson_id]

    # Fetch lesson metadata for title
    lesson = fetch_lesson(lesson_id, key)
    if not lesson:
        return {"id": lesson_id, "status": "fetch_error"}

    title = lesson.get("title", lesson_id)

    # Get tab content
    print(f"  [{lesson_id}] {title} — reading doc tab...")
    try:
        raw_text = get_tab_text(session, doc_id, tab_id)
    except Exception as e:
        return {"id": lesson_id, "status": "doc_error", "error": str(e)}

    if not raw_text.strip() or len(raw_text) < 200:
        return {"id": lesson_id, "status": "tab_too_short", "chars": len(raw_text)}

    print(f"    Doc content: {len(raw_text)} chars")

    if dry_run:
        return {"id": lesson_id, "status": "dry_run", "doc_chars": len(raw_text)}

    # Generate blocks with Claude
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"id": lesson_id, "status": "no_api_key"}

    activity_mode = is_activity_lesson(title)
    if activity_mode:
        print(f"    Activity lesson detected — using activity mode")

    print(f"    Generating blocks with Claude...")
    if activity_mode:
        user_prompt  = build_activity_prompt(lesson_id, title, raw_text)
        system_prompt = ACTIVITY_REWRITE_SYSTEM
    else:
        user_prompt  = build_rewrite_prompt(lesson_id, title, raw_text, exemplar_summaries)
        system_prompt = REWRITE_SYSTEM

    raw_response = call_claude(system_prompt, user_prompt, api_key)
    if not raw_response:
        return {"id": lesson_id, "status": "generation_failed"}

    blocks = parse_blocks(raw_response)
    if not blocks:
        debug_path = OUTPUT_DIR / f"{lesson_id}_raw.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(raw_response, encoding="utf-8")
        return {"id": lesson_id, "status": "parse_failed", "debug": str(debug_path)}

    ok, reason = (validate_activity_blocks(blocks) if activity_mode else validate_blocks(blocks))
    if not ok:
        print(f"    Quality check FAILED: {reason} — saving for review")
        review_path = OUTPUT_DIR / f"{lesson_id}_review.json"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps(blocks, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"id": lesson_id, "status": "quality_failed", "reason": reason, "review": str(review_path)}

    print(f"    {len(blocks)} blocks generated — quality OK")

    # Save locally
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{lesson_id}.json"
    out_path.write_text(json.dumps(blocks, indent=2, ensure_ascii=False), encoding="utf-8")

    # Patch platform
    patched = patch_lesson(lesson_id, blocks, key)
    status = "done" if patched else "patch_failed"
    print(f"    {'Patched OK' if patched else 'PATCH FAILED'}: {lesson_id}")
    if not patched:
        return {"id": lesson_id, "status": "patch_failed"}

    # ── Step 2: Generate Imagen images for the rewritten lesson ──────────────
    print(f"    Generating images for {lesson_id}...")
    img_result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "qc_generate_lesson_images.py"),
         "--lesson-id", lesson_id],
        capture_output=True, text=True, timeout=300,
    )
    if img_result.returncode == 0:
        print(f"    Images: OK")
    else:
        print(f"    Images: WARN — {img_result.stderr[-200:] if img_result.stderr else 'no output'}")

    # ── Step 3: Vision score + auto-regen any failures ───────────────────────
    print(f"    Scoring images for {lesson_id}...")
    score_result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "qc_image_relevance_check.py"),
         "--report", "--regen", "--lesson", lesson_id],
        capture_output=True, text=True, timeout=180,
    )
    if score_result.returncode == 0:
        # Extract pass/fail counts from output if present
        out = score_result.stdout or ""
        passed = len(re.findall(r"✓", out))
        failed = len(re.findall(r"✗", out))
        print(f"    Vision QC: {passed} passed, {failed} failed (auto-regenned)")
    else:
        print(f"    Vision QC: WARN — {score_result.stderr[-200:] if score_result.stderr else 'no output'}")

    result = {"id": lesson_id, "status": "done", "blocks": len(blocks)}
    if activity_mode:
        result["mode"] = "activity"
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",      action="store_true")
    parser.add_argument("--save",         action="store_true")
    parser.add_argument("--lesson",       help="Single lesson ID")
    parser.add_argument("--course",       choices=["C", "M"])
    parser.add_argument("--list-tabs",    action="store_true", help="Print tab mapping and exit")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Only process lessons that do NOT already have a .json output file")
    args = parser.parse_args()

    if not args.list_tabs and not args.dry_run and not args.save:
        print("Pass --list-tabs, --dry-run, or --save"); sys.exit(1)

    env = load_env()
    key = _get_platform_key()
    session = get_session()

    print("Building tab map from Google Docs...")
    tab_map = build_tab_map(session, env)
    print(f"Mapped {len(tab_map)} lessons to doc tabs")

    if args.list_tabs:
        for lid, (doc_id, tab_id) in sorted(tab_map.items()):
            course = "Creationeering" if lid.startswith("C") else "Mousetrap"
            print(f"  {lid} → {course} doc tab {tab_id}")
        return

    # Build lesson list
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    all_ids = [l["id"] for l in manifest["lessons"]]

    if args.lesson:
        lesson_ids = [args.lesson.upper()]
    elif args.course == "C":
        lesson_ids = [lid for lid in all_ids if lid.startswith("C-") and lid not in PRESERVE]
    elif args.course == "M":
        lesson_ids = [lid for lid in all_ids if lid.startswith("M-") and lid not in PRESERVE]
    else:
        lesson_ids = [lid for lid in all_ids if lid not in PRESERVE]

    # Only lessons with a doc tab
    lesson_ids = [lid for lid in lesson_ids if lid in tab_map]

    # --retry-failed: skip lessons that already have a successful output .json
    if args.retry_failed:
        before = len(lesson_ids)
        lesson_ids = [lid for lid in lesson_ids if not (OUTPUT_DIR / f"{lid}.json").exists()]
        print(f"  --retry-failed: skipping {before - len(lesson_ids)} already-done lessons, {len(lesson_ids)} remaining")

    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"\nLesson Rewrite from Google Docs [{mode}]")
    print(f"Lessons with tab matches: {len(lesson_ids)}")
    print("=" * 60)

    if not lesson_ids:
        print("No lessons with tab matches found. Run --list-tabs to debug.")
        return

    # Fetch exemplar lessons for style reference
    print("Fetching style exemplars...")
    exemplar_summaries = []
    for eid in STYLE_EXEMPLARS:
        ex = fetch_lesson(eid, key)
        if ex:
            # Use actual Firestore block JSON as reference — not a summary
            reference = blocks_to_reference(ex.get("blocks", []))
            exemplar_summaries.append((eid, ex.get("title", eid), reference))
            print(f"  {eid}: {ex.get('title', '')} ({len(ex.get('blocks', []))} blocks, {len(reference)} chars reference)")

    if not exemplar_summaries:
        print("Could not fetch style exemplars — aborting"); sys.exit(1)

    # Process lessons
    results = []
    counts: dict[str, int] = {}
    for i, lid in enumerate(lesson_ids, 1):
        print(f"\n[{i}/{len(lesson_ids)}]", end=" ")
        r = process_lesson(lid, session, tab_map, exemplar_summaries, env, key, dry_run=args.dry_run)
        results.append(r)
        s = r["status"]
        counts[s] = counts.get(s, 0) + 1
        time.sleep(0.5)

    # Save log
    log = {"results": results, "counts": counts}
    LOG_PATH.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*60}")
    print("SUMMARY:", counts)
    failures = [r for r in results if r["status"] not in ("done", "dry_run", "no_tab_match")]
    if failures:
        print("Review needed:", [(r["id"], r["status"]) for r in failures])


if __name__ == "__main__":
    main()
