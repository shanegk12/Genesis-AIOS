"""
add_style_questions.py

Appends NEW-STYLE questions (multiple-answer, fill-in-the-blank, ordering) to
existing assessment banks so quizzes test more than single-answer recall.

Grounds the new questions on the bank's OWN existing questions/options/
explanations (which already encode the lesson's facts), so it needs only the
Gemini key — no Google Docs auth. Idempotent: skips banks that already contain
new-style questions unless --force.

Shapes written (consumed by the platform's QuizQuestionCard / quizGrading):
  multi: {"kind":"multi", options{A-D}, "answers":["A","C"], ...}
  fill:  {"kind":"fill",  "question":"... ___ ...", "blanks":[{"accepted":[...]}], ...}
  order: {"kind":"order", "items":[... correct order ...], ...}

Usage:
  python scripts/add_style_questions.py --doc mousetrap --limit 12 --dry-run
  python scripts/add_style_questions.py --doc mousetrap --limit 12 --save
  python scripts/add_style_questions.py --lesson M-001 --save --force
"""

import argparse, json, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from assessment_agent import load_env, call_gemini  # reuse Gemini plumbing

ASSESSMENTS_DIR = Path(__file__).parent / "assessments"
NEW_KINDS = {"multi", "fill", "order"}

PROMPT = """You are enriching a Genesis K-12 Academy Middle School quiz bank for the lesson "{topic}".

Below are the bank's EXISTING questions — they capture the facts this lesson teaches.
Using ONLY the facts evident in them, write exactly 4 NEW questions in richer formats:
  - 2 "multi"  (select-all-that-apply): 2 or 3 correct options out of A-D
  - 1 "fill"   (fill-in-the-blank): use "___" (three underscores) for each blank, 1-2 blanks
  - 1 "order"  (ordering): 4 items the student must put in the correct sequence

Rules:
- Test facts already covered by the existing questions; do NOT invent new facts.
- 6th-8th grade vocabulary. One-sentence explanations stating WHY.
- multi: exactly one set of correct options; make distractors plausible.
- fill: the "___" count MUST equal the number of entries in "blanks"; list 1-3 accepted
  answers per blank (include obvious synonyms). Keep blanked terms short (1-3 words).
- order: "items" MUST be listed in the CORRECT order; 4 items; each a short phrase.

Return ONLY a JSON array of exactly 4 objects, no markdown:
[
  {{"kind":"multi","type":"comprehension","question":"...?","options":{{"A":"...","B":"...","C":"...","D":"..."}},"answers":["A","C"],"explanation":"..."}},
  {{"kind":"multi","type":"application","question":"...?","options":{{"A":"...","B":"...","C":"...","D":"..."}},"answers":["B","D"],"explanation":"..."}},
  {{"kind":"fill","type":"recall","question":"A ___ converts rotational motion into ___ motion.","blanks":[{{"accepted":["wheel"]}},{{"accepted":["linear","straight-line"]}}],"explanation":"..."}},
  {{"kind":"order","type":"application","question":"Put these build steps in the correct order.","items":["First step","Second step","Third step","Fourth step"],"explanation":"..."}}
]

EXISTING QUESTIONS:
{existing}"""


def _summarize_existing(questions):
    lines = []
    for q in questions:
        opts = q.get("options", {})
        opt_str = " | ".join(f"{k}:{opts.get(k,'')}" for k in ("A", "B", "C", "D"))
        lines.append(f"- {q.get('question','')} [ans {q.get('answer','?')}] ({opt_str}) — {q.get('explanation','')}")
    return "\n".join(lines)[:6000]


def _valid_multi(q):
    opts = q.get("options", {})
    if not all(opts.get(k, "").strip() for k in ("A", "B", "C", "D")):
        return False
    ans = q.get("answers", [])
    return isinstance(ans, list) and 2 <= len(ans) <= 4 and all(a in ("A", "B", "C", "D") for a in ans)


