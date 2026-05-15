"""
Genesis K-12 PM Agent — Lesson Draft Orchestrator

Coordinates three agents per lesson:
  1. Dev agent    (lesson_pipeline.py) — calls Gemini, writes to Google Doc
  2. QC agent     (qc_agent.py)        — structural + quality check, flags issues
  3. Media agent  (media_agent.py)     — generates image prompts → media_prompts.json

Usage:
  python pm_agent.py                          # draft all pending Creationeering lessons
  python pm_agent.py --course mousetrap       # draft pending Mousetrap lessons
  python pm_agent.py --course both            # draft both courses
  python pm_agent.py --batch 5               # process only 5 lessons this run
  python pm_agent.py --type all              # include build and activity types
  python pm_agent.py --skip-qc               # skip QC agent
  python pm_agent.py --skip-media            # skip media agent
  python pm_agent.py --dry-run               # preview queue without drafting
  python pm_agent.py --status                # show progress summary
  python pm_agent.py --retry-failed          # re-queue failed lessons
"""

import argparse, json, os, subprocess, sys, tempfile, urllib.request, urllib.error
from datetime import datetime, timezone

MANIFEST_PATH      = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
REPO_ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_SCRIPT    = os.path.join(os.path.dirname(__file__), "lesson_pipeline.py")
HORSTEMEYER_PDF    = os.path.join(REPO_ROOT, "references", "horstemeyer-2022.pdf")
GEMINI_UPLOAD_URL  = "https://generativelanguage.googleapis.com/upload/v1beta/files"
QC_SCRIPT       = os.path.join(os.path.dirname(__file__), "qc_agent.py")
MEDIA_SCRIPT    = os.path.join(os.path.dirname(__file__), "media_agent.py")
IMAGE_SCRIPT    = os.path.join(os.path.dirname(__file__), "image_agent.py")
NOTIFY_SCRIPT   = os.path.join(os.path.dirname(__file__), "notify.py")


def load_env():
    env_path = os.path.join(REPO_ROOT, ".env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def upload_horstemeyer_to_gemini(api_key):
    """Upload Horstemeyer 2022 PDF to Gemini File API. Returns file URI (valid 48h)."""
    if not os.path.exists(HORSTEMEYER_PDF):
        print(f"Warning: Horstemeyer PDF not found at {HORSTEMEYER_PDF}. Proceeding without file reference.")
        return None
    with open(HORSTEMEYER_PDF, "rb") as f:
        pdf_bytes = f.read()
    boundary = "boundary_gk12_horstemeyer_2022"
    metadata = json.dumps({"file": {"display_name": "Horstemeyer 2022 Creationeering"}}).encode("utf-8")
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n".encode()
        + metadata
        + f"\r\n--{boundary}\r\nContent-Type: application/pdf\r\n\r\n".encode()
        + pdf_bytes
        + f"\r\n--{boundary}--".encode()
    )
    url = f"{GEMINI_UPLOAD_URL}?key={api_key}&uploadType=multipart"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        uri = result["file"]["uri"]
        print(f"Horstemeyer PDF uploaded: {uri}")
        return uri
    except Exception as e:
        print(f"Warning: Horstemeyer PDF upload failed ({e}). Proceeding without file reference.")
        return None


def load_manifest():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(data):
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def find_lesson(data, lesson_id):
    for m in data["lessons"]:
        if m["id"] == lesson_id:
            return m
    return None


def mark(data, lesson_id, status, error=None):
    m = find_lesson(data, lesson_id)
    if m:
        m["status"] = status
        m["completed_at"] = datetime.now(timezone.utc).isoformat()
        m["error"] = error
    save_manifest(data)


