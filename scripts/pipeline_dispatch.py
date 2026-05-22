"""
Genesis K-12 Pipeline Dispatch — Local CLI trigger

Calls the Cloud Run service's /dispatch endpoint to kick off a pipeline run
without waiting for the daily Cloud Scheduler. Useful for manual reruns and testing.

Usage:
  python scripts/pipeline_dispatch.py                          # dispatch all pending (both courses)
  python scripts/pipeline_dispatch.py --batch 5               # dispatch first 5 lessons
  python scripts/pipeline_dispatch.py --course creationeering
  python scripts/pipeline_dispatch.py --dry-run               # preview queue, no dispatch
  python scripts/pipeline_dispatch.py --finalize              # trigger git-push + notification
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pm_agent


def load_env() -> dict:
    env = {}
    for name in [".env", ".env.local"]:
        path = Path(__file__).parent.parent / name
        if path.exists():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip().strip('"\'')
    return env


def call(url: str, pipeline_key: str, body: dict) -> dict:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Bearer {pipeline_key}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser(description="Dispatch pipeline tasks to Cloud Run worker")
    parser.add_argument("--course",      default="both",
                        choices=["creationeering", "mousetrap", "both"])
    parser.add_argument("--batch",       type=int, default=20)
    parser.add_argument("--type",        dest="lesson_type", default="all")
    parser.add_argument("--worker-url",  help="Override WORKER_URL env var")
    parser.add_argument("--dry-run",     action="store_true",
                        help="Preview queue locally without dispatching")
    parser.add_argument("--finalize",    action="store_true",
                        help="Call /finalize instead of /dispatch")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--skip-scorm",  action="store_true")
    args = parser.parse_args()

    env          = load_env()
    pipeline_key = os.environ.get("PIPELINE_KEY") or env.get("PIPELINE_KEY", "")
    worker_url   = (args.worker_url
                    or os.environ.get("WORKER_URL")
                    or env.get("WORKER_URL", ""))

    if args.dry_run:
        data  = pm_agent.load_manifest()
        queue = pm_agent.build_queue(data, args.course, args.lesson_type, args.batch)
        print(f"Would dispatch {len(queue)} lesson(s):")
        for lesson in queue:
            print(f"  [{lesson['id']:6s}] {lesson['tab']}")
        return

    if not worker_url:
        print("WORKER_URL not set. Add to .env or pass --worker-url <url>")
        sys.exit(1)

    if args.finalize:
        result = call(f"{worker_url}/finalize", pipeline_key, {})
        if result.get("ok"):
            print(f"Finalized: {result['done']} done, {result['failed']} failed")
        else:
            print(f"Finalize failed: {result}")
        return

    flags = {
        "generate_interactives": True,
        "generate_assessments":  True,
        "generate_scorm":        not args.skip_scorm,
        "generate_images":       not args.skip_images,
        "import_to_platform":    True,
    }

    try:
        result = call(f"{worker_url}/dispatch", pipeline_key, {
            "course":      args.course,
            "batch":       args.batch,
            "lesson_type": args.lesson_type,
            "flags":       flags,
        })
    except Exception as e:
        print(f"Error calling /dispatch: {e}")
        sys.exit(1)

    if result.get("ok"):
        queued = result.get("queued", 0)
        failed = result.get("failed", 0)
        run_id = result.get("runId", "?")
        print(f"Dispatched {queued} lesson(s) for run {run_id}" +
              (f" ({failed} enqueue error(s))" if failed else ""))
        for lid in result.get("lessons", []):
            print(f"  {lid}")
    else:
        print(f"Dispatch failed: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
