"""
Genesis K-12 Revision Agent

Reads a QC-flagged lesson from Google Docs, rewrites the flagged section(s)
using Claude (claude-opus-4-7), and writes the corrected full draft back to
the Google Doc tab.

Standalone only — NOT wired into the automatic pipeline. Run after reviewing
QC notes and deciding a targeted revision is better than a full re-draft.

Usage:
  python revision_agent.py --lesson-id C-038
      # auto-reads QC notes from manifest, revises the lowest-scoring section

  python revision_agent.py --lesson-id C-038 --section "Lesson Overview"
      # revise a specific named section

  python revision_agent.py --lesson-id C-038 --section "faith_integration"
      # revise by QC dimension name (reads notes from manifest)

  python revision_agent.py --lesson-id C-038 --dry-run
      # show what would be revised without writing to Doc

  python revision_agent.py --lesson-id C-038 --preview
      # print the revised section to stdout without writing to Doc
"""

import argparse, json, os, re, sys, urllib.request, urllib.error
import google.auth
from googleapiclient.discovery import build

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")

CLAUDE_MODEL = "claude-opus-4-7"
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"

DOC_IDS = {
    "creationeering": "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
    "mousetrap":      "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
}

# Maps QC dimension names to the section they most affect
DIMENSION_TO_SECTION = {
    "faith_integration": "The Beginning",
    "reading_level":     "Part 1",
    "analogy_quality":   "Part 1",
    "framework_use":     "Engineering Journal",
    "structure_complete": "Lesson Overview",
}

REVISION_PROMPT = """You are revising one section of a Genesis K-12 Academy Middle School {course} lesson on "{topic}".

QC FEEDBACK TO ADDRESS:
{qc_notes}

SECTION TO REVISE: {section_name}

FULL LESSON CONTEXT (read for tone and continuity — do not rewrite this):
{context}

---
CURRENT SECTION TEXT TO REWRITE:
{section_text}
---

Rewrite ONLY the section above. Keep the same section header. Match the tone, length, and style of the surrounding lesson. Address the QC feedback directly.

Rules:
- No markdown formatting (no **, *, #, >, or bullet markers)
- Plain prose, clear paragraph breaks
- Same approximate length as the original section
- Do not reference the QC feedback or this revision process in the output
- Start immediately with the section header line, end at the section boundary

Output ONLY the revised section text."""


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


def get_docs_service():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/documents"])
    return build("docs", "v1", credentials=creds)


def read_tab_content(doc_id, tab_title):
    svc = get_docs_service()
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title.strip().lower():
            body = tab.get("documentTab", {}).get("body", {})
            parts = []
            for element in body.get("content", []):
                paragraph = element.get("paragraph", {})
                for pe in paragraph.get("elements", []):
                    tr = pe.get("textRun", {})
                    parts.append(tr.get("content", ""))
            return "".join(parts)
    raise ValueError(f"Tab '{tab_title}' not found in doc")


def get_tab_id(doc_id, tab_title):
    svc = get_docs_service()
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title.strip().lower():
            return props.get("tabId")
    raise ValueError(f"Tab '{tab_title}' not found")


def get_tab_end_index(doc_id, tab_title):
    """Return the end index of the tab's body content."""
    svc = get_docs_service()
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title.strip().lower():
            body = tab.get("documentTab", {}).get("body", {})
            content = body.get("content", [])
            if content:
                return content[-1].get("endIndex", 1)
    return 1


def write_full_tab(doc_id, tab_title, text):
    """Clear the tab and write new content."""
    svc    = get_docs_service()
    tab_id = get_tab_id(doc_id, tab_title)
    end    = get_tab_end_index(doc_id, tab_title)

    requests = []
    if end > 1:
        requests.append({
            "deleteContentRange": {
                "range": {"startIndex": 1, "endIndex": end - 1, "tabId": tab_id}
            }
        })
    requests.append({
        "insertText": {"text": text, "location": {"index": 1, "tabId": tab_id}}
    })
    svc.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()


def find_section(draft, section_name):
    """
    Return (section_text, start_idx, end_idx) for the named section.
    Section boundaries are detected by header lines (plain or markdown ##/###).
    """
    # Build a pattern that matches the section header
    header_pat = re.compile(
        r'(?:^|\n)(#{0,6}\s*)' + re.escape(section_name) + r'[^\n]*\n',
        re.IGNORECASE
    )
    m = header_pat.search(draft)
    if not m:
        return None, -1, -1

    start = m.start()
    if draft[start] == '\n':
        start += 1  # don't include the leading newline

    # Find the next section header (any line that starts a new major section)
    next_header = re.compile(
        r'\n(#{1,6}\s+\S|(?:Lesson Overview|Learning Objectives|Key Vocabulary|'
        r'The Beginning|Part \d|Engineering Journal|Technical Documentation|'
        r'Summary of Key Concepts|Works Cited)\b)',
        re.IGNORECASE
    )
    rest_start = m.end()
    m2 = next_header.search(draft, rest_start)
    end = m2.start() + 1 if m2 else len(draft)

    return draft[start:end], start, end


