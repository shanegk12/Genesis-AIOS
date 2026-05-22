"""
Genesis K-12 Pipeline Worker — Cloud Run Service

Replaces the Cloud Run Job with an always-on Flask service that fans out
one Cloud Task per lesson, enabling parallel lesson processing.

Endpoints:
  GET  /health    — health check (no auth)
  POST /dispatch  — read manifest, enqueue one Cloud Task per pending lesson
  POST /process   — run all pipeline steps for one lesson (called by Cloud Tasks)
  POST /finalize  — git-commit manifest + send completion notification

Setup (run once after first deploy):
  # Create Cloud Tasks queue
  gcloud tasks queues create lesson-pipeline \
    --location=us-central1 \
    --max-concurrent-dispatches=5 \
    --max-attempts=3 \
    --min-backoff=60s \
    --max-backoff=300s \
    --project=genesis-aios

  # Update Cloud Scheduler to call /dispatch instead of running the Job
  gcloud scheduler jobs update http gk12-daily-pipeline \
    --location=us-central1 \
    --uri="https://<SERVICE_URL>/dispatch" \
    --http-method=POST \
    --headers="Authorization=Bearer <PIPELINE_KEY>,Content-Type=application/json" \
    --message-body='{"course":"both","batch":20,"lesson_type":"all"}' \
    --project=genesis-aios

  # Add PIPELINE_KEY and WORKER_URL secrets to the Cloud Run service
  echo -n "xVR-qEcAJrJD-w7V88cHIqT31A8qdedEqhW5MRGsfUI" | \
    gcloud secrets create PIPELINE_KEY --data-file=- --project=genesis-aios
  echo -n "https://<SERVICE_URL>" | \
    gcloud secrets create WORKER_URL --data-file=- --project=genesis-aios
"""

import json
import logging
import os
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify

SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT   = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))
import pm_agent  # noqa: E402 — must follow sys.path insert

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PIPELINE_KEY    = os.environ.get("PIPELINE_KEY", "")
PROJECT_ID      = "genesis-aios"
LOCATION        = "us-central1"
QUEUE_NAME      = "lesson-pipeline"
WORKER_URL      = os.environ.get("WORKER_URL", "")

_manifest_lock = threading.Lock()


# ── Auth ──────────────────────────────────────────────────────────────────────

def authorized(req) -> bool:
    return req.headers.get("Authorization", "") == f"Bearer {PIPELINE_KEY}"


# ── Manifest ──────────────────────────────────────────────────────────────────

def update_lesson_status(lesson_id: str, status: str, error: str | None = None):
    """Thread-safe, atomic manifest update with retry for write conflicts."""
    manifest_path = str(pm_agent.MANIFEST_PATH)
    for attempt in range(5):
        try:
            with _manifest_lock:
                data = pm_agent.load_manifest()
                for lesson in data["lessons"]:
                    if lesson["id"] == lesson_id:
                        lesson["status"]       = status
                        lesson["completed_at"] = datetime.now(timezone.utc).isoformat()
                        lesson["error"]        = error
                        break
                tmp = manifest_path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, manifest_path)
            return
        except Exception as exc:
            if attempt == 4:
                logging.error(f"Manifest update failed for {lesson_id}: {exc}")
            time.sleep(0.2 * (attempt + 1))


# ── Git ───────────────────────────────────────────────────────────────────────

def git_pull():
    import subprocess
    try:
        subprocess.run(
            ["git", "pull", "origin", "main", "--rebase"],
            cwd=str(REPO_ROOT), check=True, capture_output=True,
        )
        logging.info("git pull OK")
    except Exception as e:
        logging.warning(f"git pull (non-fatal): {e}")


# ── Health ────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "gk12-pipeline-worker"})


# ── Dispatch ──────────────────────────────────────────────────────────────────

@app.route("/dispatch", methods=["POST"])
def dispatch():
    """Read manifest, enqueue one Cloud Task per pending lesson, return immediately."""
    if not authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    body        = request.get_json(silent=True) or {}
    course      = body.get("course", "both")
    batch       = int(body.get("batch", 20))
    lesson_type = body.get("lesson_type", "all")
    flags       = body.get("flags", {
        "generate_interactives": True,
        "generate_assessments":  True,
        "generate_scorm":        True,
        "generate_images":       True,
        "import_to_platform":    True,
    })

    # Pull fresh manifest so we pick up any hand-edits or previous run results
    git_pull()

    data  = pm_agent.load_manifest()
    queue = pm_agent.build_queue(data, course, lesson_type, batch)

    if not queue:
        return jsonify({"ok": True, "queued": 0, "message": "No pending lessons"})

    # Upload Horstemeyer PDF once; URI shared across all tasks (valid 48 h)
    env     = pm_agent.load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    horstemeyer_uri = pm_agent.upload_horstemeyer_to_gemini(api_key) if api_key else None

    if not WORKER_URL:
        return jsonify({"error": "WORKER_URL not configured on this service"}), 500

    from google.cloud import tasks_v2
    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(PROJECT_ID, LOCATION, QUEUE_NAME)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    pm_agent.notify_morning(len(queue), batch)

    queued = []
    failed = []

    for lesson in queue:
        payload = json.dumps({
            "lessonId":       lesson["id"],
            "runId":          run_id,
            "flags":          flags,
            "horstemeyrUri":  horstemeyer_uri,
            "key":            PIPELINE_KEY,
        }).encode("utf-8")

        # Task name is idempotent per lesson per run — prevents duplicate enqueue
        safe_id   = lesson["id"].lower().replace("-", "")
        task_name = client.task_path(
            PROJECT_ID, LOCATION, QUEUE_NAME,
            f"lesson-{safe_id}-{run_id}",
        )
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url":         f"{WORKER_URL}/process",
                "headers":     {"Content-Type": "application/json"},
                "body":        payload,
            },
            "name": task_name,
        }

        try:
            client.create_task(request={"parent": parent, "task": task})
            queued.append(lesson["id"])
            logging.info(f"Queued: {lesson['id']}")
        except Exception as e:
            logging.error(f"Enqueue failed for {lesson['id']}: {e}")
            failed.append(lesson["id"])

    return jsonify({
        "ok":      True,
        "runId":   run_id,
        "queued":  len(queued),
        "failed":  len(failed),
        "lessons": queued,
    })