def _valid_fill(q):
    n = len(re.findall(r"_{3,}", q.get("question", "")))
    blanks = q.get("blanks", [])
    if n == 0 or n != len(blanks):
        return False
    return all(isinstance(b.get("accepted"), list) and any(s.strip() for s in b["accepted"]) for b in blanks)


def _valid_order(q):
    items = q.get("items", [])
    return isinstance(items, list) and len(items) >= 3 and all(isinstance(x, str) and x.strip() for x in items)


def _normalize(q):
    """Coerce one generated question into the stored shape; return it or None if invalid."""
    kind = q.get("kind")
    q.setdefault("type", "comprehension")
    q.setdefault("explanation", "")
    # Every stored question carries an options object; new kinds leave it blank.
    q.setdefault("options", {"A": "", "B": "", "C": "", "D": ""})
    q.setdefault("answer", "")
    if kind == "multi":
        return q if _valid_multi(q) else None
    if kind == "fill":
        # collapse any run of underscores to exactly three
        q["question"] = re.sub(r"_{3,}", "___", q.get("question", ""))
        return q if _valid_fill(q) else None
    if kind == "order":
        return q if _valid_order(q) else None
    return None


def enrich(path, api_key, save, force):
    data = json.load(open(path, encoding="utf-8"))
    questions = data.get("questions", [])
    if not questions:
        print(f"  {path.stem}: empty bank — skip"); return "skip"
    if not force and any(q.get("kind") in NEW_KINDS for q in questions):
        print(f"  {path.stem}: already has new-style questions — skip"); return "skip"

    prompt = PROMPT.format(topic=data.get("topic", path.stem), existing=_summarize_existing(questions))
    gen = call_gemini(api_key, prompt)
    if not gen:
        print(f"  {path.stem}: generation failed"); return "fail"

    new = [nq for nq in (_normalize(g) for g in gen) if nq]
    if not new:
        print(f"  {path.stem}: no valid new-style questions returned"); return "fail"

    counts = {}
    for nq in new:
        counts[nq["kind"]] = counts.get(nq["kind"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in counts.items())

    if not save:
        print(f"  [dry-run] {path.stem}: would add {len(new)} ({summary}) -> {len(questions)+len(new)} total")
        return "ok"

    data["questions"] = questions + new
    json.dump(data, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  {path.stem}: +{len(new)} ({summary}) -> {len(data['questions'])} total")
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", choices=["mousetrap", "creationeering"], help="Filter by course (M- / C-)")
    ap.add_argument("--lesson", help="Single lesson ID, e.g. M-001")
    ap.add_argument("--limit", type=int, help="Cap number of banks processed")
    ap.add_argument("--save", action="store_true", help="Write changes (default dry-run)")
    ap.add_argument("--force", action="store_true", help="Re-enrich banks that already have new-style questions")
    args = ap.parse_args()

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set"); sys.exit(1)

    if args.lesson:
        files = [ASSESSMENTS_DIR / f"{args.lesson}.json"]
    else:
        prefix = {"mousetrap": "M-", "creationeering": "C-"}.get(args.doc, "")
        files = sorted(ASSESSMENTS_DIR.glob(f"{prefix}*.json"))
    if args.limit:
        files = files[:args.limit]
    if not files:
        print("No matching assessment files."); sys.exit(1)

    print(f"{'[DRY RUN] ' if not args.save else ''}Enriching {len(files)} bank(s) with new-style questions\n")
    tally = {"ok": 0, "fail": 0, "skip": 0}
    for i, path in enumerate(files, 1):
        if not path.exists():
            print(f"  {path.stem}: not found — skip"); tally["skip"] += 1; continue
        print(f"[{i}/{len(files)}] {path.stem}")
        try:
            tally[enrich(path, api_key, args.save, args.force)] += 1
        except Exception as e:
            print(f"  {path.stem}: error {e}"); tally["fail"] += 1
        if i < len(files):
            time.sleep(2)
    print(f"\n=== {'DRY RUN ' if not args.save else ''}done: {tally['ok']} enriched, {tally['fail']} failed, {tally['skip']} skipped ===")


if __name__ == "__main__":
    main()
