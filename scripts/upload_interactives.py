"""
Upload custom interactives from D:\\AIOS\\interactives\\ to Google Drive lesson folders.

Maps:
  systems-diagram.html      → C-006
  unit-converter.html       → C-005
  ocv-problem-builder.html  → C-007
  flowchart-builder.html    → C-009
  gear-ratio-sim.html       → M-014
  efficiency-calculator.html → M-017
  iteration-tracker.html    → C-014

Usage:
  python scripts/upload_interactives.py
"""

import io, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _gws_auth import get_session

DRIVE_ROOT_ID = "1aiPs5WeyJEqL4kPyK5Gt5IAUfG2TSTkH"
INTERACTIVES_DIR = Path(__file__).parent.parent / "interactives"
LOG_PATH = Path(__file__).parent / "interactive_custom_log.json"

WIDGETS = [
    {
        "filename": "systems-diagram.html",
        "lessonId": "C-055",
        "description": "Clickable bicycle subassembly diagram — 6 subsystems with inputs/outputs/faith connections",
        "termCount": 6,
        "originalTarget": "C-006 (Intro to Systems Thinking)",
    },
    {
        "filename": "unit-converter.html",
        "lessonId": "C-039",
        "description": "Multi-category unit converter (length/mass/force/energy/speed/temp) with animated bar comparison",
        "termCount": 6,
        "originalTarget": "C-005 (Units, Conversions, and Measurement)",
    },
    {
        "filename": "ocv-problem-builder.html",
        "lessonId": "C-035",
        "description": "Drag-and-drop OCV (Objectives/Constraints/Variables) problem sorter with 4 engineering scenarios",
        "termCount": 8,
        "originalTarget": "C-007 (Objectives, Constraints, and Variables)",
    },
    {
        "filename": "flowchart-builder.html",
        "lessonId": "C-042",
        "description": "Drag-and-drop flowchart builder with symbol palette and step-sequencing challenges",
        "termCount": 5,
        "originalTarget": "C-009 (Process Mapping and Flowcharts)",
    },
    {
        "filename": "gear-ratio-sim.html",
        "lessonId": "M-042",
        "description": "Animated gear ratio simulator with real-time RPM, torque multiplier, and speed output",
        "termCount": 5,
        "originalTarget": "M-014 (Power Transmission Mechanisms)",
    },
    {
        "filename": "efficiency-calculator.html",
        "lessonId": "M-017",
        "description": "Mousetrap car energy efficiency calculator with Sankey flow diagram and loss breakdown",
        "termCount": 4,
        "originalTarget": "M-017 (Analysis Activity: Calculations and Efficiency)",
    },
    {
        "filename": "iteration-tracker.html",
        "lessonId": "C-031",
        "description": "Design iteration log with bar chart visualization and pre-loaded mousetrap car demo data",
        "termCount": 5,
        "originalTarget": "C-014 (Design Iteration and Communication)",
    },
]


def list_folder(session, folder_id):
    resp = session.get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "files(id,name,mimeType,size)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "pageSize": 200,
        },
    )
    return resp.json().get("files", [])


def find_lesson_folder(session, course_folder_id, lesson_id):
    files = list_folder(session, course_folder_id)
    for f in files:
        if f["name"] == lesson_id and "folder" in f.get("mimeType", ""):
            return f["id"]
    return None


def get_course_folders(session):
    files = list_folder(session, DRIVE_ROOT_ID)
    return {f["name"]: f["id"] for f in files if "folder" in f.get("mimeType", "")}


