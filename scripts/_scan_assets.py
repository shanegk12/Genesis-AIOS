"""Deep-scan Common Assets and Primary Resources for interactive files."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from google.auth.transport.requests import Request, AuthorizedSession
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/drive"]
token_path = os.path.join(os.path.dirname(__file__), "..", "drive-token.json")
creds = Credentials.from_authorized_user_file(token_path, SCOPES)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
session = AuthorizedSession(creds)

ROOT_ID = "1aiPs5WeyJEqL4kPyK5Gt5IAUfG2TSTkH"

def list_all(folder_id, path="", depth=0):
    resp = session.get("https://www.googleapis.com/drive/v3/files", params={
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,size)",
        "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "pageSize": 500
    })
    for f in resp.json().get("files", []):
        mime = f.get("mimeType", "")
        size = f.get("size", "")
        full_path = f"{path}/{f['name']}"
        if "folder" in mime:
            print(f"  [DIR]  {full_path}")
            if depth < 4:
                list_all(f["id"], full_path, depth+1)
        else:
            print(f"         {full_path}  [{mime}] {size}b")

# Get top-level folders
resp = session.get("https://www.googleapis.com/drive/v3/files", params={
    "q": f"'{ROOT_ID}' in parents and trashed=false",
    "fields": "files(id,name,mimeType)",
    "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"
})
folders = {f["name"]: f["id"] for f in resp.json().get("files", []) if "folder" in f.get("mimeType","")}

for target in ["Common Assets", "Primary Resources", "Lesson Templates"]:
    fid = folders.get(target)
    if fid:
        print(f"\n=== {target} ===")
        list_all(fid, target)
