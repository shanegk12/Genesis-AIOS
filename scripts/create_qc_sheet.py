"""
create_qc_sheet.py
------------------
Creates a Google Sheet for human QC review of all lessons.
Pulls live module / lesson data from Firestore, assigns deadlines based
on the August 2026 launch target, and uploads to a new Sheet in Drive.

Usage:
    python scripts/create_qc_sheet.py
"""

import json, sys, urllib.request, urllib.error
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
import google.auth.transport.requests as tr
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT      = "genesis-modularity"
DRIVE_FOLDER = "1aiPs5WeyJEqL4kPyK5Gt5IAUfG2TSTkH"   # Curriculum root folder

OAUTH_CLIENT = Path(__file__).parent.parent / "oauth-client.json"

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
FS_SCOPES = [
    "https://www.googleapis.com/auth/datastore",
]

# Use separate token files so scopes don't collide
DRIVE_TOKEN = Path(__file__).parent.parent / "drive-token.json"
FS_TOKEN    = Path(__file__).parent.parent / "fs-token.json"


def _get_creds(token_path: Path, scopes: list[str]) -> Credentials:
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(tr.Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT), scopes)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return creds

# Module deadlines (Mon of the review week, working toward Aug launch)
# 9 modules × ~1 week each, starting June 2
MODULE_DEADLINES = {
    "Module 1": date(2026, 6,  8),
    "Module 2": date(2026, 6, 15),
    "Module 3": date(2026, 6, 22),
    "Module 4": date(2026, 6, 29),
    "Module 5": date(2026, 7,  6),
    "Module 6": date(2026, 7, 13),
    "Module 7": date(2026, 7, 20),
    "Module 8": date(2026, 7, 27),
    "Module 9": date(2026, 8,  3),
}

# ── Auth ──────────────────────────────────────────────────────────────────────

print("Authenticating (Firestore)…")
fs_creds = _get_creds(FS_TOKEN, FS_SCOPES)
FS_TOKEN_VAL = fs_creds.token

print("Authenticating (Sheets/Drive)…")
drive_creds = _get_creds(DRIVE_TOKEN, DRIVE_SCOPES)
DRIVE_TOKEN_VAL = drive_creds.token

def _get(url, token=None):
    t = token or DRIVE_TOKEN_VAL
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {t}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def _post(url, body, token=None):
    t = token or DRIVE_TOKEN_VAL
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {t}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# ── Fetch Firestore data ───────────────────────────────────────────────────────

print("Fetching modules…")
fs_base = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"

mods_raw = _get(f"{fs_base}/modules?pageSize=50", token=FS_TOKEN_VAL).get("documents", [])
modules = {}   # id → {title, order, deadline}
for m in mods_raw:
    mid   = m["name"].split("/")[-1]
    f     = m["fields"]
    title = f.get("title", {}).get("stringValue", mid)
    order = int(f.get("order", {}).get("integerValue", 99))
    modules[mid] = {
        "title":    title,
        "order":    order,
        "deadline": MODULE_DEADLINES.get(mid, date(2026, 8, 10)),
    }

print(f"  {len(modules)} modules found")

print("Fetching units…")
units_raw = _get(f"{fs_base}/units?pageSize=200", token=FS_TOKEN_VAL).get("documents", [])
units = {}    # id → {title, moduleId}
for u in units_raw:
    uid = u["name"].split("/")[-1]
    f   = u["fields"]
    units[uid] = {
        "title":    f.get("title", {}).get("stringValue", uid),
        "moduleId": f.get("moduleId", {}).get("stringValue", ""),
        "order":    int(f.get("order", {}).get("integerValue", 99)),
    }

print(f"  {len(units)} units found")

print("Fetching lessons…")
# runQuery for all lessons (no course filter — both tracks share modules)
rq_url  = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents:runQuery"
rq_body = {"structuredQuery": {
    "from": [{"collectionId": "lessons"}],
    "orderBy": [{"field": {"fieldPath": "order"}, "direction": "ASCENDING"}],
    "limit": 300,
}}
rq_resp = _post(rq_url, rq_body, token=FS_TOKEN_VAL)
all_lessons = []
for row in rq_resp:
    if "document" not in row:
        continue
    d   = row["document"]
    lid = d["name"].split("/")[-1]
    f   = d["fields"]
    if not (lid.startswith("C-") or lid.startswith("M-")):
        continue
    all_lessons.append({
        "id":       lid,
        "title":    f.get("title",    {}).get("stringValue", ""),
        "topic":    f.get("topic",    {}).get("stringValue", ""),
        "order":    int(f.get("order", {}).get("integerValue", 999)),
        "moduleId": f.get("moduleId", {}).get("stringValue", ""),
        "unitId":   f.get("unitId",   {}).get("stringValue", ""),
        "courseId": f.get("courseId", {}).get("stringValue", ""),
        "track":    "Creationeering" if lid.startswith("C-") else "Mousetrap",
    })