def upload_or_update(session, folder_id, filename, content_bytes):
    """Upload file to Drive folder; update if same name already exists."""
    # Check for existing file
    existing = list_folder(session, folder_id)
    existing_file = next((f for f in existing if f["name"] == filename), None)

    BOUNDARY = "===gk12boundary==="
    metadata = json.dumps({"name": filename, "parents": [folder_id]})

    body = (
        f"--{BOUNDARY}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata}\r\n"
        f"--{BOUNDARY}\r\n"
        f"Content-Type: text/html; charset=UTF-8\r\n\r\n"
    ).encode("utf-8") + content_bytes + f"\r\n--{BOUNDARY}--".encode("utf-8")

    if existing_file:
        # PATCH (update content only — no need to re-parent)
        url = f"https://www.googleapis.com/upload/drive/v3/files/{existing_file['id']}?uploadType=media&supportsAllDrives=true"
        resp = session.patch(url, data=content_bytes, headers={"Content-Type": "text/html; charset=UTF-8"})
        if resp.status_code in (200, 201):
            return existing_file["id"], "updated"
        else:
            return None, f"patch_error_{resp.status_code}: {resp.text[:200]}"
    else:
        # POST new file
        url = f"https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true"
        resp = session.post(
            url,
            data=body,
            headers={"Content-Type": f"multipart/related; boundary=\"{BOUNDARY}\""},
        )
        if resp.status_code in (200, 201):
            file_id = resp.json().get("id")
            return file_id, "created"
        else:
            return None, f"upload_error_{resp.status_code}: {resp.text[:200]}"


def main():
    session = get_session()
    course_folders = get_course_folders(session)
    print(f"Course folders found: {list(course_folders.keys())}")
    print()

    results = []

    for widget in WIDGETS:
        lid = widget["lessonId"]
        filename = widget["filename"]
        filepath = INTERACTIVES_DIR / filename

        if not filepath.exists():
            print(f"  [SKIP] {filename} not found at {filepath}")
            results.append({**widget, "status": "file_not_found"})
            continue

        # Get course folder
        prefix = lid.split("-")[0]
        course_name = "Creationeering" if prefix == "C" else "Mousetrap Build"
        course_folder_id = course_folders.get(course_name)
        if not course_folder_id:
            print(f"  [SKIP] Course folder '{course_name}' not found in Drive")
            results.append({**widget, "status": "course_folder_missing"})
            continue

        # Find lesson folder
        lesson_folder_id = find_lesson_folder(session, course_folder_id, lid)
        if not lesson_folder_id:
            print(f"  [SKIP] Lesson folder '{lid}' not found under '{course_name}'")
            results.append({**widget, "status": "lesson_folder_missing"})
            continue

        # Read file
        content_bytes = filepath.read_bytes()
        size_kb = len(content_bytes) // 1024

        print(f"  Uploading {filename} → {lid} ({size_kb}KB)...")
        file_id, status = upload_or_update(session, lesson_folder_id, filename, content_bytes)

        if file_id:
            print(f"  OK [{status}] file_id={file_id}")
            results.append({**widget, "status": status, "driveFileId": file_id})
        else:
            print(f"  FAILED: {status}")
            results.append({**widget, "status": "error", "error": status})

        time.sleep(0.5)

    print()
    print("=" * 60)
    ok = [r for r in results if r.get("status") in ("created", "updated")]
    fail = [r for r in results if r.get("status") not in ("created", "updated")]
    print(f"Uploaded: {len(ok)}/{len(results)}")
    if fail:
        print(f"Failed/skipped: {[r['filename'] for r in fail]}")

    # Print final report
    print()
    for r in ok:
        print(f"  {r['lessonId']} -- {r['filename']} ({r['description'][:60]})")

    # Save log
    log = []
    if LOG_PATH.exists():
        try:
            log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            log = []

    for r in results:
        # Upsert by lessonId+filename
        existing = next((i for i, e in enumerate(log) if e.get("lessonId") == r["lessonId"] and e.get("filename") == r["filename"]), None)
        entry = {
            "lessonId": r["lessonId"],
            "filename": r["filename"],
            "description": r["description"],
            "termCount": r["termCount"],
            "status": r.get("status"),
        }
        if r.get("driveFileId"):
            entry["driveFileId"] = r["driveFileId"]
        if existing is not None:
            log[existing] = entry
        else:
            log.append(entry)

    LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"\nLog saved: {LOG_PATH}")

    return ok


if __name__ == "__main__":
    main()
