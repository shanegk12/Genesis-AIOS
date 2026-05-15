#!/bin/bash
set -e

# Strip any whitespace/CRLF that PowerShell may have appended to the secret value
GITHUB_TOKEN=$(echo "$GITHUB_TOKEN" | tr -d '\r\n ')

# Clone latest repo so the manifest and media_prompts.json are always fresh
git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/shanegk12/Genesis-AIOS.git" /repo

cd /repo
git config user.email "pipeline@genesis-aios.iam.gserviceaccount.com"
git config user.name "GK12 Pipeline"

exec python scripts/pm_agent.py --course both --batch 20 --type all --generate-images
