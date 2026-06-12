"""
Genesis K-12 — Lesson Audio Narration Generator

Converts lesson block content to MP3 narration using Google Cloud Text-to-Speech.
Uploads audio to Firebase Storage and patches the lesson with an audioUrl field.

Auth: uses google-cloud-texttospeech SDK with Application Default Credentials (ADC).
      On Cloud Run the default service account is used. Locally, authenticate once with:
        gcloud auth application-default login

Storage: audio/{lessonId}/narration.mp3  (download-token protected, same as images)

Usage:
  python scripts/generate_lesson_audio.py --lesson-id C-006 --dry-run
  python scripts/generate_lesson_audio.py --lesson-id C-006 --save
  python scripts/generate_lesson_audio.py --course C --save
  python scripts/generate_lesson_audio.py --all --save

Requires:
  pip install google-cloud-texttospeech
  TTS API enabled: https://console.cloud.google.com/apis/library/texttospeech.googleapis.com
"""

import argparse, base64, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL  = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
def _get_platform_key() -> str:
    """Load platform API key from .env — never hardcode in source."""
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
                    return _line.split('=', 1)[1].strip().strip('""')
    return ''
PLATFORM_KEY = _get_platform_key()
MANIFEST_PATH = Path(__file__).parent / "lessons_manifest.json"
LOG_PATH = Path(__file__).parent / "audio_generation_log.json"

# Target voice — Neural2 supports up to 5000 chars/request
VOICE_NAME     = "en-US-Neural2-J"   # professional male narrator
VOICE_LANGUAGE = "en-US"
AUDIO_ENCODING = "MP3"

# TTS chunk size (leave headroom under 5000 char limit)
CHUNK_SIZE = 4500

# Exempt block types from narration text
SKIP_TYPES = {"divider", "embed", "math"}


