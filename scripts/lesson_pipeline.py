"""
Genesis K-12 Lesson Draft Pipeline
-----------------------------------
Usage:
  python lesson_pipeline.py --doc [creationeering|mousetrap] --tab "Tab Title" \
      --topic "Lesson Topic" --phase "Phase Name" --prev "Previous Lesson Topic"

Fills the Creationeering prompt template, calls Gemini, and writes the draft
directly into the named tab of the target Google Doc.
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error
import google.auth
from googleapiclient.discovery import build

# ── CONFIG ──────────────────────────────────────────────────────────────────

DOC_IDS = {
    "creationeering":   "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
    "creationeering-2": "14zURPF6v6A_rQFDD0ojrmFSos3jwu_kZvLkpfg5dqDc",
    "mousetrap":        "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
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
5. Part 1–5 (or as needed) — Each part covers one major concept. Teach directly to the learning objectives.
   Use this sub-structure per part:
   - Plain-language explanation that directly addresses what students need to learn
   - Engineering analogy with concrete imagery
   - Faith or stewardship connection where it arises naturally from the content (do not force it)
   Only include a Multiscale Modeling or OCV connection in a Part if it genuinely clarifies the specific concept being taught. Do not add these as boilerplate sub-bullets to every part.
6. Engineering Journal Task — 5-part structured reflection:
   (1) Identify a System, (2) Energy Path Analysis, (3) Identify the "Toll Booths",
   (4) Optimization Proposal, (5) Biblical Reflection with a specific scripture passage.
7. Technical Documentation Requirements — 3 bullet points. End with the Junior Creationeer Signature block: Person / Date of Analysis / Location of Lab.
8. Summary of Key Concepts — 4 one-line bullets. Each starts with a single word (e.g., Conservation:, Transfer:, Loss:, Analysis:).
9. Works Cited — Use Google Search to find 2 real, published, verifiable sources directly relevant to this lesson's topic. Each must include: author(s), full title, publication name or website, year, and URL if available. Do not fabricate or guess sources — only cite what you can verify exists. Also include: (1) Genesis K12 Academy Full Lesson Book; (2) Horstemeyer, M.F., A. Adebayo, M. Jantomaso, J.L. Long, S. Burgess, and A. McIntosh. (2022). "Creationeering™: An Integrated Engineering-Business Paradigm for Technological Entrepreneurship from a Biblical Basis." Creation Research Society Quarterly 58:238–261.

TONE: Supportive, technical, and faith-integrated. Short sentences. No jargon without a definition. Analogies for every abstract concept. Write as if you are a knowledgeable mentor speaking directly to the student.

APPROACH: You are a teacher whose job is to help students achieve the learning objectives above. Teach the topic directly and clearly. Do not structure content around frameworks — structure it around what students need to understand. Frameworks like Multiscale Modeling and OCV are lenses students can apply themselves; they do not need to appear as named sub-sections in every lesson part. Use them only when they are the clearest way to explain the specific concept.

COURSE CONTEXT:
- Creationeering™ phases (Horstemeyer et al. 2022): Design → Analysis/Synthesis → Procurement → Logistics → Assembly → Performance → Sustainability → Death & Recycling
- Name the current Creationeering phase in the Lesson Overview so students know where this fits in the bigger picture.
- Optimization: use this term (not "Pareto Frontier") when discussing trade-offs.

DO NOT use markdown formatting (no **, *, #, >, or - bullets). Write in plain prose with clear paragraph breaks.
DO NOT reference the mousetrap car.

MOUSETRAP_PROMPT_TEMPLATE = """You are writing a lesson for Genesis K-12 Academy's Middle School Mousetrap Build course, delivered via LearnWorlds. The audience is middle schoolers in homeschool settings (clusters, single families, church groups). Students are designing and building a mousetrap-powered car across an 18-week project course. Write approximately 2,500 words.

TOPIC: {topic}
CREATIONEERING PHASE: {phase}
PREVIOUS LESSON: {prev}

REQUIRED STRUCTURE (use these exact section headers):
1. Lesson Overview — 2 paragraphs. Connect briefly to the previous lesson. Explain how today's topic applies directly to the mousetrap car project.
2. Learning Objectives — 5 bulleted objectives. End one with a biblical stewardship connection.
3. Key Vocabulary — table with Term and Definition columns. 6-8 terms.
4. The Beginning: [Thematic Title] — Open with a biblical anchor (cite book, chapter, verse). Connect the theological idea to the engineering principle at hand.
5. Part 1–3 (or as needed) — Each part covers one major concept. Teach directly to the learning objectives.
   - Plain-language explanation that directly addresses what students need to learn
   - Direct application to the mousetrap car project
   - Engineering analogy with concrete imagery
   Only include a Multiscale Modeling or OCV connection if it genuinely clarifies the specific concept. Do not add these as a sub-bullet to every part.
6. Engineering Journal Task — 4-part structured reflection:
   (1) Apply to Your Car, (2) Identify Trade-offs, (3) OCV for Your Design,
   (4) Biblical Reflection with a specific scripture passage
