import sys, os, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))

from google.auth.transport.requests import Request, AuthorizedSession
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/devstorage.read_write",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
]
token_path = os.path.join(os.path.dirname(__file__), "..", "drive-token.json")
creds = Credentials.from_authorized_user_file(token_path, SCOPES)
if not creds.valid:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
session = AuthorizedSession(creds)

# Check authenticated user via Drive about endpoint
resp_about = session.get("https://www.googleapis.com/drive/v3/about",
                          params={"fields": "user(emailAddress,displayName)"})
print(f"Authenticated as: {resp_about.json()}")

ROOT_ID = "1aiPs5WeyJEqL4kPyK5Gt5IAUfG2TSTkH"
print(f"\nChecking folder {ROOT_ID}...")
resp2 = session.get(f"https://www.googleapis.com/drive/v3/files/{ROOT_ID}",
                    params={"fields": "id,name,mimeType,owners", "supportsAllDrives": "true"})
print(f"Status: {resp2.status_code} {resp2.text[:300]}")

# List children of the curriculum root folder
q2 = f"'{ROOT_ID}' in parents and trashed=false"
resp_children = session.get("https://www.googleapis.com/drive/v3/files",
    params={"q": q2, "fields": "files(id,name,mimeType)", "pageSize": 50,
            "includeItemsFromAllDrives": "true", "supportsAllDrives": "true"})
print("\nChildren of Homeschool MS Curriculum folder:")
for f in resp_children.json().get("files", []):
    print(f"  {f['mimeType'][:35]:35s}  {f['name']}")
print(resp_children.json().get("error", ""))