def call_claude(api_key, prompt):
    payload = json.dumps({
        "model":      CLAUDE_MODEL,
        "max_tokens": 4096,
        "messages":   [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        CLAUDE_URL, data=payload,
        headers={
            "Content-Type":    "application/json",
            "x-api-key":       api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        print(f"Claude error {e.code}: {e.read().decode('utf-8')[:300]}")
        return None
    except Exception as e:
        print(f"Claude error: {e}")
        return None


def pick_target_section(lesson):
    """Choose which section to revise based on lowest QC score."""
    scores = lesson.get("qc_scores", {})
    notes  = lesson.get("qc_notes", "")

    # Find the lowest-scoring dimension
    dims = ["faith_integration", "reading_level", "analogy_quality",
            "framework_use", "structure_complete"]
    worst_dim  = min(dims, key=lambda d: scores.get(d) or 3)
    worst_score = scores.get(worst_dim, 3)

    section = DIMENSION_TO_SECTION.get(worst_dim, "Part 1")
    return section, worst_dim, worst_score, notes


def update_manifest(lesson_id, section_revised, status="revised"):
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    for m in data["lessons"]:
        if m["id"] == lesson_id:
            m["revision_status"]  = status
            m["revised_section"]  = section_revised
            m["qc_status"]        = "needs_recheck"
            break
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Revision Agent")
    parser.add_argument("--lesson-id", required=True)
    parser.add_argument("--section",   default=None,
                        help="Section name or QC dimension to revise")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Show what would be revised without calling Claude or writing to Doc")
    parser.add_argument("--preview",   action="store_true",
                        help="Call Claude and print revised section, but do not write to Doc")
    args = parser.parse_args()

    env     = load_env()
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print("Error: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    lesson = next((l for l in data["lessons"] if l["id"] == args.lesson_id), None)
    if not lesson:
        print(f"Lesson {args.lesson_id} not found in manifest")
        sys.exit(1)

    if lesson["status"] != "done":
        print(f"Lesson {args.lesson_id} is not done (status={lesson['status']}). Nothing to revise.")
        sys.exit(1)

    # Determine target section
    if args.section and args.section in DIMENSION_TO_SECTION:
        section_name = DIMENSION_TO_SECTION[args.section]
        dim          = args.section
        qc_notes     = lesson.get("qc_notes", "No QC notes available.")
    elif args.section:
        section_name = args.section
        dim          = "manual"
        qc_notes     = lesson.get("qc_notes", "No QC notes available.")
    else:
        section_name, dim, score, qc_notes = pick_target_section(lesson)
        print(f"Auto-selected section: '{section_name}' (lowest dimension: {dim})")

    print(f"\nRevision: [{args.lesson_id}] {lesson['tab']}")
    print(f"  Section:  {section_name}")
    print(f"  QC notes: {qc_notes[:120]}")

    if args.dry_run:
        print(f"\n[dry-run] Would revise '{section_name}' via Claude {CLAUDE_MODEL}")
        return

    # Read current draft from Google Doc
    doc_id = DOC_IDS[lesson["doc"]]
    print(f"\nReading from Google Doc tab '{lesson['tab']}'...")
    draft = read_tab_content(doc_id, lesson["tab"])
    if len(draft.strip()) < 200:
        print(f"Tab content too short ({len(draft)} chars). May be empty.")
        sys.exit(1)
    print(f"Read {len(draft):,} chars")

    # Find the target section
    section_text, start, end = find_section(draft, section_name)
    if section_text is None:
        print(f"Section '{section_name}' not found in draft.")
        print("Available headers:")
        for line in draft.splitlines():
            if re.match(r'^(#{1,6}\s+\S|\b(?:Lesson Overview|Learning Objectives|Key Vocabulary|The Beginning|Part \d|Engineering Journal|Technical Documentation|Summary|Works Cited))', line):
                print(f"  {line[:80]}")
        sys.exit(1)

    print(f"Found section '{section_name}': {len(section_text):,} chars (pos {start}–{end})")

    # Build context (surrounding lesson text, trimmed)
    context_before = draft[max(0, start - 800):start].strip()
    context_after  = draft[end:end + 400].strip()
    context = (f"...{context_before}\n[TARGET SECTION GOES HERE]\n{context_after}...").strip()

    course_label = "Creationeering" if lesson["doc"] == "creationeering" else "Mousetrap Build"
    prompt = REVISION_PROMPT.format(
        course       = course_label,
        topic        = lesson["topic"],
        qc_notes     = qc_notes,
        section_name = section_name,
        context      = context[:2000],
        section_text = section_text.strip(),
    )

    print(f"\nCalling Claude ({CLAUDE_MODEL})...")
    revised = call_claude(api_key, prompt)
    if not revised:
        print("Claude returned no response.")
        sys.exit(1)

    print(f"Revised section: {len(revised):,} chars")

    if args.preview:
        print("\n" + "="*60)
        print(revised)
        print("="*60)
        print("\n[preview mode] Not written to Google Doc.")
        return

    # Splice revised section back into full draft
    new_draft = draft[:start] + revised + "\n" + draft[end:]
    print(f"\nWriting updated draft to Google Doc ({len(new_draft):,} chars)...")
    write_full_tab(doc_id, lesson["tab"], new_draft)
    print("Written.")

    update_manifest(args.lesson_id, section_name)
    print(f"Manifest updated: revision_status=revised, qc_status=needs_recheck")
    print(f"\nDone. Run 'python rerun_qc.py --ids {args.lesson_id}' to re-score.")


if __name__ == "__main__":
    main()