def run_dev_agent(lesson, draft_out_path, horstemeyer_uri=None):
    cmd = [
        sys.executable, PIPELINE_SCRIPT,
        "--doc",       lesson["doc"],
        "--tab",       lesson["tab"],
        "--topic",     lesson["topic"],
        "--phase",     lesson["phase"],
        "--prev",      lesson["prev"],
        "--draft-out", draft_out_path,
    ]
    if horstemeyer_uri:
        cmd += ["--horstemeyer-uri", horstemeyer_uri]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def run_qc_agent(draft_path, lesson):
    cmd = [
        sys.executable, QC_SCRIPT,
        "--draft-file", draft_path,
        "--lesson-id",  lesson["id"],
        "--doc",        lesson["doc"],
        "--tab",        lesson["tab"],
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if output:
        for line in output.splitlines():
            print(f"    {line}")
    passed = result.returncode == 0
    return passed


def run_media_agent(draft_path, lesson):
    cmd = [
        sys.executable, MEDIA_SCRIPT,
        "--draft-file", draft_path,
        "--lesson-id",  lesson["id"],
        "--topic",      lesson["topic"],
        "--doc",        lesson["doc"],
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if output:
        for line in output.splitlines():
            print(f"    {line}")
    return result.returncode == 0


def run_image_agent(lesson_id=None, rework_flagged=False):
    cmd = [sys.executable, IMAGE_SCRIPT]
    if lesson_id:
        cmd += ["--lesson-id", lesson_id]
    if rework_flagged:
        cmd += ["--rework-flagged"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if output:
        for line in output.splitlines():
            print(f"    {line}")
    return result.returncode == 0


def notify(message):
    if os.path.exists(NOTIFY_SCRIPT):
        subprocess.run([sys.executable, NOTIFY_SCRIPT, message], check=False)


def git_push_manifest():
    try:
        subprocess.run(
            ["git", "add", "scripts/lessons_manifest.json", "scripts/media_prompts.json"],
            cwd=REPO_ROOT, check=True, capture_output=True
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=REPO_ROOT, capture_output=True
        )
        if diff.returncode != 0:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            subprocess.run(
                ["git", "commit", "-m", f"pipeline: manifest update {today}"],
                cwd=REPO_ROOT, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=REPO_ROOT, check=True, capture_output=True
            )
            print("Manifest pushed to GitHub.")
        else:
            print("No manifest changes to push.")
    except subprocess.CalledProcessError as e:
        print(f"Git push failed (non-fatal): {e}")


def print_status(data):
    by_doc = {}
    for l in data["lessons"]:
        key = l["doc"]
        by_doc.setdefault(key, {"pending": 0, "done": 0, "failed": 0, "skipped": 0, "qc_flagged": 0})
        st = l["status"]
        by_doc[key][st] = by_doc[key].get(st, 0) + 1
        if l.get("qc_status") == "flagged":
            by_doc[key]["qc_flagged"] += 1

    print("\n=== Manifest Status ===")
    total_done = total_pending = total_failed = total_flagged = 0
    for doc, counts in sorted(by_doc.items()):
        done     = counts.get("done",    0)
        pending  = counts.get("pending", 0)
        failed   = counts.get("failed",  0)
        skipped  = counts.get("skipped", 0)
        flagged  = counts.get("qc_flagged", 0)
        total    = done + pending + failed + skipped
        print(f"  {doc:20s}  done={done}  pending={pending}  failed={failed}"
              f"  skipped={skipped}  qc_flagged={flagged}  total={total}")
        total_done    += done
        total_pending += pending
        total_failed  += failed
        total_flagged += flagged

    print(f"  {'TOTAL':20s}  done={total_done}  pending={total_pending}"
          f"  failed={total_failed}  qc_flagged={total_flagged}")

    if total_failed:
        print("\nFailed lessons:")
        for l in data["lessons"]:
            if l["status"] == "failed":
                print(f"  [{l['id']}] {l['tab']}")
                if l.get("error"):
                    print(f"    {l['error'][:200]}")

    flagged_lessons = [l for l in data["lessons"] if l.get("qc_status") == "flagged"]
    if flagged_lessons:
        print(f"\nQC-flagged lessons ({len(flagged_lessons)}) — review before publishing:")
        for l in flagged_lessons:
            score = l.get("qc_scores", {}).get("overall", "?")
            notes = l.get("qc_notes", "")[:100]
            print(f"  [{l['id']}] {l['tab']}  overall={score}/3  {notes}")


def build_queue(data, course, lesson_type, batch):
    queue = [l for l in data["lessons"] if l["status"] == "pending"]

    if course != "both":
        queue = [l for l in queue if l["doc"] == course]

    if lesson_type != "all":
        queue = [l for l in queue if l["type"] == lesson_type]

    queue.sort(key=lambda l: (l["doc"], l["tab_number"]))

    if batch:
        queue = queue[:batch]

    return queue


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 PM Agent")
    parser.add_argument("--course",    choices=["creationeering", "mousetrap", "both"],
                        default="creationeering")
    parser.add_argument("--batch",     type=int, default=0,
                        help="Max lessons to process this run (0 = all pending)")
    parser.add_argument("--type",      dest="lesson_type", default="lesson",
                        choices=["lesson", "build", "activity", "all"])
    parser.add_argument("--skip-qc",         action="store_true", help="Skip QC agent")
    parser.add_argument("--skip-media",      action="store_true", help="Skip media agent")
    parser.add_argument("--generate-images", action="store_true",
                        help="Run image agent after media (slow — generates images via Gemini)")
    parser.add_argument("--dry-run",   action="store_true", help="Preview queue, no drafting")
    parser.add_argument("--status",    action="store_true", help="Print progress summary and exit")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Re-queue failed lessons as pending")
    args = parser.parse_args()

    data = load_manifest()

    if args.status:
        print_status(data)
        return

    if args.retry_failed:
        count = 0
        for l in data["lessons"]:
            if l["status"] == "failed":
                l["status"] = "pending"
                l["error"] = None
                count += 1
        save_manifest(data)
        print(f"{count} failed lessons re-queued as pending.")
        return

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    horstemeyer_uri = upload_horstemeyer_to_gemini(api_key.strip()) if api_key.strip() else None

    queue = build_queue(data, args.course, args.lesson_type, args.batch)

    if not queue:
        print("No pending lessons match the filter. Run --status to check progress.")
        return

    skipped_count = len([
        l for l in data["lessons"]
        if l["status"] == "pending"
        and (args.course == "both" or l["doc"] == args.course)
        and l["type"] != args.lesson_type
        and args.lesson_type != "all"
    ])

    print(f"\nCourse:  {args.course}")
    print(f"Type:    {args.lesson_type}")
    print(f"Queue:   {len(queue)} lessons to draft")
    if skipped_count:
        print(f"Skipped: {skipped_count} build/activity tabs (use --type all to include)")
    if not args.skip_qc:
        print("QC:      enabled (flag-only mode)")
    if not args.skip_media:
        print("Media:   enabled -> media_prompts.json")
    if args.generate_images:
        print("Images:  enabled -> Gemini + Drive")

    if args.dry_run:
        print("\nDry run — no drafts will be written:\n")
        for l in queue:
            print(f"  [{l['id']:6s}] {l['doc']:15s} tab {l['tab_number']:3d} | {l['tab']}")
        return

    print()
    done = failed = qc_flagged = media_failed = image_failed = 0

    for i, lesson in enumerate(queue, 1):
        print(f"[{i}/{len(queue)}] {lesson['id']} — {lesson['tab']}")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
            draft_path = tf.name

        try:
            # 1. Dev agent
            success, output = run_dev_agent(lesson, draft_path, horstemeyer_uri=horstemeyer_uri)
            print(output.strip())

            if not success:
                mark(data, lesson["id"], "failed", error=output[-500:])
                failed += 1
                print(f"  !! Dev agent failed. Moving to next lesson.\n")
                continue

            mark(data, lesson["id"], "done")
            done += 1

            # 2. QC agent
            if not args.skip_qc and os.path.exists(draft_path):
                qc_passed = run_qc_agent(draft_path, lesson)
                if not qc_passed:
                    qc_flagged += 1
                    m = find_lesson(data, lesson["id"])
                    if m:
                        m["qc_status"] = "flagged"
                    save_manifest(data)

            # 3. Media agent
            if not args.skip_media and os.path.exists(draft_path):
                if not run_media_agent(draft_path, lesson):
                    media_failed += 1

            # 4. Image agent (opt-in via --generate-images)
            if args.generate_images and not args.skip_media:
                if not run_image_agent(lesson_id=lesson["id"]):
                    image_failed += 1

        finally:
            if os.path.exists(draft_path):
                os.unlink(draft_path)

        print()

    # Rework any QC-flagged images from this batch
    if args.generate_images and not args.skip_media:
        print("\n--- Reworking flagged images ---")
        run_image_agent(rework_flagged=True)

    summary_parts = [f"{done} drafted", f"{failed} failed"]
    if not args.skip_qc:
        summary_parts.append(f"{qc_flagged} QC-flagged")
    if not args.skip_media:
        summary_parts.append(f"{media_failed} media errors")
    if args.generate_images:
        summary_parts.append(f"{image_failed} image errors")

    summary = f"GK12 pipeline ({args.course}): " + ", ".join(summary_parts)
    print(f"=== {summary} ===")
    notify(summary)

    if done > 0:
        git_push_manifest()


if __name__ == "__main__":
    main()
