"""List everything at the Drive curriculum root and scan non-lesson folders for interactives."""
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

def list_folder(folder_id, depth=0):
    resp = session.get("https://www.googleapis.com/drive/v3/files", params={
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,size)",
        "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "pageSize": 200
    })
    files = resp.json().get("files", [])
    indent = "  " * depth
    for f in files:
        mime = f.get("mimeType", "")
        size = f.get("size", "")
        is_folder = "folder" in mime
        print(f"{indent}{'[DIR]' if is_folder else '     '} {f['name'][:60]:60s}  {mime[:40]}")
        if is_folder and depth < 1:
            list_folder(f["id"], depth + 1)

print(f"Root curriculum folder contents:")
list_folder(ROOT_ID)