# ── Process ───────────────────────────────────────────────────────────────────

@app.route("/process", methods=["POST"])
def process():
    """Run all pipeline steps for one lesson. Called by Cloud Tasks."""
    body = request.get_json(silent=True) or {}

    if body.get("key") != PIPELINE_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    lesson_id       = body.get("lessonId")
    flags           = body.get("flags", {})
    horstemeyer_uri = body.get("horstemeyrUri")

    if not lesson_id:
        return jsonify({"error": "lessonId required"}), 400

    data   = pm_agent.load_manifest()
    lesson = pm_agent.find_lesson(data, lesson_id)
    if not lesson:
        return jsonify({"error": f"Lesson {lesson_id} not found"}), 404

    logging.info(f"Start: {lesson_id} — {lesson.get('tab', '')}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
        draft_path = tf.name

    try:
        # 1. Dev agent
        success, output = pm_agent.run_dev_agent(lesson, draft_path, horstemeyer_uri=horstemeyer_uri)
        if not success:
            update_lesson_status(lesson_id, "failed", error=output[-500:])
            logging.warning(f"Dev agent failed: {lesson_id}")
            return jsonify({"ok": False, "lessonId": lesson_id, "status": "failed"})

        update_lesson_status(lesson_id, "done")

        # 2. QC
        if not flags.get("skip_qc") and os.path.exists(draft_path):
            pm_agent.run_qc_agent(draft_path, lesson)

        # 3. Media
        if not flags.get("skip_media") and os.path.exists(draft_path):
            pm_agent.run_media_agent(draft_path, lesson)

        # 4. Interactives
        if flags.get("generate_interactives") and os.path.exists(draft_path):
            pm_agent.run_interactive_agent(
                draft_path, lesson,
                skip_concept=flags.get("interactives_no_concept", False),
            )

        # 5. Assessments (QC-passed only)
        if flags.get("generate_assessments") and os.path.exists(draft_path):
            data_fresh   = pm_agent.load_manifest()
            lesson_fresh = pm_agent.find_lesson(data_fresh, lesson_id)
            if lesson_fresh and lesson_fresh.get("qc_status") == "passed":
                pm_agent.run_assessment_agent(draft_path, lesson)

        # 6. SCORM
        if flags.get("generate_scorm"):
            pm_agent.run_scorm_packager(lesson_id)

        # 7. Images
        if flags.get("generate_images") and not flags.get("skip_media"):
            pm_agent.run_image_agent(lesson_id=lesson_id)

        # 8–11. Platform import → format QC → reformat → dev fix
        if flags.get("import_to_platform"):
            imported = pm_agent.run_platform_import(lesson_id)
            if imported:
                pm_agent.run_format_qc(lesson_id)
                fmt_status = pm_agent._read_format_qc_status(lesson_id)

                if fmt_status == "needs_reformat":
                    pm_agent.run_reformat_agent(lesson_id)
                    pm_agent.run_format_qc(lesson_id)
                    fmt_status = pm_agent._read_format_qc_status(lesson_id)

                if fmt_status == "needs_fix":
                    pm_agent.run_dev_fix_agent(lesson_id)

        logging.info(f"Done: {lesson_id}")
        return jsonify({"ok": True, "lessonId": lesson_id, "status": "done"})

    except Exception:
        tb = traceback.format_exc()
        logging.error(f"Error processing {lesson_id}:\n{tb}")
        update_lesson_status(lesson_id, "failed", error=tb[-500:])
        return jsonify({"ok": False, "lessonId": lesson_id, "error": tb[-200:]}), 500

    finally:
        if os.path.exists(draft_path):
            os.unlink(draft_path)


# ── Finalize ──────────────────────────────────────────────────────────────────

@app.route("/finalize", methods=["POST"])
def finalize():
    """Git-commit updated manifest and send completion notification."""
    if not authorized(request):
        return jsonify({"error": "Unauthorized"}), 401

    pm_agent.git_push_manifest()

    data   = pm_agent.load_manifest()
    done   = sum(1 for l in data["lessons"] if l["status"] == "done")
    failed = sum(1 for l in data["lessons"] if l["status"] == "failed")
    pm_agent.notify(f"GK12 pipeline complete: {done} done, {failed} failed")

    return jsonify({"ok": True, "done": done, "failed": failed})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # threaded=True lets Flask handle concurrent /process calls on one instance
    app.run(host="0.0.0.0", port=port, threaded=True)
