"""
Genesis K-12 Assessment Agent

Generates 5 multiple-choice questions per lesson from the draft text.
Saves to scripts/assessments/[lesson-id].json and updates the manifest.

Only runs on lessons that passed QC — flagged lessons skip assessment until
they're revised and re-checked.

Usage (standalone):
  python assessment_agent.py --draft-file path/to/draft.txt \\
      --lesson-id C-030 --topic "Procurement" --doc creationeering

  python assessment_agent.py --lesson-id C-030   # reads from Google Doc
  python assessment_agent.py --all-passed        # batch all QC-passed lessons missing assessments
  python assessment_agent.py --dry-run           # list targets without generating
"""

import argparse, json, os, re, sys, time, urllib.request, urllib.error

MANIFEST_PATH    = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
ASSESSMENTS_DIR  = os.path.join(os.path.dirname(__file__), "assessments")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

DOC_IDS = {
    "creationeering": "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
    "mousetrap":      "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
}

ASSESSMENT_PROMPT = """You are writing a quiz for a Genesis K-12 Academy Middle School {course} lesson on "{topic}".

Generate exactly 5 multiple-choice questions based on the lesson draft below. Questions should:
- Test genuine understanding of the key concepts, not trivia or memorization
- Include one question on the biblical/faith connection
- Include one question applying the OCV method or Creationeering framework
- Use vocabulary appropriate for 6th-8th grade
- Have one clearly correct answer and three plausible distractors

Return ONLY a JSON array — no markdown, no other text:
[
  {{
    "question": "Full question text?",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "answer": "B",
    "explanation": "One sentence explaining why this answer is correct."
  }},
  ...
]

LESSON DRAFT (first 6000 chars):
{draft}"""


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


def read_from_google_doc(lesson):
    import google.auth
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/documents.readonly"])
    svc = build("docs", "v1", credentials=creds)
    doc_id = DOC_IDS[lesson["doc"]]
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()
    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == lesson["tab"].strip().lower():
            body = tab.get("documentTab", {}).get("body", {})
            parts = []
            for element in body.get("content", []):
                for pe in element.get("paragraph", {}).get("elements", []):
                    parts.append(pe.get("textRun", {}).get("content", ""))
            return "".join(parts)
    raise ValueError(f"Tab '{lesson['tab']}' not found")


def call_gemini(api_key, prompt):
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
    }).encode("utf-8")
    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data["candidates"][0]["content"].get("parts", [])
        text = "\n".join(p["text"] for p in parts if not p.get("thought") and "text" in p).strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        start = text.find("[")
        if start > 0:
            text = text[start:]
        return json.loads(text)
    except Exception as e:
        print(f"  Gemini error: {e}")
        return None


def save_assessment(lesson_id, topic, doc, questions):
    os.makedirs(ASSESSMENTS_DIR, exist_ok=True)
    path = os.path.join(ASSESSMENTS_DIR, f"{lesson_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"lesson_id": lesson_id, "topic": topic, "doc": doc,
                   "questions": questions}, f, indent=2, ensure_ascii=False)
    return path


def update_manifest(lesson_id, status, path=None):
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)
    for m in data["lessons"]:
        if m["id"] == lesson_id:
            m["assessment_status"] = status
            if path:
                m["assessment_file"] = os.path.relpath(path, os.path.dirname(MANIFEST_PATH))
            break
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_assessment(draft_text, lesson_id, topic, doc, api_key):
    course_label = "Creationeering" if doc == "creationeering" else "Mousetrap Build"
    prompt = ASSESSMENT_PROMPT.format(
        course=course_label, topic=topic, draft=draft_text[:6000]
    )
    questions = call_gemini(api_key, prompt)
    if not questions:
        update_manifest(lesson_id, "failed")
        return False

    path = save_assessment(lesson_id, topic, doc, questions)
    update_manifest(lesson_id, "done", path)
    print(f"  Assessment: {len(questions)} questions -> {path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Assessment Agent")
    parser.add_argument("--draft-file",  help="Path to draft text file")
    parser.add_argument("--lesson-id",   help="Lesson ID (e.g. C-030)")
    parser.add_argument("--topic",       help="Lesson topic")
    parser.add_argument("--doc",         choices=["creationeering", "mousetrap"])
    parser.add_argument("--all-passed",  action="store_true",
                        help="Batch all QC-passed lessons missing assessments")
    parser.add_argument("--dry-run",     action="store_true")
    args = parser.parse_args()

    env     = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Batch mode
    if args.all_passed:
        targets = [
            l for l in data["lessons"]
            if l["status"] == "done"
            and l.get("qc_status") == "passed"
            and l.get("assessment_status") != "done"
        ]
        if not targets:
            print("No QC-passed lessons are missing assessments.")
            return
        print(f"Batch assessment: {len(targets)} lessons\n")
        if args.dry_run:
            for l in targets:
                print(f"  [{l['id']}] {l['tab']}")
            return
        ok = fail = 0
        for i, lesson in enumerate(targets, 1):
            print(f"[{i}/{len(targets)}] {lesson['id']} — {lesson['tab']}")
            try:
                draft = read_from_google_doc(lesson)
                if len(draft.strip()) < 200:
                    print(f"  Tab too short, skipping")
                    fail += 1
                    continue
                if run_assessment(draft, lesson["id"], lesson["topic"], lesson["doc"], api_key):
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"  Error: {e}")
                fail += 1
            if i < len(targets):
                time.sleep(2)
        print(f"\n=== Assessment batch: {ok} done, {fail} failed ===")
        return

    # Single lesson mode
    if not args.lesson_id:
        parser.error("--lesson-id required (or use --all-passed for batch)")

    lesson = next((l for l in data["lessons"] if l["id"] == args.lesson_id), None)
    if not lesson:
        print(f"Lesson {args.lesson_id} not found in manifest")
        sys.exit(1)

    topic = args.topic or lesson["topic"]
    doc   = args.doc   or lesson["doc"]

    if args.draft_file:
        with open(args.draft_file, encoding="utf-8") as f:
            draft = f.read()
    else:
        print(f"Reading tab '{lesson['tab']}' from Google Doc...")
        draft = read_from_google_doc(lesson)
        print(f"Read {len(draft):,} chars")

    if args.dry_run:
        print(f"[dry-run] Would generate 5 MCQ for [{args.lesson_id}] {topic}")
        return

    print(f"Assessment: [{args.lesson_id}] {topic}")
    success = run_assessment(draft, args.lesson_id, topic, doc, api_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
