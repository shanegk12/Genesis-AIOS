"""
fix_lw_image_urls.py
--------------------
Replaces the LearnWorlds instructor image URL with the locally-hosted one
in all Firestore siteContent documents.

Usage:
    python scripts/fix_lw_image_urls.py --dry-run   # preview
    python scripts/fix_lw_image_urls.py             # apply
"""

import json, sys, urllib.request, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import google.auth.transport.requests as tr
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

OAUTH_CLIENT = Path(__file__).parent.parent / "oauth-client.json"
FS_TOKEN     = Path(__file__).parent.parent / "fs-token.json"
PROJECT      = "genesis-modularity"
FS_SCOPES    = ["https://www.googleapis.com/auth/datastore"]

OLD_URL = "https://lwfiles.mycourse.app/6974e5c417966def72c83dcc-public/5c3397d6ad3c606f15135be46d3db268.jpg"
NEW_URL = "/images/instructor-horstemeyer.jpg"


def _get_creds():
    creds = None
    if FS_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(FS_TOKEN), FS_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(tr.Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT), FS_SCOPES)
            creds = flow.run_local_server(port=0)
        FS_TOKEN.write_text(creds.to_json())
    return creds


def _fs_get(path, token):
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _fs_patch(path, body, token):
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents/{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="PATCH", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def replace_in_value(v):
    """Recursively replace OLD_URL with NEW_URL in a Firestore value dict."""
    if "stringValue" in v:
        if v["stringValue"] == OLD_URL:
            return {"stringValue": NEW_URL}, True
        return v, False
    if "mapValue" in v:
        fields = v["mapValue"].get("fields", {})
        changed = False
        new_fields = {}
        for k, fv in fields.items():
            new_fv, c = replace_in_value(fv)
            new_fields[k] = new_fv
            if c:
                changed = True
        return {"mapValue": {"fields": new_fields}}, changed
    if "arrayValue" in v:
        values = v["arrayValue"].get("values", [])
        changed = False
        new_values = []
        for av in values:
            new_av, c = replace_in_value(av)
            new_values.append(new_av)
            if c:
                changed = True
        return {"arrayValue": {"values": new_values}}, changed
    return v, False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Authenticating…")
    creds = _get_creds()
    token = creds.token

    # Fetch all siteContent documents
    print("Fetching siteContent documents…")
    raw = _fs_get("siteContent", token)
    docs = raw.get("documents", [])
    print(f"  {len(docs)} documents found")

    for doc in docs:
        doc_id = doc["name"].split("/")[-1]
        fields = doc.get("fields", {})
        new_fields = {}
        changed = False
        for k, v in fields.items():
            new_v, c = replace_in_value(v)
            new_fields[k] = new_v
            if c:
                changed = True

        if changed:
            if args.dry_run:
                print(f"  [dry-run] Would update siteContent/{doc_id}")
            else:
                print(f"  Updating siteContent/{doc_id}…")
                _fs_patch(f"siteContent/{doc_id}", {"fields": new_fields}, token)
                print(f"    Done.")
        else:
            print(f"  siteContent/{doc_id}: no match, skip")

    print("\nDone." if not args.dry_run else "\nDry run complete.")


if __name__ == "__main__":
    main()
