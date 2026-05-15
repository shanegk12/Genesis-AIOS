"""
Genesis K-12 Lesson Draft Pipeline
-----------------------------------
Usage:
  python lesson_pipeline.py --doc [creationeering|mousetrap] --tab "Tab Title" \
      --topic "Lesson Topic" --phase "Phase Name" --prev "Previous Lesson Topic"

Fills the Creationeering prompt template, calls Gemini, and writes the draft
directly into the named tab of the target Google Doc.
"""

import argparse, json, os, re, subprocess, sys, urllib.request, urllib.error

# ── CONFIG ──────────────────────────────────────────────────────────────────

DOC_IDS = {
    "creationeering": "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
    "mousetrap":      "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
}

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

CREATIONEERING_PROMPT_TEMPLATE = """You are writing a lesson for Genesis K-12 Academy's Middle School Creationeering course, delivered via LearnWorlds. The audience is middle schoolers in homeschool settings (clusters, single families, church groups). Write approximately 3,000 words.

TOPIC: {topic}
CREATIONEERING PHASE: {phase}
PREVIOUS LESSON TOPIC: {prev}

REQUIRED STRUCTURE (use these exact section headers):
1. Lesson Overview — 2 paragraphs. Reference the previous lesson briefly. Introduce today's topic through the Creationeering™ framework.
2. Learning Objectives — 5 bulleted objectives. End one with a biblical stewardship connection.
3. Key Vocabulary — table with Term and Definition columns. 8-10 terms.
4. The Beginning: [Thematic Title] — Open with a biblical anchor (cite book, chapter, verse). Connect the theological idea directly to the engineering principle.
5. Part 1–5 (or as needed) — Each part covers one major concept. Use this sub-structure per part:
   - Plain-language explanation
   - Engineering analogy with concrete imagery
   - Multiscale Modeling connection (macro-level observation → atomic-level cause)
   - OCV application where relevant
6. Engineering Journal Task — 5-part structured reflection:
   (1) Identify a System, (2) Energy Path Analysis, (3) Identify the "Toll Booths",
   (4) Optimization Proposal using OCV, (5) Biblical Reflection with a specific scripture passage.
7. Technical Documentation Requirements — 3 bullet points. End with the Junior Creationeer Signature block: Person / Date of Analysis / Location of Lab.
8. Summary of Key Concepts — 4 one-line bullets. Each starts with a single word (e.g., Conservation:, Transfer:, Loss:, Analysis:).
9. Works Cited — Genesis K12 Academy Full Lesson Book, Horstemeyer 2021 Creationeering paper, 2 external sources relevant to the topic.

TONE: Supportive, technical, and faith-integrated. Short sentences. No jargon without a definition. Analogies for every abstract concept. Write as if you are a knowledgeable mentor speaking directly to the student.

FRAMEWORKS TO USE (do not omit these):
- Creationeering™ phases (name the relevant phase explicitly per Dr. Horstemeyer 2021)
  Phases in order: Design → Analysis/Synthesis → Procurement → Logistics → Assembly → Performance → Sustainability → Death & Recycling
- Multiscale Modeling — always connect macro-level observation to atomic-level cause
- OCV Method (Objective, Constraint, Variable) — apply to one design problem per lesson
- Optimization — use this term (not "Pareto Frontier") when discussing finding the best trade-off between variables

DO NOT use markdown formatting (no **, *, #, >, or - bullets). Write in plain prose with clear paragraph breaks.
DO NOT reference the mousetrap car."""

MOUSETRAP_PROMPT_TEMPLATE = """You are writing a lesson for Genesis K-12 Academy's Middle School Mousetrap Build course, delivered via LearnWorlds. The audience is middle schoolers in homeschool settings (clusters, single families, church groups). Students are designing and building a mousetrap-powered car across an 18-week project course. Write approximately 2,500 words.

TOPIC: {topic}
CREATIONEERING PHASE: {phase}
PREVIOUS LESSON: {prev}

REQUIRED STRUCTURE (use these exact section headers):
1. Lesson Overview — 2 paragraphs. Connect briefly to the previous lesson. Explain how today's topic applies directly to the mousetrap car project.
2. Learning Objectives — 5 bulleted objectives. End one with a biblical stewardship connection.
3. Key Vocabulary — table with Term and Definition columns. 6-8 terms.
4. The Beginning: [Thematic Title] — Open with a biblical anchor (cite book, chapter, verse). Connect the theological idea to the engineering principle at hand.
5. Part 1–3 (or as needed) — Each part covers one major concept:
   - Plain-language explanation
   - Direct application to the mousetrap car project
   - Multiscale Modeling connection (macro-level observation → atomic-level cause) where applicable
   - OCV application (Objective, Constraint, Variable) where relevant
6. Engineering Journal Task — 4-part structured reflection:
   (1) Apply to Your Car, (2) Identify Trade-offs, (3) OCV for Your Design,
   (4) Biblical Reflection with a specific scripture passage
7. Technical Documentation Requirements — 2 bullet points. End with Junior Creationeer Signature block: Person / Date / Location of Lab.
8. Summary of Key Concepts — 4 one-line bullets each starting with a single word (e.g., Precision:, Efficiency:, Design:, Trade-off:).
9. Works Cited — Genesis K12 Academy Full Lesson Book, Horstemeyer 2021 Creationeering paper, 2 external sources relevant to the topic.

TONE: Supportive, technical, and faith-integrated. Short sentences. No jargon without a definition. Always connect abstract concepts to the mousetrap car. Write as a knowledgeable mentor speaking directly to the student.

FRAMEWORKS TO USE (do not omit):
- Creationeering™ phases (Dr. Horstemeyer 2021) — name the current phase explicitly
- Multiscale Modeling — connect macro-level observation to atomic-level cause
- OCV Method (Objective, Constraint, Variable) — apply to one mousetrap car design decision
- All concepts must connect explicitly to the mousetrap car build project

DO NOT use markdown formatting (no **, *, #, >, or - bullets). Write in plain prose with clear paragraph breaks."""


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


