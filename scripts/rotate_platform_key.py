"""
Rotate the shared platform API key.

The key gates ~20 admin routes on the live platform (/api/admin/lessons,
/api/admin/enroll, /api/admin/migrate, ...). It lives in two places:

  1. Secret Manager  ADMIN_API_KEY   project genesis-modularity (App Hosting, prod + staging)
  2. D:\\AIOS\\.env    PIPELINE_KEY                               (every local script)

Different names, same value. The local scripts send it as a bearer token and the
platform compares it against ADMIN_API_KEY, so they must match.

NOTE: the Cloud Run pipeline worker used to be a third consumer, via a
PIPELINE_KEY secret in project genesis-aios. That service was retired on
2026-07-30 (the course content is finished and only video work remains), so that
secret is orphaned and is not rotated here. Delete it rather than rotating it.

This script writes the new value to both places and never prints it. The deploy
is NOT automated: App Hosting only picks up a new secret version on a build, and
that is deliberately your call. The remaining steps print at the end.

Usage:
  python scripts/rotate_platform_key.py             # dry run, shows the plan
  python scripts/rotate_platform_key.py --confirm   # actually rotate

Prerequisites:
  gcloud auth login   (tokens expire; this is the usual failure)
  No local pipeline scripts mid-run -- between the rotation and the platform
  deploy, the new key is not yet valid and calls will 401.
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ENV_PATH  = REPO_ROOT / ".env"

# On Windows gcloud is a .cmd shim, which CreateProcess cannot resolve from the
# bare name. shutil.which finds it via PATHEXT.
GCLOUD = shutil.which("gcloud") or "gcloud"

TARGETS = [
    ("ADMIN_API_KEY", "genesis-modularity"),
]


def add_secret_version(name: str, project: str, value: str) -> bool:
    """Add a new version via --data-file. Never pipe the value through a shell:
    PowerShell appends CRLF and a BOM, which silently corrupts the secret."""
    fd, tmp = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(value.encode("utf-8"))  # bytes, so no BOM and no trailing newline
        r = subprocess.run(
            [GCLOUD, "secrets", "versions", "add", name,
             f"--data-file={tmp}", f"--project={project}"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"  FAILED {name} ({project}): {r.stderr.strip()}")
            return False
        print(f"  OK     {name} ({project}) -- new version added")
        return True
    finally:
        os.unlink(tmp)


def update_env_file(value: str) -> bool:
    if not ENV_PATH.exists():
        print(f"  SKIP   {ENV_PATH} does not exist")
        return False
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("PIPELINE_KEY="):
            lines[i] = f"PIPELINE_KEY={value}"
            found = True
    if not found:
        lines.append(f"PIPELINE_KEY={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  OK     {ENV_PATH} -- PIPELINE_KEY updated")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="actually rotate; without this it only prints the plan")
    args = ap.parse_args()

    print("Rotating the shared platform API key.\n")
    print("Will write a new value to:")
    for name, project in TARGETS:
        print(f"  - Secret Manager {name} in {project}")
    print(f"  - {ENV_PATH}")

    if not args.confirm:
        print("\nDry run. Nothing changed. Re-run with --confirm to rotate.")
        return 0

    new_key = secrets.token_urlsafe(32)
    print("\nWriting (value is never printed):")

    ok = all(add_secret_version(n, p, new_key) for n, p in TARGETS)
    update_env_file(new_key)

    if not ok:
        print("\nAt least one secret write FAILED. The old key is still valid "
              "everywhere it did not change. Fix the error and re-run before "
              "deploying anything.")
        return 1

    print("""
Secret updated, but the LIVE PLATFORM STILL VALIDATES THE OLD KEY until it is
redeployed. Until you finish step 1, your local scripts will 401.

  1. Deploy the platform so it picks up the new ADMIN_API_KEY.
     From D:\\GK12-Platform:
       git commit --allow-empty -m "chore: pick up rotated ADMIN_API_KEY"
       git push origin staging
       # validate staging, then:
       git checkout main && git merge --ff-only staging && git push origin main

  2. Confirm a local script authenticates against prod again. Any read-only
     admin call will do; a 401 means the deploy has not landed yet.

  3. Disable the old version so it cannot be rolled back into use. Get the
     version number from:
       gcloud secrets versions list ADMIN_API_KEY --project=genesis-modularity
     then:
       gcloud secrets versions disable <OLD_VERSION> \\
         --secret=ADMIN_API_KEY --project=genesis-modularity
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