all_lessons.sort(key=lambda x: (
    modules.get(x["moduleId"], {}).get("order", 99),
    x["order"],
))
print(f"  {len(all_lessons)} lessons found")

# ── Build sheet rows ──────────────────────────────────────────────────────────

# Header row
HEADER = [
    "Lesson ID", "Track", "Title", "Topic",
    "Module", "Unit", "Deadline",
    "Reviewer", "Status", "Review Date",
    "AI Issues", "Notes",
]

# Load any existing QC report issues for pre-population
qc_path = Path(__file__).parent / "qc_reports.json"
qc_issues = {}
if qc_path.exists():
    rpts = json.loads(qc_path.read_text()).get("reports", {})
    for lid, rpt in rpts.items():
        if rpt.get("issues"):
            qc_issues[lid] = "; ".join(i.get("description", "") for i in rpt["issues"])

rows = [HEADER]
current_mod = None
for lesson in all_lessons:
    mod_id    = lesson["moduleId"]
    mod_info  = modules.get(mod_id, {})
    mod_title = mod_info.get("title", mod_id or "Unassigned")
    deadline  = mod_info.get("deadline", date(2026, 8, 10))
    unit_info = units.get(lesson["unitId"], {})
    unit_name = unit_info.get("title", lesson["unitId"] or "")

    # Blank separator row between modules
    if mod_id != current_mod:
        if current_mod is not None:
            rows.append([""] * len(HEADER))
        rows.append([f"── Module: {mod_title} ──  Deadline: {deadline.strftime('%b %d')}"] + [""] * (len(HEADER) - 1))
        current_mod = mod_id

    rows.append([
        lesson["id"],
        lesson["track"],
        lesson["title"],
        lesson["topic"],
        mod_title,
        unit_name,
        deadline.strftime("%Y-%m-%d"),
        "",          # Reviewer
        "Not Started",
        "",          # Review Date
        qc_issues.get(lesson["id"], ""),
        "",          # Notes
    ])

print(f"  {len(rows)} total rows (incl. headers + separators)")

# ── Create Google Sheet ───────────────────────────────────────────────────────

print("Creating Google Sheet…")
sheets_base = "https://sheets.googleapis.com/v4/spreadsheets"

create_body = {
    "properties": {"title": "GK12 Lesson QC Tracker — Aug 2026"},
    "sheets": [
        {"properties": {"title": "All Lessons", "gridProperties": {"frozenRowCount": 1}}},
        {"properties": {"title": "Flagged",     "gridProperties": {"frozenRowCount": 1}}},
        {"properties": {"title": "Deadlines",   "gridProperties": {"frozenRowCount": 1}}},
    ],
}
sheet_meta = _post(sheets_base, create_body)
sheet_id = sheet_meta["spreadsheetId"]
print(f"  Sheet created: {sheet_id}")

# ── Write lesson rows ─────────────────────────────────────────────────────────

import urllib.parse

def _put_values(sheet_id, tab_name, values):
    encoded_tab = urllib.parse.quote(f"{tab_name}!A1")
    url = f"{sheets_base}/{sheet_id}/values/{encoded_tab}?valueInputOption=USER_ENTERED"
    data = json.dumps({"values": values}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {DRIVE_TOKEN_VAL}", "Content-Type": "application/json"},
        method="PUT",
    )
    urllib.request.urlopen(req)

print("Writing lesson data…")
_put_values(sheet_id, "All Lessons", rows)

# ── Write Deadlines summary ───────────────────────────────────────────────────

deadline_rows = [["Module", "Title", "# Lessons", "Deadline", "Days Remaining"]]
today = date.today()
for mid, info in sorted(modules.items(), key=lambda x: x[1]["order"]):
    count = sum(1 for l in all_lessons if l["moduleId"] == mid)
    dl    = info["deadline"]
    days  = (dl - today).days
    deadline_rows.append([mid, info["title"], count, dl.strftime("%Y-%m-%d"), days])

_put_values(sheet_id, "Deadlines", deadline_rows)

# ── Write Flagged sheet header ────────────────────────────────────────────────

flagged_rows = [
    HEADER,
    ["← Paste flagged rows here, or use this sheet to track re-reviews"] + [""] * (len(HEADER) - 1),
]
_put_values(sheet_id, "Flagged", flagged_rows)

# ── Formatting ────────────────────────────────────────────────────────────────

print("Formatting sheet…")

