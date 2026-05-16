"""
Genesis K-12 Re-QC Agent

Re-runs QC on flagged lessons by reading content directly from Google Docs.
Fixes lessons where QC scores show overall=?/3 due to the manifest overwrite bug.

Usage:
  python rerun_qc.py                          # re-QC all lessons with missing scores
  python rerun_qc.py --ids C-030 C-031        # re-QC specific lessons
  python rerun_qc.py --all-flagged            # re-QC all flagged lessons (including those with existing scores)
  python rerun_qc.py --dry-run                # list targets without running QC
"""

import argparse, json, os, sys, time

import google.auth
from googleapiclient.discovery import build

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")

DOC_IDS = {
    "creationeering": "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY",
    "mousetrap":      "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc",
}

sys.path.insert(0, os.path.dirname(__file__))
from qc_agent import structural_check, gemini_qc, update_manifest, load_env


def get_docs_service():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/documents.readonly"])
    return build("docs", "v1", credentials=creds)


def extract_text_from_tab(tab):
    body = tab.get("documentTab", {}).get("body", {})
    parts = []
    for element in body.get("content", []):
        paragraph = element.get("paragraph", {})
        for pe in paragraph.get("elements", []):
            tr = pe.get("textRun", {})
            parts.append(tr.get("content", ""))
    return "".join(parts)


def read_tab_content(doc_id, tab_title):
    svc = get_docs_service()
    req = svc.documents().get(documentId=doc_id)
    req.uri += "&includeTabsContent=true"
    doc = req.execute()

    for tab in doc.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == tab_title.strip().lower():
            return extract_text_from_tab(tab)

    available = [t.get("tabProperties", {}).get("title") for t in doc.get("tabs", [])]
    raise ValueError(f"Tab '{tab_title}' not found. Available: {available}")


def main():
    parser = argparse.ArgumentParser(description="Re-run QC on flagged lessons")
    parser.add_argument("--ids",         nargs="*", help="Specific lesson IDs to re-QC")
    parser.add_argument("--all-flagged", action="store_true",
                        help="Re-QC all flagged lessons, even those with existing scores")
    parser.add_argument("--dry-run",     action="store_true", help="List targets, no API calls")
    args = parser.parse_args()

    with open(MANIFEST_PATH, encoding="utf-8") as f:
        data = json.load(f)

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        sys.exit(1)

    if args.ids:
        targets = [l for l in data["lessons"] if l["id"] in args.ids and l["status"] == "done"]
    elif args.all_flagged:
        targets = [l for l in data["lessons"] if l.get("qc_status") == "flagged" and l["status"] == "done"]
    else:
        # Default: lessons flagged with missing/null overall score
        targets = [
            l for l in data["lessons"]
            if l.get("qc_status") == "flagged"
            and l["status"] == "done"
            and l.get("qc_scores", {}).get("overall") is None
        ]

    if not targets:
        print("No lessons match the target criteria.")
        return

    print(f"Re-QC targets: {len(targets)} lessons\n")

    if args.dry_run:
        for l in targets:
            print(f"  [{l['id']}] {l['tab']}  ({l['doc']})")
        return

    passed = failed = errors = 0

    for i, lesson in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {lesson['id']} — {lesson['tab']}")
        doc_id = DOC_IDS[lesson["doc"]]

        try:
            content = read_tab_content(doc_id, lesson["tab"])
            if len(content.strip()) < 200:
                print(f"  WARNING: tab content too short ({len(content)} chars) — may be empty. Skipping.")
                errors += 1
                continue

            print(f"  Read {len(content):,} chars from Google Doc")

            structural = structural_check(content, lesson["doc"])
            gemini_result = gemini_qc(api_key, content, lesson["doc"])
            ok = update_manifest(lesson["id"], structural, gemini_result)

            print(f"  Structural: {'PASS' if structural['structural_pass'] else 'FAIL'}"
                  f"  words={structural['word_count']}"
                  f"  missing_sections={structural['missing_sections'] or 'none'}"
                  f"  missing_frameworks={structural['missing_frameworks'] or 'none'}")
            print(f"  Gemini:     {'PASS' if gemini_result.get('pass') else 'FLAGGED'}"
                  f"  overall={gemini_result.get('overall', '?')}/3"
                  f"  notes: {gemini_result.get('notes', '')[:150]}")

            if ok:
                passed += 1
                print(f"  => PASSED")
            else:
                failed += 1
                print(f"  => FLAGGED (needs review)")

        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

        # Brief pause between Gemini calls to avoid rate limiting
        if i < len(targets):
            time.sleep(2)

        print()

    print(f"=== Re-QC complete: {passed} passed, {failed} still flagged, {errors} errors ===")


if __name__ == "__main__":
    main()
