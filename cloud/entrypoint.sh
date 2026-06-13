#!/bin/sh
# Boot: clone/refresh both repos with the GitHub token, set Bez's git identity,
# then start the Socket Mode listener. Secrets arrive as env vars (Secret Manager).
set -e

: "${GITHUB_TOKEN:?GITHUB_TOKEN required}"
AUTH="https://x-access-token:${GITHUB_TOKEN}@github.com"

mkdir -p /app/repos
cd /app/repos
if [ -d GK12-Platform/.git ]; then (cd GK12-Platform && git pull --ff-only || true); else
  git clone --depth 1 "$AUTH/shanegk12/genesis-education-solutions.git" GK12-Platform; fi
if [ -d AIOS/.git ]; then (cd AIOS && git pull --ff-only || true); else
  git clone --depth 1 "$AUTH/shanegk12/Genesis-AIOS.git" AIOS; fi

git config --global user.email "bez@gk12academy.com"
git config --global user.name "Bez"
git config --global --add safe.directory '*'
# Push uses the token transparently.
git config --global url."${AUTH}/".insteadOf "https://github.com/"

# Install platform deps in the background so the health server / socket come up
# immediately (Cloud Run needs the port bound fast). Bez can also run this on demand.
(cd /app/repos/GK12-Platform && npm install --no-audit --no-fund >/tmp/npm.log 2>&1 || true) &

cd /app
exec python scripts/bez_socket.py
