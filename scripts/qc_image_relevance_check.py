"""
qc_image_relevance_check.py

For each lesson image block with a live src URL, fetches the image and
checks with Claude Vision whether it:
  1. Matches the lesson topic and surrounding text context
  2. Is educational and appropriate for grades 6-8
  3. Is clearly applicable to the talking point it illustrates

Produces a JSON report — qc_image_relevance_report.json — with pass/fail
and a reason for each image. Optionally regenerates failed images with Imagen.

Usage:
  python scripts/qc_image_relevance_check.py --dry-run         # count only
  python scripts/qc_image_relevance_check.py --report          # check + save report
  python scripts/qc_image_relevance_check.py --report --regen  # check + replace fails
  python scripts/qc_image_relevance_check.py --lesson C-007    # single lesson
  python scripts/qc_image_relevance_check.py --course C        # Creationeering only
"""

import argparse, base64, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"
REPORT_PATH   = Path(__file__).parent / "qc_image_relevance_report.json"

CLAUDE_MODEL  = "claude-haiku-4-5-20251001"   # fast + cheap for vision QC
CLAUDE_URL    = "https://api.anthropic.com/v1/messages"
IMAGEN_MODEL  = "imagen-4.0-fast-generate-001"
IMAGEN_URL    = f"https://generativelanguage.googleapis.com/v1beta/models/{IMAGEN_MODEL}:predict"


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


def load_env() -> dict:
    env = {}
    for name in [".env", ".env.local"]:
        p = Path(__file__).parent.parent / name
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
    return env


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


def patch_lesson(lesson_id: str, blocks: list, key: str) -> bool:
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


def upload_image(lesson_id: str, filename: str, img_bytes: bytes, key: str) -> str | None:
    payload = json.dumps({
        "lessonId": lesson_id,
        "filename": filename,
        "mimeType": "image/png",
        "dataBase64": base64.b64encode(img_bytes).decode(),
    }).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/images", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("url") if result.get("ok") else None
    except Exception as e:
        print(f"  Upload error: {e}")
        return None


# ── Context extraction ────────────────────────────────────────────────────────

def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def get_surrounding_text(blocks: list, img_index: int, window: int = 2) -> str:
    """Return text from blocks immediately before and after the image block."""
    parts = []
    for i in range(max(0, img_index - window), min(len(blocks), img_index + window + 1)):
        if i == img_index:
            continue
        b = blocks[i]
        if b.get("type") == "text":
            text = strip_tags(b.get("data", {}).get("html", "")).strip()
            if text:
                parts.append(text[:300])
    return " ".join(parts)[:600]


# ── Image download ─────────────────────────────────────────────────────────────

def fetch_image_as_base64(url: str) -> tuple[str, str] | None:
    """Download image and return (base64_data, mime_type) or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GK12-QC/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            return base64.standard_b64encode(data).decode(), mime
    except Exception as e:
        print(f"    Image fetch error: {e}")
        return None


# ── Claude Vision check ───────────────────────────────────────────────────────

IMAGE_QC_PROMPT = """You are a quality reviewer for Genesis K-12 Academy's middle school engineering curriculum.

Lesson: "{title}"
Lesson context around this image:
{context}

Caption: {caption}

Look at this image and evaluate it against these standards:
1. RELEVANCE: Does it directly illustrate a concept from the surrounding lesson text?
2. EDUCATIONAL: Is it clear, informative, and appropriate for grades 6-8?
3. APPLICABLE: Could a student immediately connect this image to the talking point?

Respond with JSON only:
{{"pass": true/false, "score": 1-5, "reason": "one-sentence explanation"}}