# Get sheet IDs for batchUpdate
main_sheet_gid  = sheet_meta["sheets"][0]["properties"]["sheetId"]
dead_sheet_gid  = sheet_meta["sheets"][2]["properties"]["sheetId"]

STATUS_COL = HEADER.index("Status")   # 0-based

requests_fmt = [
    # Freeze + bold header row
    {"repeatCell": {
        "range": {"sheetId": main_sheet_gid, "startRowIndex": 0, "endRowIndex": 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.106, "green": 0.165, "blue": 0.361},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat)",
    }},
    # Auto-resize all columns on All Lessons
    {"autoResizeDimensions": {
        "dimensions": {"sheetId": main_sheet_gid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(HEADER)},
    }},
    # Bold header on Deadlines
    {"repeatCell": {
        "range": {"sheetId": dead_sheet_gid, "startRowIndex": 0, "endRowIndex": 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.106, "green": 0.165, "blue": 0.361},
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat)",
    }},
    # Status column data validation
    {"setDataValidation": {
        "range": {
            "sheetId": main_sheet_gid,
            "startRowIndex": 1, "startColumnIndex": STATUS_COL,
            "endColumnIndex": STATUS_COL + 1,
        },
        "rule": {
            "condition": {
                "type": "ONE_OF_LIST",
                "values": [
                    {"userEnteredValue": "Not Started"},
                    {"userEnteredValue": "In Progress"},
                    {"userEnteredValue": "Approved"},
                    {"userEnteredValue": "Flagged"},
                    {"userEnteredValue": "Needs Re-Review"},
                ],
            },
            "showCustomUi": True,
            "strict": False,
        },
    }},
    # Conditional formatting: Approved → green
    {"addConditionalFormatRule": {
        "rule": {
            "ranges": [{"sheetId": main_sheet_gid, "startRowIndex": 1,
                         "startColumnIndex": STATUS_COL, "endColumnIndex": STATUS_COL + 1}],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "Approved"}]},
                "format": {"backgroundColor": {"red": 0.714, "green": 0.843, "blue": 0.659}},
            },
        }, "index": 0,
    }},
    # Conditional formatting: Flagged → red
    {"addConditionalFormatRule": {
        "rule": {
            "ranges": [{"sheetId": main_sheet_gid, "startRowIndex": 1,
                         "startColumnIndex": STATUS_COL, "endColumnIndex": STATUS_COL + 1}],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "Flagged"}]},
                "format": {"backgroundColor": {"red": 0.918, "green": 0.600, "blue": 0.600}},
            },
        }, "index": 1,
    }},
    # Conditional formatting: In Progress → yellow
    {"addConditionalFormatRule": {
        "rule": {
            "ranges": [{"sheetId": main_sheet_gid, "startRowIndex": 1,
                         "startColumnIndex": STATUS_COL, "endColumnIndex": STATUS_COL + 1}],
            "booleanRule": {
                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "In Progress"}]},
                "format": {"backgroundColor": {"red": 1.0, "green": 0.949, "blue": 0.8}},
            },
        }, "index": 2,
    }},
]

batch_url = f"{sheets_base}/{sheet_id}:batchUpdate"
_post(batch_url, {"requests": requests_fmt})

# ── Move to curriculum Drive folder ──────────────────────────────────────────

print("Moving sheet to curriculum Drive folder…")
drive_base = "https://www.googleapis.com/drive/v3/files"

# Get current parents
meta = _get(f"{drive_base}/{sheet_id}?fields=parents&supportsAllDrives=true")
old_parents = ",".join(meta.get("parents", []))

move_url = (f"{drive_base}/{sheet_id}"
            f"?addParents={DRIVE_FOLDER}"
            f"&removeParents={old_parents}"
            f"&fields=id,parents"
            f"&supportsAllDrives=true")
req = urllib.request.Request(
    move_url,
    data=b"{}",
    headers={"Authorization": f"Bearer {DRIVE_TOKEN_VAL}", "Content-Type": "application/json"},
    method="PATCH",
)
urllib.request.urlopen(req)

# ── Done ──────────────────────────────────────────────────────────────────────

url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
print(f"\n✓ Done!")
print(f"  Sheet: {url}")
print(f"  Lessons: {len(all_lessons)}")
print(f"  Modules: {len(modules)}")
print(f"  Deadline schedule:")
for mid, info in sorted(modules.items(), key=lambda x: x[1]["order"]):
    count = sum(1 for l in all_lessons if l["moduleId"] == mid)
    dl    = info["deadline"]
    days  = (dl - date.today()).days
    print(f"    {mid} — {info['title']}: {count} lessons  →  {dl.strftime('%b %d')}  ({days}d)")
