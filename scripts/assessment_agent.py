"""
Genesis K-12 Assessment Agent

Generates a question bank of 12 multiple-choice questions per lesson.
Questions span four types so quiz draws feel varied across retakes:
  - Recall (3): key facts, definitions, terms from the lesson
  - Comprehension (3): explain why/how, cause-and-effect
  - Application (3): apply a concept to a new scenario
  - Synthesis/Faith (3): connect ideas, biblical stewardship angle

QuizEngine draws 5 random questions per attempt from the bank of 12,
so retakes present different questions.

Saves to scripts/assessments/[lesson-id].json and updates the manifest.

Usage:
  python assessment_agent.py --lesson-id C-030   # single lesson
  python assessment_agent.py --all-passed        # batch all QC-passed lessons missing banks
  python assessment_agent.py --expand-bank       # expand existing 5-question files to 12
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

ASSESSMENT_PROMPT = """You are building a question bank for a Genesis K-12 Academy Middle School {course} lesson on "{topic}".

Generate exactly 12 multiple-choice questions from the lesson draft below.
Write exactly 3 questions of each type — label each with a "type" field:

  "recall"       — key facts, definitions, or terms stated directly in the lesson
  "comprehension"— explain why/how something works, cause-and-effect reasoning
  "application"  — apply a concept from the lesson to a new real-world scenario
  "synthesis"    — connect two or more lesson ideas, OR tie a concept to biblical stewardship

Rules for all questions:
- No two questions test the same fact or concept
- Each question is independently answerable — no "based on your answer above" references
- Vocabulary appropriate for 6th-8th grade
- One clearly correct answer and three plausible, non-trivial distractors
- Explanations are one sentence: state WHY the answer is correct, not just what it is

Return ONLY a JSON array — no markdown, no other text:
[
  {{
    "type": "recall",
    "question": "Full question text?",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "answer": "B",
    "explanation": "One sentence explaining why B is correct."
  }},
  ...
]

LESSON DRAFT (first 6000 chars):
{draft}"""


EXPAND_BANK_PROMPT = """You are expanding a question bank for a Genesis K-12 Academy Middle School {course} lesson on "{topic}".

The lesson already has these {existing_count} questions (do NOT duplicate them):
{existing_questions}

Generate exactly {needed} NEW multiple-choice questions to bring the bank to 12 total.
Write questions of these types to fill the gaps: {needed_types}

Rules:
- Do not repeat any concept already tested in the existing questions above
- Each new question is independently answerable
- Vocabulary appropriate for 6th-8th grade
- One clearly correct answer and three plausible distractors
- Explanations are one sentence

Return ONLY a JSON array of the NEW questions — no markdown:
[
  {{
    "type": "recall|comprehension|application|synthesis",
    "question": "...",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "answer": "A",
    "explanation": "..."
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


def _clean_json_text(text):
    # Strip markdown fences
    text = re.sub(r"^```json\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    # Find start of JSON array
    start = text.find("[")
    if start > 0:
        text = text[start:]
    # Replace curly/smart quotes with straight quotes
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    return text


def call_gemini(api_key, prompt):
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 8192},
    }).encode("utf-8")
    url = f"{GEMINI_URL}?key={api_key}"
    for attempt in range(3):
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            parts = data["candidates"][0]["content"].get("parts", [])
            text = "\n".join(p["text"] for p in parts if not p.get("thought") and "text" in p).strip()
            text = _clean_json_text(text)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                last = text.rfind("},")
                if last > 0:
                    text = text[:last + 1] + "\n]"
                    return json.loads(text)
                raise
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"  Gemini {e.code} — retrying in {wait}s ({attempt + 2}/3)...")
                time.sleep(wait)
                continue
            print(f"  Gemini error: {e}")
            return None
        except Exception as e:
            print(f"  Gemini error: {e}")
            return None
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


QUESTION_TYPES = ["recall", "comprehension", "application", "synthesis"]
BANK_SIZE = 12
DRAW_SIZE = 5  # questions drawn per quiz attempt


def run_assessment(draft_text, lesson_id, topic, doc, api_key):
    course_label = "Creationeering" if doc == "creationeering" else "Mousetrap Build"
    prompt = ASSESSMENT_PROMPT.format(
        course=course_label, topic=topic, draft=draft_text[:6000]
    )
    questions = call_gemini(api_key, prompt)
    if not questions or len(questions) < 8:
        update_manifest(lesson_id, "failed")
        return False

    # Stamp any missing type fields
    for i, q in enumerate(questions):
        if "type" not in q:
            q["type"] = QUESTION_TYPES[i % len(QUESTION_TYPES)]

    path = save_assessment(lesson_id, topic, doc, questions)
    update_manifest(lesson_id, "done", path)
    print(f"  Bank: {len(questions)} questions ({DRAW_SIZE} drawn per attempt) -> {path}")
    return True


