#!/bin/bash
set -e

# Strip any whitespace/CRLF that PowerShell may have appended to the secret value
GITHUB_TOKEN=$(echo "$GITHUB_TOKEN" | tr -d '\r\n ')

# Clone latest repo so scripts and manifest are always fresh
git clone --depth=1 --single-branch --branch=main "https://x-access-token:${GITHUB_TOKEN}@github.com/shanegk12/Genesis-AIOS.git" /repo
cd /repo
git config user.email "pipeline@genesis-aios.iam.gserviceaccount.com"
git config user.name "GK12 Pipeline"

# Start the worker under gunicorn (PORT is set by Cloud Run).
#
# --workers 1 is REQUIRED, not a tuning choice. Two pieces of state are
# in-process or on local disk only: _manifest_lock in pipeline_worker.py is a
# threading.Lock (a second process ignores it and races the manifest write),
# and every request operates on the single git clone at /repo. Concurrency
# comes from threads, matching --concurrency=20 in cloudbuild.yaml.
#
# --timeout must stay long. /process runs a full lesson pipeline for many
# minutes; at gunicorn's 30s default the arbiter SIGKILLs the worker mid-run
# and takes every in-flight lesson with it. 3600 lets Cloud Run's own
# --timeout=3600 be what gives up first.
exec gunicorn \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 1 --threads 24 \
  --timeout 3600 --graceful-timeout 60 \
  --chdir /repo --pythonpath /repo/scripts \
  --access-logfile - --error-logfile - \
  pipeline_worker:app
