#!/bin/bash
set -e

# Strip any whitespace/CRLF that PowerShell may have appended to the secret value
GITHUB_TOKEN=$(echo "$GITHUB_TOKEN" | tr -d '\r\n ')

# Clone latest repo so scripts and manifest are always fresh
git clone --depth=1 --single-branch --branch=main "https://x-access-token:${GITHUB_TOKEN}@github.com/shanegk12/Genesis-AIOS.git" /repo
cd /repo
git config user.email "pipeline@genesis-aios.iam.gserviceaccount.com"
git config user.name "GK12 Pipeline"

# Start Flask worker (PORT is set by Cloud Run)
exec python /repo/scripts/pipeline_worker.py
