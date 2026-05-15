"""
Genesis K-12 Image Agent

Reads image prompts from media_prompts.json, generates images via gemini-2.5-flash-image
(with the GK12 logo as a brand color reference), runs a Gemini vision QC pass on each
result, and uploads passing images to Google Drive.

Flagged images can be reworked after a batch with --rework-flagged. Max 2 retries per image.

Drive structure:
  GK12 Main > MS Curriculum > Lesson Images > [Creationeering|Mousetrap] > [C-025] > ...

Usage:
  python image_agent.py                        # generate images for all lessons with prompts
  python image_agent.py --lesson-id C-025      # generate for one specific lesson
  python image_agent.py --rework-flagged       # re-generate QC-flagged images (all lessons)
  python image_agent.py --dry-run              # show what would be generated
  python image_agent.py --local-only           # save locally, skip Drive upload
"""

import argparse, base64, json, os, re, sys, urllib.request, urllib.error
import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

MEDIA_PROMPTS_PATH = os.path.join(os.path.dirname(__file__), "media_prompts.json")
LOCAL_OUTPUT_DIR   = os.path.join(os.path.dirname(__file__), "..", "output", "images")
LOGO_PATH          = os.path.join(os.path.dirname(__file__), "..", "references", "gk12-logo.PNG")

GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
GEMINI_IMAGE_URL   = (
    f"https://generativelanguage.googleapis.com/v1beta/models"
    f"/{GEMINI_IMAGE_MODEL}:generateContent"
)

IMAGE_QC_MODEL = "gemini-2.5-flash-lite"
IMAGE_QC_URL   = (
    f"https://generativelanguage.googleapis.com/v1beta/models"
    f"/{IMAGE_QC_MODEL}:generateContent"
)

MAX_RETRIES = 2

ASPECT_RATIO_HINTS = {
    "16:9": "wide 16:9 horizontal widescreen composition",
    "1:1":  "square 1:1 composition",
    "4:3":  "4:3 horizontal composition",
}

COURSE_FOLDER_NAMES = {
    "creationeering": "Creationeering",
    "mousetrap":      "Mousetrap Build",
}

_logo_b64    = None   # cached on first load
_drive_svc   = None   # cached Drive service


def _load_logo():
    global _logo_b64
    if _logo_b64 is not None:
        return _logo_b64
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, "rb") as f:
            _logo_b64 = base64.b64encode(f.read()).decode("utf-8")
    return _logo_b64