7. Technical Documentation Requirements — 2 bullet points. End with Junior Creationeer Signature block: Person / Date / Location of Lab.
8. Summary of Key Concepts — 4 one-line bullets each starting with a single word (e.g., Precision:, Efficiency:, Design:, Trade-off:).
9. Works Cited — Use Google Search to find 2 real, published, verifiable sources directly relevant to this lesson's topic. Each must include: author(s), full title, publication name or website, year, and URL if available. Do not fabricate or guess sources — only cite what you can verify exists. Also include: (1) Genesis K12 Academy Full Lesson Book; (2) Horstemeyer, M.F., A. Adebayo, M. Jantomaso, J.L. Long, S. Burgess, and A. McIntosh. (2022). "Creationeering™: An Integrated Engineering-Business Paradigm for Technological Entrepreneurship from a Biblical Basis." Creation Research Society Quarterly 58:238–261.

TONE: Supportive, technical, and faith-integrated. Short sentences. No jargon without a definition. Always connect abstract concepts to the mousetrap car. Write as a knowledgeable mentor speaking directly to the student.

APPROACH: You are a teacher whose job is to help students achieve the learning objectives above. Teach each concept so students can actually do what the objectives describe. Frameworks like Multiscale Modeling and OCV are analytical lenses — use them only when they are the most direct way to explain the concept at hand. Do not add them as named sections or boilerplate sub-bullets to every lesson part.

COURSE CONTEXT:
- Name the current Creationeering™ phase (Horstemeyer et al. 2022) in the Lesson Overview.
- All concepts must connect explicitly to the mousetrap car build project.

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


def call_gemini(api_key, prompt, horstemeyer_uri=None):
    req_parts = []
    if horstemeyer_uri:
        req_parts.append({"file_data": {"mime_type": "application/pdf", "file_uri": horstemeyer_uri}})
    req_parts.append({"text": prompt})
    payload = json.dumps({
        "contents": [{"parts": req_parts}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192, "thinkingConfig": {"thinkingBudget": 1024}}
    }).encode("utf-8")

    url = f"{GEMINI_URL}?key={api_key}"
    max_retries = 3
    for attempt in range(max_retries + 1):
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
            resp_parts = candidate["content"].get("parts", [])
            text_parts = [p["text"] for p in resp_parts
                          if not p.get("thought", False) and "text" in p
                          and len(p["text"]) < 40000]
            result = "\n".join(text_parts)
            if len(result) > 30000:
                print(f"Error: draft is {len(result):,} chars, exceeds 60K safety limit. Skipping.")
                sys.exit(1)
            return strip_markdown(result)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            if e.code == 429 and attempt < max_retries:
                match = re.search(r'retry in (\d+\.?\d*)s', body)
                delay = float(match.group(1)) + 5 if match else 65 * (attempt + 1)
                print(f"Rate limited (429). Retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)
                continue
            print(f"Gemini error {e.code}: {body}")
            sys.exit(1)


def get_docs_service():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/documents"])
    return build("docs", "v1", credentials=creds)


def get_tab_id(doc_id, tab_title):
    svc = get_docs_service()
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title.strip().lower():
            return props.get("tabId")
    available = [t.get("tabProperties", {}).get("title") for t in doc.get("tabs", [])]
    print(f"Tab '{tab_title}' not found. Available tabs:\n" + "\n".join(f"  - {t}" for t in available))
    sys.exit(1)


def write_to_tab(doc_id, tab_id, text):
    svc = get_docs_service()
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()
    end_index = 1
    for tab in doc.get("tabs", []):
        if tab.get("tabProperties", {}).get("tabId") == tab_id:
            content = tab.get("documentTab", {}).get("body", {}).get("content", [])
            if content:
                end_index = content[-1].get("endIndex", 1)
            break

    requests = []
    if end_index > 2:
        requests.append({"deleteContentRange": {"range": {
            "startIndex": 1, "endIndex": end_index - 1, "tabId": tab_id
        }}})
    requests.append({"insertText": {"text": text, "location": {"index": 1, "tabId": tab_id}}})
    svc.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Lesson Draft Pipeline")
    parser.add_argument("--doc",       required=True, choices=["creationeering", "creationeering-2", "mousetrap"],
                        help="Which course doc to write to")
    parser.add_argument("--tab",       required=True, help="Exact tab title to write into")
    parser.add_argument("--topic",     required=True, help="Lesson topic")
    parser.add_argument("--phase",     required=True,
                        help="Creationeering phase (e.g. 'Procurement')")
    parser.add_argument("--prev",      required=True, help="Previous lesson topic")
    parser.add_argument("--draft-out", default=None,
                        help="Optional path to write the raw draft text for downstream agents")
    parser.add_argument("--horstemeyer-uri", default=None,
                        help="Gemini File API URI for the Horstemeyer 2022 PDF")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        sys.exit(1)

    doc_id = DOC_IDS[args.doc]

    template = MOUSETRAP_PROMPT_TEMPLATE if args.doc == "mousetrap" else CREATIONEERING_PROMPT_TEMPLATE
    prompt = template.format(
        topic=args.topic,
        phase=args.phase,
        prev=args.prev
    )
    if args.horstemeyer_uri:
        prompt = (
            "The attached PDF is the Horstemeyer et al. 2022 Creationeering paper — your primary source "
            "for all framework references and the Works Cited entry. Use it directly; do not paraphrase the citation.\n\n"
            + prompt
        )

    print(f"Drafting: '{args.topic}' ({args.phase} phase)...")
    draft = call_gemini(api_key, prompt, horstemeyer_uri=args.horstemeyer_uri)
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
