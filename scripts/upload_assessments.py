"""
upload_assessments.py

Uploads backed-up assessment JSON files to the live platform via the admin API.
Sets the assessmentJson field on each lesson document.

Also supports generating missing banks for lessons without local files.

Usage:
  python scripts/upload_assessments.py --dry-run       # list what would upload
  python scripts/upload_assessments.py --save          # upload all local assessment files
  python scripts/upload_assessments.py --lesson C-030  # single lesson
  python scripts/upload_assessments.py --save --expand # upload + expand 5→12 before uploading
"""

import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

ASSESSMENTS_DIR = Path(__file__).parent / "assessments"
MANIFEST_PATH   = Path(__file__).parent / "lessons_manifest.json"
LIVE_URL        = "https://gk12academy.com"

DRAW_SIZE = 5   # questions drawn per quiz attempt (stored on the lesson for QuizEngine)


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


def get_platform_key(env: dict) -> str:
    return env.get("PIPELINE_KEY") or env.get("PLATFORM_KEY", "")


def upload_assessment(lesson_id: str, assessment: dict, key: str, save: bool) -> bool:
    """PATCH assessmentJson onto a lesson via the admin API."""
    payload = json.dumps({
        "assessmentJson": json.dumps(assessment),
        "assessmentDrawSize": DRAW_SIZE,
    }).encode("utf-8")

    url = f"{LIVE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(
        url, data=payload, method="PATCH",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    if not save:
        print(f"  [dry-run] Would upload {len(assessment['questions'])} questions -> {lesson_id}")
        return True
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")[:200]
        print(f"  HTTP {e.code} on {lesson_id}: {body}")
        return False
    except Exception as e:
        print(f"  Error on {lesson_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save",    action="store_true", help="Actually upload (default: dry-run)")
    parser.add_argument("--lesson",  help="Single lesson ID")
    parser.add_argument("--expand",  action="store_true",
                        help="Run expand-bank before uploading (requires Gemini key)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = load_env()
    key = get_platform_key(env)
    if not key and args.save:
        print("Error: PIPELINE_KEY or PLATFORM_KEY not set in .env")
        sys.exit(1)

    save = args.save and not args.dry_run

    # Collect assessment files to upload
    if args.lesson:
        files = [ASSESSMENTS_DIR / f"{args.lesson}.json"]
    else:
        files = sorted(ASSESSMENTS_DIR.glob("*.json"))

    if not files:
        print("No assessment files found in scripts/assessments/")
        sys.exit(1)

    print(f"{'[DRY RUN] ' if not save else ''}Uploading {len(files)} assessment(s)...\n")

    ok = fail = skip = 0
    for i, path in enumerate(files, 1):
        if not path.exists():
            print(f"  [{path.stem}] file not found — skipping")
            skip += 1
            continue

        with open(path, encoding="utf-8") as f:
            assessment = json.load(f)

        q_count = len(assessment.get("questions", []))
        lesson_id = assessment.get("lesson_id") or path.stem

        print(f"[{i}/{len(files)}] {lesson_id} — {q_count} questions")

        if upload_assessment(lesson_id, assessment, key, save):
            ok += 1
        else:
            fail += 1

        if save and i < len(files):
            time.sleep(0.3)  # avoid hammering the API

    print(f"\n{'[DRY RUN] ' if not save else ''}=== Upload complete: {ok} uploaded, {fail} failed, {skip} skipped ===")
    if not save:
        print("Run with --save to execute uploads.")


if __name__ == "__main__":
    main()
