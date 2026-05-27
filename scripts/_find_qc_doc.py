"""Find QC Checklist doc in Drive and print its ID and URL."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gws_auth import get_credentials
from googleapiclient.discovery import build

creds = get_credentials()
drive = build("drive", "v3", credentials=creds)

results = drive.files().list(
    q="name contains 'QC' and mimeType='application/vnd.google-apps.document' and trashed=false",
    fields="files(id, name, parents, webViewLink)",
    supportsAllDrives=True,
    includeItemsFromAllDrives=True,
    pageSize=20,
).execute()

for f in results.get("files", []):
    print(f["name"], "|", f["id"], "|", f.get("webViewLink", ""))
