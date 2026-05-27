"""Scan Drive lesson folders for non-image, non-Google-doc files (HTML5, zip, etc.)"""
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
IMAGE_TYPES = {"image/png","image/jpeg","image/gif","image/webp","image/svg+xml"}

resp = session.get("https://www.googleapis.com/drive/v3/files", params={
    "q": f"'{ROOT_ID}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
    "fields": "files(id,name)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"
})
course_folders = {f["name"]: f["id"] for f in resp.json().get("files", [])}
print("Course folders:", list(course_folders.keys()))

non_image = []
for course_name, course_id in course_folders.items():
    resp2 = session.get("https://www.googleapis.com/drive/v3/files", params={
        "q": f"'{course_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        "fields": "files(id,name)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
        "pageSize": 200
    })
    lesson_folders = resp2.json().get("files", [])
    for lf in lesson_folders:
        resp3 = session.get("https://www.googleapis.com/drive/v3/files", params={
            "q": f"'{lf['id']}' in parents and trashed=false",
            "fields": "files(id,name,mimeType,size)", "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true"
        })
        for f in resp3.json().get("files", []):
            mime = f.get("mimeType", "")
            if mime not in IMAGE_TYPES and "google-apps" not in mime:
                non_image.append({
                    "lesson": lf["name"], "course": course_name,
                    "name": f["name"], "mime": mime,
                    "size": f.get("size", "?"), "id": f["id"]
                })

print(f"\nNon-image files: {len(non_image)}")
for f in non_image:
    print(f"  {f['course']:20s}  {f['lesson']:8s}  {f['mime']:45s}  {f['name']}")
