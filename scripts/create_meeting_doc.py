"""
Creates a Google Doc from the meeting reports markdown file,
then updates the calendar event description with the doc link.
"""

import os, sys, re, json

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "reports", "2026-05-19-meeting-reports.md")
CALENDAR_EVENT_ID = "vtlspmvi776s2g1usr7m371agk"
DOC_TITLE = "GK12 Platform & AIOS Review Reports — May 19, 2026"

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
]

def get_creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path  = os.path.join(os.path.dirname(__file__), "..", "drive-token.json")
    client_path = os.path.join(os.path.dirname(__file__), "..", "oauth-client.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def create_doc(docs_svc, title: str) -> str:
    doc = docs_svc.documents().create(body={"title": title}).execute()
    return doc["documentId"]


def build_requests(md_text: str) -> list:
    """Convert markdown to Docs API batchUpdate requests."""
    requests = []
    index = 1  # Docs inserts at index 1 initially

    lines = md_text.split("\n")
    # We'll insert all text first, then apply formatting in a second pass.
    # Build plain text with markers, then style.
    segments = []  # list of (text, style) where style is 'h1','h2','h3','bold','normal','code'

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("# ") and not line.startswith("## "):
            segments.append((line[2:].strip() + "\n", "HEADING_1"))
        elif line.startswith("## "):
            segments.append((line[3:].strip() + "\n", "HEADING_2"))
        elif line.startswith("### "):
            segments.append((line[4:].strip() + "\n", "HEADING_3"))
        elif line.startswith("---"):
            segments.append(("\n", "NORMAL_TEXT"))
        elif line.strip() == "":
            segments.append(("\n", "NORMAL_TEXT"))
        else:
            # Strip inline markdown for plain text
            clean = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
            clean = re.sub(r'\*(.+?)\*', r'\1', clean)
            clean = re.sub(r'`(.+?)`', r'\1', clean)
            clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)
            segments.append((clean.strip() + "\n", "NORMAL_TEXT"))
        i += 1

    # Insert all text as one block (end → start to preserve indices)
    full_text = "".join(s[0] for s in segments)
    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": full_text,
        }
    })

    # Apply paragraph styles by walking through text positions
    pos = 1
    for text, style in segments:
        end = pos + len(text)
        if style != "NORMAL_TEXT":
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": pos, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": style},
                    "fields": "namedStyleType",
                }
            })
        pos = end

    return requests


def share_doc_with_ethan(drive_svc, doc_id: str):
    drive_svc.permissions().create(
        fileId=doc_id,
        body={"type": "user", "role": "reader", "emailAddress": "ethan@gk12academy.com"},
        sendNotificationEmail=False,
    ).execute()
    print("  Shared with ethan@gk12academy.com")


def update_calendar_event(cal_svc, event_id: str, doc_url: str):
    event = cal_svc.events().get(calendarId="primary", eventId=event_id).execute()
    existing_desc = event.get("description", "")
    new_desc = (
        f'<p><strong>📄 Meeting Reports: <a href="{doc_url}">View Google Doc</a></strong></p>\n\n'
        + existing_desc
    )
    event["description"] = new_desc
    cal_svc.events().update(
        calendarId="primary", eventId=event_id, body=event,
        sendUpdates="all",
    ).execute()
    print("  Calendar event updated with doc link")


def main():
    from googleapiclient.discovery import build

    print("Authenticating...")
    creds = get_creds()
    docs_svc  = build("docs",     "v1", credentials=creds)
    drive_svc = build("drive",    "v3", credentials=creds)
    cal_svc   = build("calendar", "v3", credentials=creds)

    with open(REPORT_PATH, encoding="utf-8") as f:
        md_text = f.read()

    print(f"Creating Google Doc: '{DOC_TITLE}'...")
    doc_id  = create_doc(docs_svc, DOC_TITLE)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"  Doc ID: {doc_id}")
    print(f"  URL: {doc_url}")

    print("Populating content...")
    requests = build_requests(md_text)
    docs_svc.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()
    print(f"  Content written ({len(md_text)} chars)")

    print("Sharing with Ethan...")
    share_doc_with_ethan(drive_svc, doc_id)

    print("Linking to calendar event...")
    update_calendar_event(cal_svc, CALENDAR_EVENT_ID, doc_url)

    print(f"\nDone. Doc URL: {doc_url}")
    return doc_url


if __name__ == "__main__":
    main()