def strip_markdown(text):
    text = re.sub(r'\*\*(.+?)\*\*', lambda m: m.group(1), text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*',     lambda m: m.group(1), text, flags=re.DOTALL)
    text = re.sub(r'`(.+?)`',       lambda m: m.group(1), text, flags=re.DOTALL)
    text = re.sub(r'\[(.+?)\]\(.+?\)', lambda m: m.group(1), text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>+\s?',     '', text, flags=re.MULTILINE)
    text = re.sub(r'^[*\-]\s+', '',  text, flags=re.MULTILINE)
    return text


def call_gemini(api_key, prompt):
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 24576},
        "thinkingConfig": {"thinkingBudget": 0}
    }).encode("utf-8")

    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        candidate = data["candidates"][0]
        if "content" not in candidate:
            finish = candidate.get("finishReason", "UNKNOWN")
            print(f"Gemini returned no content (finishReason: {finish})")
            sys.exit(1)
        parts = candidate["content"].get("parts", [])
        text_parts = [p["text"] for p in parts if not p.get("thought", False) and "text" in p]
        result = "\n".join(text_parts)
        if len(result) > 60000:
            print(f"Error: draft is {len(result):,} chars, exceeds 60K safety limit. Possible thinking token leak. Skipping.")
            sys.exit(1)
        return strip_markdown(result)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"Gemini error {e.code}: {body}")
        sys.exit(1)


_GWS_EXE = r"C:\Users\Shane\AppData\Roaming\npm\node_modules\@googleworkspace\cli\bin\gws.exe"


def gws_run(params_dict, json_dict=None, subcommand=""):
    """Run a gws command via the Windows gws.exe binary."""
    cmd = [_GWS_EXE] + subcommand.split()
    cmd += ["--params", json.dumps(params_dict, ensure_ascii=True)]
    if json_dict is not None:
        cmd += ["--json", json.dumps(json_dict, ensure_ascii=True)]

    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = "\n".join(l for l in (result.stdout or "").splitlines() if not l.startswith("Using keyring"))
    if result.returncode != 0:
        stderr = "\n".join(l for l in (result.stderr or "").splitlines() if not l.startswith("Using keyring"))
        print(f"gws error: {stderr.strip() or output}")
        sys.exit(1)
    return json.loads(output) if output.strip() else {}


def get_tab_id(doc_id, tab_title):
    """Find the tabId for a tab by title."""
    data = gws_run({"documentId": doc_id, "includeTabsContent": True},
                   subcommand="docs documents get")
    tabs = data.get("tabs", [])
    for tab in tabs:
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title.strip().lower():
            return props.get("tabId")
    available = [t.get("tabProperties", {}).get("title") for t in tabs]
    print(f"Tab '{tab_title}' not found. Available tabs:\n" + "\n".join(f"  - {t}" for t in available))
    sys.exit(1)


def write_to_tab(doc_id, tab_id, text):
    """Write text to a tab in chunks to stay under Windows' 32K command-line limit."""
    CHUNK = 8000
    chunks = [text[i:i+CHUNK] for i in range(0, len(text), CHUNK)]

    first_body = {"requests": [{"insertText": {"text": chunks[0], "location": {"index": 1, "tabId": tab_id}}}]}
    gws_run({"documentId": doc_id}, json_dict=first_body, subcommand="docs documents batchUpdate")

    for chunk in chunks[1:]:
        body = {"requests": [{"insertText": {"text": chunk, "endOfSegmentLocation": {"tabId": tab_id}}}]}
        gws_run({"documentId": doc_id}, json_dict=body, subcommand="docs documents batchUpdate")


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Lesson Draft Pipeline")
    parser.add_argument("--doc",       required=True, choices=["creationeering", "mousetrap"],
                        help="Which course doc to write to")
    parser.add_argument("--tab",       required=True, help="Exact tab title to write into")
    parser.add_argument("--topic",     required=True, help="Lesson topic")
    parser.add_argument("--phase",     required=True,
                        help="Creationeering phase (e.g. 'Procurement')")
    parser.add_argument("--prev",      required=True, help="Previous lesson topic")
    parser.add_argument("--draft-out", default=None,
                        help="Optional path to write the raw draft text for downstream agents")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        sys.exit(1)

    doc_id = DOC_IDS[args.doc]

    template = CREATIONEERING_PROMPT_TEMPLATE if args.doc == "creationeering" else MOUSETRAP_PROMPT_TEMPLATE
    prompt = template.format(
        topic=args.topic,
        phase=args.phase,
        prev=args.prev
    )

    print(f"Drafting: '{args.topic}' ({args.phase} phase)...")
    draft = call_gemini(api_key, prompt)
    print(f"Draft received: {len(draft)} chars / ~{len(draft.split()):,} words")

    if args.draft_out:
        with open(args.draft_out, "w", encoding="utf-8") as f:
            f.write(draft)

    print(f"Locating tab '{args.tab}'...")
    tab_id = get_tab_id(doc_id, args.tab)
    print(f"Found tab ID: {tab_id}")

    print("Writing to Google Doc...")
    write_to_tab(doc_id, tab_id, draft)
    print(f"Done. Open the doc and check tab: '{args.tab}'")


if __name__ == "__main__":
    main()