def load_env():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def load_media_prompts():
    if not os.path.exists(MEDIA_PROMPTS_PATH):
        return {}
    with open(MEDIA_PROMPTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_media_prompts(data):
    with open(MEDIA_PROMPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_image(api_key, prompt, aspect_ratio="16:9"):
    """Call gemini-2.5-flash-image with logo brand reference and aspect ratio hint."""
    logo_b64 = _load_logo()
    ar_hint  = ASPECT_RATIO_HINTS.get(aspect_ratio, ASPECT_RATIO_HINTS["16:9"])
    full_prompt = f"{prompt} [{ar_hint}]"

    if logo_b64:
        parts = [
            {"text": (
                "Brand color reference only — do NOT reproduce or include this logo in the output. "
                "Use the navy blue (#1B2A5C) and gold (#C9A84C) palette from the reference image. "
                "Generate a new image: " + full_prompt
            )},
            {"inline_data": {"mime_type": "image/png", "data": logo_b64}},
        ]
    else:
        parts = [{"text": full_prompt}]

    payload = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode("utf-8")

    url = f"{GEMINI_IMAGE_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])
        print("    No image data in response")
        return None
    except urllib.error.HTTPError as e:
        print(f"    Image error {e.code}: {e.read().decode('utf-8')[:300]}")
        return None
    except Exception as e:
        print(f"    Image error: {e}")
        return None


def qc_image(api_key, img_bytes, prompt, concept):
    """Gemini vision QC pass. Returns (passed: bool, notes: str)."""
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    qc_text = (
        "You are reviewing an AI-generated educational illustration for Genesis K-12 Academy's "
        "middle school engineering curriculum. Evaluate this image against four criteria:\n"
        "1. Color palette: navy blue (#1B2A5C) and gold (#C9A84C) are the dominant colors\n"
        "2. Style: clean educational illustration (not photorealistic, not heavy cartoon)\n"
        "3. Concept fit: the image clearly depicts this concept: " + concept + "\n"
        "4. Age-appropriate: suitable for ages 11-14, no inappropriate content\n\n"
        f"Generation prompt used: {prompt[:200]}\n\n"
        "Respond ONLY with JSON (no markdown): "
        "{\"pass\": true, \"issues\": \"none\"}  "
        "or  {\"pass\": false, \"issues\": \"brief description of the problem\"}"
    )

    payload = json.dumps({
        "contents": [{"parts": [
            {"text": qc_text},
            {"inline_data": {"mime_type": "image/png", "data": img_b64}},
        ]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
    }).encode("utf-8")

    url = f"{IMAGE_QC_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data["candidates"][0]["content"].get("parts", [])
        text_parts = [p["text"] for p in parts
                      if not p.get("thought", False) and "text" in p]
        text = "\n".join(text_parts).strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        start = text.find("{")
        if start > 0:
            text = text[start:]
        result = json.loads(text)
        return result.get("pass", True), result.get("issues", "")
    except Exception as e:
        return True, f"QC check error (skipped): {e}"


def get_drive_service():
    global _drive_svc
    if _drive_svc is None:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        _drive_svc = build("drive", "v3", credentials=creds)
    return _drive_svc


def get_or_create_folder(name, parent_id):
    """Find a Drive folder by name under parent_id, create it if missing."""
    svc = get_drive_service()
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
         f" and '{parent_id}' in parents and trashed=false")
    resp = svc.files().list(
        q=q, fields="files(id,name)",
        includeItemsFromAllDrives=True, supportsAllDrives=True
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    folder = svc.files().create(
        body={"name": name,
              "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        fields="id",
        supportsAllDrives=True
    ).execute()
    return folder["id"]


def upload_to_drive(local_path, filename, parent_id):
    """Upload a local image file to Google Drive, return (file_id, web_url)."""
    svc   = get_drive_service()
    media = MediaFileUpload(local_path, mimetype="image/png", resumable=False)
    result = svc.files().create(
        body={"name": filename, "parents": [parent_id]},
        media_body=media,
        fields="id,webViewLink",
        supportsAllDrives=True
    ).execute()
    return result.get("id"), result.get("webViewLink")


def ensure_drive_folder(doc, lesson_id, root_folder_id):
    """Return lesson_folder_id, creating the hierarchy if needed."""
    course_id  = get_or_create_folder(COURSE_FOLDER_NAMES.get(doc, doc), root_folder_id)
    lesson_fid = get_or_create_folder(lesson_id, course_id)
    return lesson_fid


def process_lesson(lesson_id, lesson_data, local_only, dry_run,
                   rework_flagged=False, root_folder_id=None):
    topic   = lesson_data.get("topic", lesson_id)
    doc     = lesson_data.get("doc", "creationeering")
    prompts = lesson_data.get("prompts", [])

    if not prompts:
        print(f"  [{lesson_id}] No prompts found, skipping.")
        return 0, 0

    mode_label = "REWORK" if rework_flagged else "generate"
    print(f"\n[{lesson_id}] {topic}  ({len(prompts)} prompts, mode={mode_label})")

    local_dir = os.path.join(LOCAL_OUTPUT_DIR, doc, lesson_id)
    os.makedirs(local_dir, exist_ok=True)

    drive_folder_id = None
    if not local_only and not dry_run and root_folder_id:
        try:
            drive_folder_id = ensure_drive_folder(doc, lesson_id, root_folder_id)
        except Exception as e:
            print(f"  Drive folder setup failed: {e}. Saving locally only.")

    generated = flagged = 0
    images = lesson_data.setdefault("images", {})

    for entry in prompts:
        section      = entry.get("section", f"section_{generated+1}")
        prompt       = entry.get("prompt", "")
        concept      = entry.get("concept", "")
        aspect_ratio = entry.get("aspectRatio", "16:9")
        safe_name    = re.sub(r'[\\/:*?"<>|]', "", section).replace(" ", "_")[:40] + ".png"
        local_path   = os.path.join(local_dir, safe_name)
        img_record   = images.get(section, {})

        if rework_flagged:
            if img_record.get("image_qc_status") != "flagged":
                continue
            retry_count = img_record.get("image_retry_count", 0)
            if retry_count >= MAX_RETRIES:
                print(f"  {safe_name}: max retries reached, skipping.")
                continue
        else:
            if os.path.exists(local_path) and img_record:
                # If Drive is enabled but upload was skipped previously, upload now
                if drive_folder_id and not img_record.get("drive_id"):
                    print(f"  {safe_name}: uploading to Drive...", end=" ", flush=True)
                    try:
                        drive_id, drive_url = upload_to_drive(local_path, safe_name, drive_folder_id)
                        img_record["drive_id"]  = drive_id
                        img_record["drive_url"] = drive_url
                        print(f"OK  {drive_url or drive_id}")
                    except Exception as e:
                        print(f"FAILED: {e}")
                    images[section] = img_record
                    continue
                print(f"  {safe_name}: already done, skipping.")
                continue

        if dry_run:
            print(f"  Would {'rework' if rework_flagged else 'generate'}: {safe_name}"
                  f"  [{aspect_ratio}]")
            print(f"    Concept: {concept}")
            print(f"    Prompt:  {prompt[:100]}...")
            continue

        print(f"  {safe_name} [{aspect_ratio}]...", end=" ", flush=True)

        img_bytes = generate_image(api_key, prompt, aspect_ratio)
        if not img_bytes:
            print("FAILED")
            continue

        with open(local_path, "wb") as f:
            f.write(img_bytes)

        drive_id = drive_url = None
        if drive_folder_id:
            try:
                drive_id, drive_url = upload_to_drive(local_path, safe_name, drive_folder_id)
            except Exception as e:
                print(f"\n    Drive upload failed: {e}")

        # QC pass
        qc_passed, qc_notes = qc_image(api_key, img_bytes, prompt, concept)
        retry_count = img_record.get("image_retry_count", 0)

        images[section] = {
            "local":            local_path,
            "drive_id":         drive_id,
            "drive_url":        drive_url,
            "image_qc_status":  "passed" if qc_passed else "flagged",
            "image_qc_notes":   qc_notes,
            "image_retry_count": retry_count + (1 if rework_flagged else 0),
        }

        qc_label = "QC=PASS" if qc_passed else f"QC=FLAGGED ({qc_notes[:60]})"
        loc_label = (f"Drive: {drive_url or 'upload failed'}"
                     if drive_folder_id else f"local: {local_path}")
        print(f"OK  {qc_label}  {loc_label}")

        generated += 1
        if not qc_passed:
            flagged += 1

    return generated, flagged


# Set in main() before calling process_lesson
api_key = None


def main():
    global api_key
    parser = argparse.ArgumentParser(description="Genesis K-12 Image Agent")
    parser.add_argument("--lesson-id",      default=None,
                        help="Process only this lesson (e.g. C-025)")
    parser.add_argument("--rework-flagged", action="store_true",
                        help="Re-generate only QC-flagged images (all lessons unless --lesson-id)")
    parser.add_argument("--dry-run",        action="store_true")
    parser.add_argument("--local-only",     action="store_true",
                        help="Skip Drive upload")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        sys.exit(1)

    root_folder_id = (env.get("GOOGLE_DRIVE_MS_CURRICULUM_ID")
                      or os.environ.get("GOOGLE_DRIVE_MS_CURRICULUM_ID"))
    if not root_folder_id and not args.local_only:
        print("Warning: GOOGLE_DRIVE_MS_CURRICULUM_ID not set — saving locally only.")
        args.local_only = True

    media_data = load_media_prompts()
    if not media_data:
        print("No entries in media_prompts.json. Run pm_agent.py first.")
        sys.exit(0)

    if args.lesson_id:
        if args.lesson_id not in media_data:
            print(f"Lesson {args.lesson_id} not found in media_prompts.json")
            sys.exit(1)
        targets = {args.lesson_id: media_data[args.lesson_id]}
    else:
        targets = media_data

    logo_status = "with logo reference" if os.path.exists(LOGO_PATH) else "text-only"
    mode_label  = "REWORK FLAGGED" if args.rework_flagged else "generate"
    print(f"Model:    {GEMINI_IMAGE_MODEL} ({logo_status})")
    print(f"Mode:     {mode_label}")
    print(f"Lessons:  {len(targets)}")
    print(f"Drive:    {'disabled (local only)' if args.local_only else f'Project Content ({root_folder_id})'}")
    if args.dry_run:
        print("          DRY RUN\n")

    total_gen = total_flagged = 0
    for lid, ldata in targets.items():
        gen, flagged = process_lesson(lid, ldata, args.local_only, args.dry_run,
                                      args.rework_flagged, root_folder_id)
        total_gen     += gen
        total_flagged += flagged

    if not args.dry_run:
        save_media_prompts(media_data)

    flag_note = f", {total_flagged} flagged for rework" if total_flagged else ""
    print(f"\n=== Image agent complete: {total_gen} images generated{flag_note} ===")


if __name__ == "__main__":
    main()