def expand_bank(draft_text, lesson_id, topic, doc, api_key):
    """Expand an existing 5-question assessment to a full 12-question bank."""
    path = os.path.join(ASSESSMENTS_DIR, f"{lesson_id}.json")
    if not os.path.exists(path):
        print(f"  No existing assessment for {lesson_id} — running full generation instead")
        return run_assessment(draft_text, lesson_id, topic, doc, api_key)

    with open(path, encoding="utf-8") as f:
        existing = json.load(f)
    existing_qs = existing.get("questions", [])

    if len(existing_qs) >= BANK_SIZE:
        print(f"  {lesson_id}: already has {len(existing_qs)} questions — skipping")
        return True

    needed = BANK_SIZE - len(existing_qs)
    # Count existing types to determine what's missing
    type_counts = {t: 0 for t in QUESTION_TYPES}
    for q in existing_qs:
        t = q.get("type", "recall")
        type_counts[t] = type_counts.get(t, 0) + 1

    target_per_type = BANK_SIZE // len(QUESTION_TYPES)
    needed_types = []
    for t in QUESTION_TYPES:
        gap = target_per_type - type_counts.get(t, 0)
        needed_types.extend([t] * max(0, gap))
    needed_types = needed_types[:needed]

    course_label = "Creationeering" if doc == "creationeering" else "Mousetrap Build"
    existing_summary = "\n".join(
        f"  [{q.get('type','?')}] {q['question']}" for q in existing_qs
    )
    prompt = EXPAND_BANK_PROMPT.format(
        course=course_label,
        topic=topic,
        existing_count=len(existing_qs),
        existing_questions=existing_summary,
        needed=needed,
        needed_types=", ".join(needed_types),
        draft=draft_text[:6000],
    )
    new_qs = call_gemini(api_key, prompt)
    if not new_qs:
        print(f"  {lesson_id}: expansion failed")
        return False

    for i, q in enumerate(new_qs):
        if "type" not in q:
            q["type"] = needed_types[i] if i < len(needed_types) else "recall"

    all_questions = existing_qs + new_qs[:needed]
    path = save_assessment(lesson_id, topic, doc, all_questions)
    update_manifest(lesson_id, "done", path)
    print(f"  Expanded {lesson_id}: {len(existing_qs)} -> {len(all_questions)} questions")
    return True


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Assessment Agent")
    parser.add_argument("--draft-file",   help="Path to draft text file")
    parser.add_argument("--lesson-id",    help="Lesson ID (e.g. C-030)")
    parser.add_argument("--topic",        help="Lesson topic")
    parser.add_argument("--doc",          choices=["creationeering", "mousetrap"])
    parser.add_argument("--all-passed",   action="store_true",
                        help="Batch all QC-passed lessons missing banks")
    parser.add_argument("--expand-bank",  action="store_true",
                        help="Expand existing 5-question files to 12-question banks")
    parser.add_argument("--dry-run",      action="store_true")
    args = parser.parse_args()

    env     = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set")
        sys.exit(1)

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    # Expand-bank mode: grow existing 5-question files to 12
    if args.expand_bank:
        targets = [
            l for l in data["lessons"]
            if l.get("assessment_status") == "done"
        ]
        # Filter to those with < BANK_SIZE questions
        to_expand = []
        for l in targets:
            path = os.path.join(ASSESSMENTS_DIR, f"{l['id']}.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    existing = json.load(f)
                if len(existing.get("questions", [])) < BANK_SIZE:
                    to_expand.append(l)
        if not to_expand:
            print("All assessment banks already at target size.")
            return
        print(f"Expanding {len(to_expand)} banks to {BANK_SIZE} questions each\n")
        if args.dry_run:
            for l in to_expand:
                path = os.path.join(ASSESSMENTS_DIR, f"{l['id']}.json")
                with open(path, encoding="utf-8") as f:
                    existing = json.load(f)
                print(f"  [{l['id']}] {len(existing.get('questions',[]))} -> {BANK_SIZE}")
            return
        ok = fail = 0
        for i, lesson in enumerate(to_expand, 1):
            print(f"[{i}/{len(to_expand)}] {lesson['id']} — {lesson['tab']}")
            try:
                draft = read_from_google_doc(lesson)
                if expand_bank(draft, lesson["id"], lesson["topic"], lesson["doc"], api_key):
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                print(f"  Error: {e}")
                fail += 1
            if i < len(to_expand):
                time.sleep(3)
        print(f"\n=== Bank expansion: {ok} expanded, {fail} failed ===")
        return

    # Batch mode: generate banks for lessons missing assessments
    if args.all_passed:
        targets = [
            l for l in data["lessons"]
            if l["status"] == "done"
            and l.get("assessment_status") != "done"
        ]
        if not targets:
            print("No lessons are missing assessment banks.")
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
                time.sleep(3)
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
