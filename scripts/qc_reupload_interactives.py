"""
qc_reupload_interactives.py

Uploads all locally-generated HTML interactives (in scripts/interactives/{lessonId}/)
to Firebase Storage via /api/admin/interactives, then fixes the lesson's embed blocks
so each one has the correct proxy URL.

Existing empty-src embed blocks are matched to files by type label. New embed blocks
are appended for files that have no corresponding embed block yet.

Usage:
  python scripts/qc_reupload_interactives.py --dry-run         # preview
  python scripts/qc_reupload_interactives.py --save            # upload + patch
  python scripts/qc_reupload_interactives.py --lesson C-007    # single lesson
  python scripts/qc_reupload_interactives.py --save --force    # re-upload even if src filled
"""

import argparse, base64, json, os, random, re, string, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
INTERACTIVES_DIR = Path(__file__).parent / "interactives"
MANIFEST_PATH    = Path(__file__).parent / "lessons_manifest.json"
LOG_PATH         = Path(__file__).parent / "interactive_upload_log.json"

# Human-readable label for each interactive file type
FILE_LABELS = {
    "flashcards.html":  "Vocabulary Flashcards",
    "concept.html":     "Interactive Activity",
    "ocv.html":         "OCV Explorer",
    "vocab.html":       "Vocabulary Review",
    "simulation.html":  "Interactive Simulation",
    "physics.html":     "Physics Sandbox",
    "model.html":       "3D System Viewer",
}

# accordion.html used a "Parts 1-5" structure that doesn't match how lessons are written.
# Replaced by the lesson outline side panel in the lesson player UI.
SKIP_FILES = {"accordion.html"}


def _get_platform_key() -> str:
    import os as _os
    from pathlib import Path as _Path
    k = _os.environ.get('PIPELINE_KEY') or _os.environ.get('PLATFORM_KEY', '')
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=')) and '=' in _line:
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


# ── Platform API ──────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str, key: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  Fetch error: {e}")
        return None


def _fix_scrollbar(html: str) -> str:
    """Inject overflow:hidden on html+body so interactives never show a scrollbar in an iframe."""
    if "overflow: hidden" in html or "overflow:hidden" in html:
        return html
    fix = "<style>html,body{overflow:hidden!important;height:100%!important}</style>"
    if "</head>" in html:
        return html.replace("</head>", fix + "</head>", 1)
    return fix + html


def upload_file(lesson_id: str, filename: str, html: str, key: str) -> str | None:
    payload = json.dumps({
        "lessonId": lesson_id,
        "filename": filename,
        "mimeType": "text/html; charset=utf-8",
        "dataBase64": base64.b64encode(html.encode("utf-8")).decode(),
    }).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/interactives", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("url") if result.get("ok") else None
    except urllib.error.HTTPError as e:
        print(f"  Upload HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return None
    except Exception as e:
        print(f"  Upload error: {e}")
        return None


def patch_blocks(lesson_id: str, blocks: list, key: str) -> bool:
    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


def gen_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=9))


# ── Per-lesson processing ─────────────────────────────────────────────────────