Score guide: 5=perfect match, 4=good, 3=acceptable, 2=weak, 1=wrong/irrelevant
Fail if score <= 2."""


def check_image(img_b64: str, mime: str, title: str, context: str, caption: str,
                api_key: str) -> dict:
    prompt = IMAGE_QC_PROMPT.format(
        title=title, context=context or "(no surrounding text)", caption=caption or "(no caption)"
    )
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
        {"type": "text",  "text": prompt},
    ]
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 200,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    req = urllib.request.Request(
        CLAUDE_URL, data=payload,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        raw = result["content"][0]["text"].strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"pass": False, "score": 0, "reason": f"Parse error: {raw[:100]}"}
    except Exception as e:
        return {"pass": False, "score": 0, "reason": f"API error: {e}"}


# ── Imagen regeneration ───────────────────────────────────────────────────────

def regenerate_image(caption: str, title: str, gemini_key: str) -> bytes | None:
    prompt = (
        f"Educational illustration for middle school engineering, clean professional style, "
        f"no text or labels. Lesson: {title}. {caption}"
    )
    payload = json.dumps({
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "4:3"},
    }).encode()
    req = urllib.request.Request(
        f"{IMAGEN_URL}?key={gemini_key}", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        b64 = data.get("predictions", [{}])[0].get("bytesBase64Encoded")
        return base64.b64decode(b64) if b64 else None
    except Exception as e:
        print(f"    Imagen error: {e}")
        return None


# ── Per-lesson processing ─────────────────────────────────────────────────────

def process_lesson(lesson_id: str, key: str, env: dict,
                   dry_run: bool, regen: bool) -> dict:
    lesson = fetch_lesson(lesson_id, key)
    if not lesson:
        return {"id": lesson_id, "status": "fetch_error"}

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])

    img_blocks = [(i, b) for i, b in enumerate(blocks)
                  if b.get("type") == "image" and b.get("data", {}).get("src")]

    if not img_blocks:
        return {"id": lesson_id, "status": "no_images"}

    api_key     = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_key  = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")

    if dry_run:
        return {"id": lesson_id, "status": "dry_run", "image_count": len(img_blocks)}

    results  = []
    updated  = list(blocks)
    replaced = 0

    for img_idx, img_block in img_blocks:
        src     = img_block["data"]["src"]
        caption = img_block["data"].get("caption", "")
        context = get_surrounding_text(blocks, img_idx)

        print(f"    Image {img_idx}: {caption[:50]!r}...")

        img_data = fetch_image_as_base64(src)
        if not img_data:
            results.append({"idx": img_idx, "pass": False, "reason": "Could not download image"})
            continue

        img_b64, mime = img_data
        verdict = check_image(img_b64, mime, title, context, caption, api_key)
        results.append({"idx": img_idx, "caption": caption[:80], **verdict})

        status_char = "✓" if verdict.get("pass") else "✗"
        print(f"      {status_char} score={verdict.get('score',0)} — {verdict.get('reason','')[:80]}")

        if not verdict.get("pass") and regen and gemini_key:
            print(f"      Regenerating...")
            new_bytes = regenerate_image(caption, title, gemini_key)
            if new_bytes:
                filename = f"img_regen_{img_idx:03d}.png"
                new_url = upload_image(lesson_id, filename, new_bytes, key)
                if new_url:
                    updated[img_idx] = {
                        **img_block,
                        "data": {**img_block["data"], "src": new_url},
                    }
                    replaced += 1
                    print(f"      Replaced: {new_url[:60]}...")

        time.sleep(0.5)

    if replaced > 0:
        patch_lesson(lesson_id, updated, key)

    passed = sum(1 for r in results if r.get("pass"))
    failed = len(results) - passed
    return {
        "id": lesson_id, "status": "done", "title": title,
        "images": len(results), "passed": passed, "failed": failed,
        "replaced": replaced, "details": results,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Count images, no API calls")
    parser.add_argument("--report",  action="store_true", help="Run vision checks, save report")
    parser.add_argument("--regen",   action="store_true", help="Regenerate failed images (requires --report)")
    parser.add_argument("--lesson",  help="Single lesson ID")
    parser.add_argument("--course",  choices=["C", "M"])
    args = parser.parse_args()

    if not args.dry_run and not args.report:
        print("Pass --dry-run or --report"); sys.exit(1)
    if args.regen and not args.report:
        print("--regen requires --report"); sys.exit(1)

    key = _get_platform_key()
    env = load_env()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lesson_ids = [l["id"] for l in manifest["lessons"]]

    if args.lesson:
        lesson_ids = [args.lesson.upper()]
    elif args.course:
        lesson_ids = [lid for lid in lesson_ids if lid.startswith(args.course + "-")]

    mode = "DRY RUN" if args.dry_run else f"REPORT{' + REGEN' if args.regen else ''}"
    print(f"\nQC Image Relevance Check [{mode}] — {len(lesson_ids)} lesson(s)")
    print("=" * 60)

    all_results = []
    for i, lid in enumerate(lesson_ids, 1):
        print(f"[{i}/{len(lesson_ids)}] {lid}")
        r = process_lesson(lid, key, env, dry_run=args.dry_run, regen=args.regen)
        all_results.append(r)
        time.sleep(0.2)

    # Summary
    if not args.dry_run:
        total_imgs    = sum(r.get("images", 0) for r in all_results)
        total_passed  = sum(r.get("passed", 0) for r in all_results)
        total_failed  = sum(r.get("failed", 0) for r in all_results)
        total_replaced = sum(r.get("replaced", 0) for r in all_results)

        print(f"\n{'='*60}")
        print(f"Total images checked: {total_imgs}")
        print(f"  Passed: {total_passed} ({100*total_passed//max(1,total_imgs)}%)")
        print(f"  Failed: {total_failed}")
        if args.regen:
            print(f"  Replaced: {total_replaced}")

        REPORT_PATH.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nReport saved to {REPORT_PATH}")

        # Show worst offenders
        failures = [
            (r["id"], r.get("title",""), detail)
            for r in all_results
            for detail in r.get("details", [])
            if not detail.get("pass")
        ]
        if failures:
            print(f"\nFailed images ({len(failures)}):")
            for lid, title, d in failures[:15]:
                print(f"  {lid} idx={d['idx']} score={d.get('score',0)}: {d.get('reason','')[:70]}")
            if len(failures) > 15:
                print(f"  ... and {len(failures)-15} more (see report)")
    else:
        total = sum(r.get("image_count", 0) for r in all_results)
        lessons_with = sum(1 for r in all_results if r.get("status") == "dry_run")
        print(f"\nDRY RUN: {total} images in {lessons_with} lessons would be checked")
        print("Run with --report to execute vision checks")


if __name__ == "__main__":
    main()
