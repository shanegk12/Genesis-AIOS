# Google APIs Reference

Reference for all Google APIs wired to the AIOS. Auth note: API keys only work for public data. Private Drive/Docs/Gmail data requires a **service account key** (JSON) — share your Drive folder with the service account email and it works without browser popups.

---

## Auth Summary

| API | OAuth 2.0 | API Key | Service Account |
|-----|-----------|---------|-----------------|
| Drive v3 | ✓ | public only | ✓ |
| Docs v1 | ✓ | ✗ | ✓ |
| Gmail v1 | ✓ | public only | ✓ |
| Calendar v3 | ✓ | public only | ✓ |
| Sheets v4 | ✓ | public only | ✓ |

**This AIOS uses a service account key.** See `.env` for key path. Share any Drive folder with the service account email to grant access.

---

## Google Drive API v3

**Base URL:** `https://www.googleapis.com/drive/v3`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/files` | List files — supports search via `q` param |
| GET | `/files/{fileId}` | Get file metadata |
| GET | `/files/{fileId}?alt=media` | Download file content |
| PATCH | `/files/{fileId}` | Update file metadata |
| DELETE | `/files/{fileId}` | Delete a file |

**Search query examples (`q` param):**
```
name contains 'lesson'
mimeType = 'application/vnd.google-apps.document'
'folderId' in parents
modifiedTime > '2026-01-01T00:00:00'
```

**Common list call:**
```
GET /drive/v3/files?q=name contains 'module' and 'FOLDER_ID' in parents&orderBy=modifiedTime desc&fields=files(id,name,modifiedTime)
```

---

## Google Docs API v1

**Base URL:** `https://docs.googleapis.com/v1`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/documents/{documentId}` | Get full document content |
| POST | `/documents` | Create new document |
| POST | `/documents/{documentId}:batchUpdate` | Apply edits to a document |

**Note:** No "list documents" endpoint — use Drive API with `mimeType = 'application/vnd.google-apps.document'` to find docs, then fetch content here.

**Get doc content:**
```
GET /documents/{documentId}?fields=body,documentId,title
```

Document IDs come from the share URL: `https://docs.google.com/document/d/{documentId}/edit`

---

## Gmail API v1

**Base URL:** `https://www.googleapis.com/gmail/v1`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/me/messages` | List messages (returns IDs only) |
| GET | `/users/me/messages/{id}` | Get full message with headers + body |
| POST | `/users/me/messages/send` | Send a message |
| GET | `/users/me/threads` | List threads |
| GET | `/users/me/threads/{id}` | Get full thread |
| POST | `/users/me/drafts` | Create a draft |

**Search query examples (`q` param — same syntax as Gmail search bar):**
```
from:shane@gk12academy.com
subject:Genesis
is:unread after:2026/05/01
has:attachment from:ethan
```

**Common call:**
```
GET /users/me/messages?q=from:dr.mark subject:Genesis&maxResults=10
```

---

## Google Calendar API v3

**Base URL:** `https://www.googleapis.com/calendar/v3`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/users/me/calendarList` | List all calendars |
| GET | `/calendars/{calendarId}/events` | List events in a time range |
| GET | `/calendars/{calendarId}/events/{eventId}` | Get a specific event |
| POST | `/calendars/{calendarId}/events` | Create an event |
| PATCH | `/calendars/{calendarId}/events/{eventId}` | Update an event |

Use `primary` as `calendarId` for the main Google Calendar.

**Common call:**
```
GET /calendars/primary/events?timeMin=2026-05-13T00:00:00Z&timeMax=2026-05-20T23:59:59Z&singleEvents=true&orderBy=startTime
```

---

## Google Sheets API v4

**Base URL:** `https://sheets.googleapis.com/v4`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/spreadsheets/{id}/values/{range}` | Read a range of cells |
| GET | `/spreadsheets/{id}/values:batchGet` | Read multiple ranges |
| PUT | `/spreadsheets/{id}/values/{range}` | Write to a range |
| POST | `/spreadsheets/{id}/values/{range}:append` | Append rows |
| POST | `/spreadsheets/{id}/values/{range}:clear` | Clear a range |

**Range syntax:** `Sheet1!A1:Z100`, `Sheet1!A:C`, `Sheet1!1:5`

**Common read call:**
```
GET /spreadsheets/{id}/values/Sheet1!A1:Z100?majorDimension=ROWS&valueRenderOption=FORMATTED_VALUE
```

---

## Setting Up a Service Account (one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → IAM & Admin → Service Accounts
2. Create a service account → name it `aios-drive-reader`
3. Skip role assignment → Create
4. Click the service account → Keys tab → Add Key → JSON → Download
5. Save the JSON to `C:\Users\Shane\.claude\gdrive\service-account.json`
6. Copy the service account email (looks like `aios-drive-reader@project-id.iam.gserviceaccount.com`)
7. Share your Genesis K-12 Drive folder with that email (Viewer access)
8. Update `GOOGLE_SERVICE_ACCOUNT_PATH` in `.env`