# ── Text extraction from blocks ────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;",  "<", text)
    text = re.sub(r"&gt;",  ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;",  "'", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_narration_text(blocks: list[dict]) -> str:
    """Convert lesson blocks to narration-ready plain text."""
    parts = []

    for block in blocks:
        t = block.get("type", "")
        d = block.get("data", {})

        if t in SKIP_TYPES:
            continue

        if t == "text":
            text = _strip_html(d.get("html", ""))
            if text:
                parts.append(text)

        elif t == "callout":
            label_map = {
                "info":     "Note:",
                "tip":      "Tip:",
                "warning":  "Warning:",
                "biblical": "Biblical connection:",
            }
            label = label_map.get(d.get("variant", "info"), "Note:")
            text = _strip_html(d.get("html", ""))
            if text:
                parts.append(f"{label} {text}")

        elif t == "image":
            caption = d.get("caption", "").strip()
            if caption:
                parts.append(f"[Image: {caption}]")

        elif t == "vocab":
            items = d.get("items", [])
            if items:
                parts.append("Key vocabulary:")
                for item in items:
                    term = item.get("term", "").strip()
                    defn = item.get("definition", "").strip()
                    if term and defn:
                        parts.append(f"{term}: {defn}")

        elif t == "accordion":
            title = d.get("title", "").strip()
            body  = _strip_html(d.get("html", ""))
            if title:
                parts.append(title + ".")
            if body:
                parts.append(body)

        elif t == "accordion-grid":
            for item in d.get("items", []):
                title = item.get("title", "").strip()
                body  = _strip_html(item.get("html", ""))
                if title:
                    parts.append(title + ".")
                if body:
                    parts.append(body)

        elif t == "tabs":
            for tab in d.get("tabs", []):
                label = tab.get("title", "").strip()
                body  = _strip_html(tab.get("html", ""))
                if label:
                    parts.append(label + ".")
                if body:
                    parts.append(body)

        elif t in ("bordered-note", "columns"):
            html = d.get("html", "") or " ".join(str(c) for c in d.get("cols", []))
            text = _strip_html(html)
            if text:
                parts.append(text)

        elif t == "carousel":
            for slide in d.get("slides", []):
                title = slide.get("title", "").strip()
                body  = _strip_html(slide.get("html", ""))
                if title:
                    parts.append(title + ".")
                if body:
                    parts.append(body)

    return "\n\n".join(p for p in parts if p.strip())


# ── Google Cloud TTS ───────────────────────────────────────────────────────────

def synthesize_chunks(text: str) -> bytes:
    """Synthesize text to MP3 using Google Cloud TTS, chunked for long lessons."""
    try:
        from google.cloud import texttospeech
    except ImportError:
        sys.exit("google-cloud-texttospeech not installed. Run: pip install google-cloud-texttospeech")

    client = texttospeech.TextToSpeechClient()
    voice  = texttospeech.VoiceSelectionParams(
        language_code=VOICE_LANGUAGE,
        name=VOICE_NAME,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.95,  # slightly slower for clarity
        pitch=0.0,
    )

    # Split into chunks at sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 > CHUNK_SIZE and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip() if current else sentence
    if current:
        chunks.append(current.strip())

    mp3_parts = []
    for i, chunk in enumerate(chunks):
        if not chunk:
            continue
        synthesis_input = texttospeech.SynthesisInput(text=chunk)
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        mp3_parts.append(response.audio_content)
        if len(chunks) > 1:
            print(f"    Chunk {i+1}/{len(chunks)}: {len(chunk)} chars → {len(response.audio_content):,} bytes")
        time.sleep(0.1)

    return b"".join(mp3_parts)


# ── Platform API ───────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {PLATFORM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  Fetch error: {e}")
        return None


def upload_audio(lesson_id: str, mp3_bytes: bytes) -> str | None:
    """Upload MP3 to Firebase Storage via platform audio endpoint. Returns URL."""
    payload = json.dumps({
        "lessonId":   lesson_id,
        "dataBase64": base64.b64encode(mp3_bytes).decode(),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/audio",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read())
            return result.get("url")
    except Exception as e:
        print(f"  Upload error: {e}")
        return None


def patch_audio_url(lesson_id: str, audio_url: str) -> bool:
    payload = json.dumps({"audioUrl": audio_url}).encode("utf-8")
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        data=payload,
        headers={"Authorization": f"Bearer {PLATFORM_KEY}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"  Patch error: {e}")
        return False


# ── Main logic ─────────────────────────────────────────────────────────────────

def load_log() -> dict:
    if LOG_PATH.exists():
        try:
            return json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_log(log: dict):
    LOG_PATH.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def process_lesson(lesson_id: str, dry_run: bool, log: dict) -> str:
    lesson = fetch_lesson(lesson_id)
    if not lesson:
        return "fetch_failed"

    title  = lesson.get("title", lesson_id)
    blocks = lesson.get("blocks", [])
    if not blocks:
        print(f"  [{lesson_id}] No blocks — skipping")
        return "skipped"

    text = extract_narration_text(blocks)
    word_count = len(text.split())
    print(f"  [{lesson_id}] {title[:45]} — {word_count} words")

    if word_count < 30:
        print(f"    Too short — skipping")
        return "skipped"

    if dry_run:
        print(f"    Would synthesize ~{word_count // 150 + 1} min audio")
        return "dry_run"

    print(f"    Synthesizing...")
    mp3 = synthesize_chunks(text)
    print(f"    Generated: {len(mp3):,} bytes ({len(mp3) / 1024:.0f} KB)")

    print(f"    Uploading...")
    url = upload_audio(lesson_id, mp3)
    if not url:
        return "upload_failed"

    ok = patch_audio_url(lesson_id, url)
    if not ok:
        return "patch_failed"

    log[lesson_id] = {"status": "done", "url": url, "words": word_count, "bytes": len(mp3)}
    print(f"    ✓ Patched audioUrl")
    return "done"


def main():
    parser = argparse.ArgumentParser(description="Generate lesson audio narration via Google Cloud TTS")
    parser.add_argument("--lesson-id", help="Single lesson ID")
    parser.add_argument("--course",    choices=["C", "M"], help="All lessons in a course")
    parser.add_argument("--all",       action="store_true",  help="All lessons in manifest")
    parser.add_argument("--dry-run",   action="store_true",  help="Extract text, show word count, skip synthesis")
    parser.add_argument("--save",      action="store_true",  help="Run synthesis and upload")
    parser.add_argument("--force",     action="store_true",  help="Re-generate even if already done")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        args.dry_run = True
        print("Defaulting to --dry-run (pass --save to generate audio)")
    dry_run = not args.save

    if args.lesson_id:
        lesson_ids = [args.lesson_id]
    elif args.course or args.all:
        if not MANIFEST_PATH.exists():
            sys.exit("lessons_manifest.json not found — run platform_import.py first")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        lesson_ids = [l["id"] for l in manifest.get("lessons", [])]
        if args.course:
            lesson_ids = [lid for lid in lesson_ids if lid.startswith(args.course + "-")]
    else:
        parser.error("Provide --lesson-id, --course, or --all")

    log = load_log()

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\nGenerate Lesson Audio [{mode}]: {len(lesson_ids)} lesson(s)")
    print("=" * 60)

    counts = {"done": 0, "dry_run": 0, "skipped": 0, "error": 0}

    for lesson_id in lesson_ids:
        if not args.force and lesson_id in log and log[lesson_id].get("status") == "done":
            print(f"  [{lesson_id}] Already done — skipping (use --force to regenerate)")
            continue
        try:
            status = process_lesson(lesson_id, dry_run, log)
        except Exception as e:
            print(f"  [{lesson_id}] ERROR: {e}")
            status = "error"
        counts[status if status in counts else "error"] += 1
        if not dry_run:
            save_log(log)
        time.sleep(0.5)

    print(f"\n{'=' * 60}")
    print(f"Done — {counts}")
    if dry_run:
        print("Run with --save to generate and upload audio.")


if __name__ == "__main__":
    main()