def process_lesson(lesson_id: str, key: str, dry_run: bool, force: bool) -> dict:
    local_dir = INTERACTIVES_DIR / lesson_id
    if not local_dir.exists():
        return {"id": lesson_id, "status": "no_local_files"}

    html_files = sorted(
        [f for f in local_dir.glob("*.html") if f.name not in SKIP_FILES],
        key=lambda f: f.name,
    )
    if not html_files:
        return {"id": lesson_id, "status": "no_local_files"}

    lesson = fetch_lesson(lesson_id, key)
    if not lesson:
        return {"id": lesson_id, "status": "fetch_error"}

    blocks: list = lesson.get("blocks", [])

    # Build a map of existing embed blocks: filename stem → block index
    embed_by_filename: dict[str, int] = {}
    for i, b in enumerate(blocks):
        if b.get("type") != "embed":
            continue
        # Support both old "src"/"label" and correct "url"/"title" field names
        url: str = b.get("data", {}).get("url", "") or b.get("data", {}).get("src", "") or ""
        title: str = b.get("data", {}).get("title", "") or b.get("data", {}).get("label", "") or ""
        # Match by url path segment or title
        for fname, flabel in FILE_LABELS.items():
            stem = fname.replace(".html", "")
            if stem in url or flabel.lower() in title.lower():
                embed_by_filename[fname] = i
                break

    # Collect empty embed blocks in order (to fill by file order)
    empty_embeds = [i for i, b in enumerate(blocks)
                    if b.get("type") == "embed" and not (
                        (b.get("data", {}).get("url") or "") + (b.get("data", {}).get("src") or "")
                    ).strip()]

    print(f"\n  [{lesson_id}] {len(html_files)} files | {len(empty_embeds)} empty embeds")
    if dry_run:
        for f in html_files:
            label = FILE_LABELS.get(f.name, f.stem)
            existing = embed_by_filename.get(f.name)
            action = "update" if existing is not None else "add"
            print(f"    {f.name} ({f.stat().st_size // 1024}KB) → {action} embed ({label})")
        return {"id": lesson_id, "status": "dry_run", "files": len(html_files)}

    updated_blocks = list(blocks)
    empty_idx = 0  # pointer into empty_embeds list
    uploaded = 0
    skipped = 0

    for html_file in html_files:
        filename = html_file.name
        label = FILE_LABELS.get(filename, html_file.stem.replace("-", " ").title())

        # Check if already uploaded (url or src non-empty) unless force
        if filename in embed_by_filename:
            block_idx = embed_by_filename[filename]
            d = updated_blocks[block_idx].get("data", {})
            existing_url = d.get("url", "") or d.get("src", "")
            if existing_url and not force:
                skipped += 1
                continue

        html = _fix_scrollbar(html_file.read_text(encoding="utf-8", errors="replace"))
        proxy_url = upload_file(lesson_id, filename, html, key)
        if not proxy_url:
            print(f"    {filename}: upload FAILED")
            continue

        print(f"    {filename}: uploaded → {proxy_url}")
        uploaded += 1

        if filename in embed_by_filename:
            # Update existing embed block — use correct field names, strip legacy src/label
            block_idx = embed_by_filename[filename]
            old_data = {k: v for k, v in updated_blocks[block_idx].get("data", {}).items()
                        if k not in ("src", "label")}
            updated_blocks[block_idx] = {
                **updated_blocks[block_idx],
                "data": {**old_data, "url": proxy_url, "title": label},
            }
        elif empty_idx < len(empty_embeds):
            # Fill the next empty embed block
            block_idx = empty_embeds[empty_idx]
            old_data = {k: v for k, v in updated_blocks[block_idx].get("data", {}).items()
                        if k not in ("src", "label")}
            updated_blocks[block_idx] = {
                **updated_blocks[block_idx],
                "data": {**old_data, "url": proxy_url, "title": label},
            }
            empty_idx += 1
        else:
            # Append new embed block
            updated_blocks.append({
                "id": gen_id(),
                "type": "embed",
                "data": {"url": proxy_url, "height": 520, "title": label},
                "meta": {"spacing": "md", "qcStatus": "approved"},
            })

        time.sleep(0.2)

    if uploaded == 0:
        return {"id": lesson_id, "status": "skipped_all_filled", "skipped": skipped}

    ok = patch_blocks(lesson_id, updated_blocks, key)
    status = "done" if ok else "patch_failed"
    print(f"  [{lesson_id}] {'OK' if ok else 'PATCH FAILED'}: {uploaded} uploaded, {skipped} skipped")
    return {"id": lesson_id, "status": status, "uploaded": uploaded}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save",    action="store_true")
    parser.add_argument("--lesson",  help="Single lesson ID")
    parser.add_argument("--force",   action="store_true", help="Re-upload even if src already filled")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    key = _get_platform_key()
    if not key:
        print("PIPELINE_KEY not found"); sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lesson_ids = [l["id"] for l in manifest["lessons"]]

    if args.lesson:
        lesson_ids = [args.lesson.upper()]

    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"\nQC Reupload Interactives [{mode}] — {len(lesson_ids)} lesson(s) | force={args.force}")
    print("=" * 60)

    results = []
    counts: dict[str, int] = {}
    for i, lid in enumerate(lesson_ids, 1):
        print(f"[{i}/{len(lesson_ids)}]", end="")
        r = process_lesson(lid, key, dry_run=args.dry_run, force=args.force)
        results.append(r)
        s = r["status"]
        counts[s] = counts.get(s, 0) + 1
        time.sleep(0.1)

    print(f"\n{'='*60}")
    print("SUMMARY:", counts)
    errors = [r["id"] for r in results if "fail" in r.get("status", "")]
    if errors:
        print("Failed:", errors)


if __name__ == "__main__":
    main()
