"""
GWS Auth — Domain-wide Delegation helper for GK12 local scripts.

Uses the pipeline-runner service account (DwD already granted in Google Admin)
to impersonate shane@gk12academy.com, so user OAuth tokens never expire.

Setup (one-time):
  1. GCP Console → IAM → Service Accounts → pipeline-runner@genesis-aios.iam.gserviceaccount.com
  2. Keys → Add Key → Create new key → JSON → Download
  3. Save the downloaded file as: D:\\AIOS\\gk12-sa-key.json

The key file is gitignored. Never commit it.
"""

import os, sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

SA_KEY_PATH    = Path(__file__).parent.parent / "gk12-sa-key.json"
IMPERSONATE_AS = "shane@gk12academy.com"

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/devstorage.read_write",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
]

# Fallback: user OAuth token (legacy — only used if SA key not found)
OAUTH_TOKEN_PATH   = Path(__file__).parent.parent / "drive-token.json"
OAUTH_CLIENT_PATH  = Path(__file__).parent.parent / "oauth-client.json"


def get_credentials(scopes: list[str] | None = None):
    """
    Return Google credentials. Prefers DwD service account key; falls back to
    user OAuth flow if the key file is not present.
    """
    scopes = scopes or DRIVE_SCOPES

    if SA_KEY_PATH.exists() and SA_KEY_PATH.stat().st_size > 0:
        return _dwd_credentials(scopes)
    else:
        print(
            f"[AUTH] gk12-sa-key.json not found at {SA_KEY_PATH}\n"
            f"       Falling back to user OAuth. To fix permanently:\n"
            f"       GCP Console → pipeline-runner service account → Keys → Create JSON key\n"
            f"       Save as: {SA_KEY_PATH}",
            file=sys.stderr,
        )
        return _oauth_credentials(scopes)


def _dwd_credentials(scopes: list[str]):
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY_PATH),
        scopes=scopes,
        subject=IMPERSONATE_AS,
    )
    return creds


def _oauth_credentials(scopes: list[str]):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if OAUTH_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            if not OAUTH_CLIENT_PATH.exists():
                print(f"[AUTH] oauth-client.json not found at {OAUTH_CLIENT_PATH}", file=sys.stderr)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT_PATH), scopes)
            creds = flow.run_local_server(port=0)
        with open(OAUTH_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def get_session(scopes: list[str] | None = None):
    """Return an AuthorizedSession using the best available credentials."""
    from google.auth.transport.requests import AuthorizedSession
    return AuthorizedSession(get_credentials(scopes))
