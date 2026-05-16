"""
Genesis K-12 QC Agent

Reads a lesson draft and runs two checks:
  1. Structural check  — required sections, word count, framework keywords (no API call)
  2. Gemini quality check — reading level, faith integration, tone, accuracy

Flags lessons that fall short. Does NOT block the pipeline — PM agent logs and continues.

Usage (standalone):
  python qc_agent.py --draft-file path/to/draft.txt --lesson-id C-030 --doc creationeering --tab "What is Procurement?"
"""

import argparse, json, os, re, sys, urllib.request, urllib.error

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")

GEMINI_MODEL = "gemini-2.5-pro"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

REQUIRED_SECTIONS_CREATIONEERING = [
    "Lesson Overview",
    "Learning Objectives",
    "Key Vocabulary",
    "Engineering Journal",
    "Technical Documentation",
    "Summary of Key Concepts",
    "Works Cited",
]
REQUIRED_SECTIONS_MOUSETRAP = [
    "Lesson Overview",
    "Learning Objectives",
    "Key Vocabulary",
    "Engineering Journal",
    "Technical Documentation",
    "Summary of Key Concepts",
    "Works Cited",
]
REQUIRED_FRAMEWORKS = ["Creationeering", "Multiscale", "OCV"]
WORD_COUNT_RANGE = {
    "creationeering": (2000, 4000),
    "mousetrap":      (1800, 3500),
}

QC_PROMPT = """You are a curriculum quality reviewer for Genesis K-12 Academy's Middle School {course} course. Evaluate this lesson draft. Return ONLY a JSON object — no markdown, no other text.

Score each criterion 1 (poor), 2 (acceptable), or 3 (excellent):
- reading_level: Vocabulary and sentence complexity appropriate for 6th-8th grade
- faith_integration: Biblical content natural and meaningfully connected to the engineering topic
- framework_use: Creationeering phases, Multiscale Modeling, and OCV all correctly applied
- analogy_quality: Analogies are concrete and relatable for middle schoolers
- structure_complete: All required sections present and substantive

Set "pass" to true if overall >= 2 AND no individual score is 1.
Keep "notes" under 150 words — focus on the most important issues only.

Return exactly this format:
{{"reading_level": 0, "faith_integration": 0, "framework_use": 0, "analogy_quality": 0, "structure_complete": 0, "overall": 0, "pass": false, "notes": ""}}

DRAFT (first 6000 chars):
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


def structural_check(draft, doc):
    results = {}
    sections = REQUIRED_SECTIONS_CREATIONEERING if doc == "creationeering" else REQUIRED_SECTIONS_MOUSETRAP
    missing = [s for s in sections if s.lower() not in draft.lower()]
    results["missing_sections"] = missing

    frameworks_missing = [f for f in REQUIRED_FRAMEWORKS if f.lower() not in draft.lower()]
    results["missing_frameworks"] = frameworks_missing

    word_count = len(draft.split())
    lo, hi = WORD_COUNT_RANGE.get(doc, (2000, 4000))
    results["word_count"] = word_count
    results["word_count_ok"] = lo <= word_count <= hi

    results["has_scripture"] = bool(re.search(r"\d+:\d+", draft))
    results["has_signature"] = "Junior Creationeer" in draft

    results["structural_pass"] = (
        not missing
        and not frameworks_missing
        and results["word_count_ok"]
        and results["has_scripture"]
    )
    return results


def gemini_qc(api_key, draft, doc):
    course_label = "Creationeering" if doc == "creationeering" else "Mousetrap Build"
    prompt = QC_PROMPT.format(course=course_label, draft=draft[:15000])
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 1024}
        }
    }).encode("utf-8")

    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data["candidates"][0]["content"].get("parts", [])
        text_parts = [p["text"] for p in parts if not p.get("thought", False) and "text" in p]
        text = "\n".join(text_parts).strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # Find first JSON object in case thinking text precedes it
        start = text.find("{")
        if start > 0:
            text = text[start:]
        return json.loads(text)
    except Exception as e:
        return {"error": str(e), "pass": False, "notes": f"QC API error: {e}"}


def update_manifest(lesson_id, structural, gemini_result):
    if not os.path.exists(MANIFEST_PATH):
        return
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    passed = structural["structural_pass"] and gemini_result.get("pass", False)

    for m in data["lessons"]:
        if m["id"] == lesson_id:
            m["qc_status"] = "passed" if passed else "flagged"
            m["qc_scores"] = {k: gemini_result.get(k) for k in
                              ["reading_level", "faith_integration", "framework_use",
                               "analogy_quality", "structure_complete", "overall"]}
            m["qc_structural"] = {
                "word_count":         structural["word_count"],
                "missing_sections":   structural["missing_sections"],
                "missing_frameworks": structural["missing_frameworks"],
                "has_scripture":      structural["has_scripture"],
            }
            m["qc_notes"] = gemini_result.get("notes", "")
            break

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return passed


def run_qc(draft_text, lesson_id, doc, api_key):
    structural = structural_check(draft_text, doc)
    gemini_result = gemini_qc(api_key, draft_text, doc)
    passed = update_manifest(lesson_id, structural, gemini_result)

    print(f"  QC structural: {'PASS' if structural['structural_pass'] else 'FAIL'}"
          f"  words={structural['word_count']}"
          f"  missing_sections={structural['missing_sections'] or 'none'}"
          f"  missing_frameworks={structural['missing_frameworks'] or 'none'}")
    print(f"  QC Gemini:     {'PASS' if gemini_result.get('pass') else 'FLAGGED'}"
          f"  overall={gemini_result.get('overall', '?')}/3"
          f"  notes: {gemini_result.get('notes', '')[:120]}")

    return passed, structural, gemini_result


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 QC Agent")
    parser.add_argument("--draft-file",  required=True, help="Path to draft text file")
    parser.add_argument("--lesson-id",   required=True, help="Lesson ID (e.g. C-030)")
    parser.add_argument("--doc",         required=True, choices=["creationeering", "mousetrap"])
    parser.add_argument("--tab",         required=True, help="Tab title (for display)")
    args = parser.parse_args()

    if not os.path.exists(args.draft_file):
        print(f"Draft file not found: {args.draft_file}")
        sys.exit(1)

    with open(args.draft_file, encoding="utf-8") as f:
        draft_text = f.read()

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        sys.exit(1)

    print(f"QC: [{args.lesson_id}] {args.tab}")
    passed, _, _ = run_qc(draft_text, args.lesson_id, args.doc, api_key)
    sys.exit(0 if passed else 2)


if __name__ == "__main__":
    main()
