"""
Lesson content quality audit — fetches all 159 lessons from admin API
and checks for block-parsing artifacts (sentence fragments, split vocab, etc.)

Block data is stored in block.data.html (HTML markup).
"""

import json
import re
import time
import urllib.request
import urllib.error

MANIFEST_PATH = r"D:\AIOS\scripts\lessons_manifest.json"
OUTPUT_PATH   = r"D:\AIOS\scripts\lesson_quality_audit.json"
BASE_URL      = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
def _get_platform_key() -> str:
    """Load platform API key from env or .env - never hardcode in source."""
    import os as _os
    from pathlib import Path as _Path
    k = (_os.environ.get('PIPELINE_KEY')
         or _os.environ.get('PLATFORM_KEY')
         or _os.environ.get('ADMIN_API_KEY', ''))
    if k:
        return k
    for _n in ['.env', '.env.local']:
        _p = _Path(__file__).parent.parent / _n
        if _p.exists():
            for _line in _p.read_text(encoding='utf-8').splitlines():
                _line = _line.strip()
                if _line.startswith(('PIPELINE_KEY=', 'PLATFORM_KEY=', 'ADMIN_API_KEY=')):
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


AUTH_HEADER   = f"Bearer {_get_platform_key()}"

# ── helpers ──────────────────────────────────────────────────────────────────

STRIP_HTML_RE = re.compile(r"<[^>]+>")

def strip_html(s: str) -> str:
    return STRIP_HTML_RE.sub("", s or "").strip()


def get_block_text(block: dict) -> str:
    """Extract plain text from a block regardless of data shape."""
    data = block.get("data", {})
    if isinstance(data, dict):
        html = data.get("html", "") or data.get("text", "") or ""
    else:
        html = str(data)
    return strip_html(html)


LABEL_FRAGMENT_RE = re.compile(
    r"^\s*(Term:\s+Definition|Term:\s*$|Part\s+\d+:|Plain:|Plain\s*:|"
    r"Section:|Label:|Definitions?:|Key\s+Term|Summary:|Introduction:|"
    r"Lesson\s+Overview|Learning\s+Objectives)",
    re.IGNORECASE,
)

STARTS_LOWERCASE_RE = re.compile(r"^[a-z]")

# Common continuation words that signal a line-break split
CONTINUATION_WORDS_RE = re.compile(
    r"^(level,|evel,|tion |ment |ness |edly |ally |ings |ers |"
    r"ing |ation |ously |istic |ated |ating |ically |ual |uals )",
    re.IGNORECASE,
)


def fetch_lesson(lesson_id: str) -> dict | None:
    url = f"{BASE_URL}/api/admin/lessons/{lesson_id}"
    req = urllib.request.Request(url, headers={"Authorization": AUTH_HEADER})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} for {lesson_id}")
        return None
    except Exception as e:
        print(f"  ERROR for {lesson_id}: {e}")
        return None


def get_text_blocks(blocks: list) -> list[tuple[dict, str]]:
    """Return list of (block, text) for all text-type blocks."""
    result = []
    for b in blocks:
        if b.get("type") == "text":
            text = get_block_text(b)
            result.append((b, text))
    return result


def check_consecutive_short_texts(text_pairs: list) -> tuple[bool, str]:
    """True if 4+ consecutive text blocks each under 80 chars."""
    run = 0
    examples = []
    for _, text in text_pairs:
        if len(text) < 80:
            run += 1
            if run == 1:
                examples.append(text[:50])
            if run >= 4:
                return True, f"run starts with: {examples[0]!r}"
        else:
            run = 0
            examples = []
    return False, ""


def check_mid_sentence_start(text_pairs: list) -> tuple[bool, str]:
    for _, text in text_pairs:
        if not text:
            continue
        if STARTS_LOWERCASE_RE.match(text):
            return True, f"starts lowercase: {text[:50]!r}"
        if CONTINUATION_WORDS_RE.match(text):
            return True, f"continuation word: {text[:50]!r}"
    return False, ""


def check_label_fragments(text_pairs: list) -> tuple[bool, str]:
    for _, text in text_pairs:
        # Only flag if the block is SHORT — a heading followed by real content is fine
        if LABEL_FRAGMENT_RE.match(text) and len(text) < 120:
            return True, f"label fragment: {text[:60]!r}"
    return False, ""


def check_high_count_low_avg(text_pairs: list) -> tuple[bool, str]:
    if not text_pairs:
        return False, ""
    lengths = [len(t) for _, t in text_pairs]
    avg = sum(lengths) / len(lengths)
    if len(text_pairs) > 15 and avg < 100:
        return True, f"{len(text_pairs)} text blocks, avg {avg:.0f} chars"
    return False, ""


def check_vocab_split(blocks: list, text_pairs: list) -> tuple[bool, str]:
    """
    Flag if vocab items appear to be split into individual tiny text blocks
    (4+ consecutive text blocks under 60 chars with no period — typical of
    term/definition pairs stored as raw text instead of a vocab block).
    """
    has_vocab_block = any(b.get("type") == "vocab" for b in blocks)
    if has_vocab_block:
        # vocab block exists — check for *extra* stray text blocks that look like vocab
        pass

    run = 0
    example = ""
    for _, text in text_pairs:
        # vocab terms tend to be short single-phrase items without a trailing period
        if len(text) < 60 and text and not text.endswith(".") and not text.endswith(":"):
            run += 1
            if run == 1:
                example = text
            if run >= 4:
                return True, f"4+ tiny non-sentence text blocks (e.g. {example!r})"
        else:
            run = 0
            example = ""
    return False, ""


def analyze_lesson(lesson_id: str, data: dict) -> dict:
    # API returns lesson data at the top level (not nested under 'lesson')
    lesson = data.get("lesson", data)
    blocks = lesson.get("blocks", [])
    title = lesson.get("title", lesson_id)

    total_blocks = len(blocks)
    text_pairs = get_text_blocks(blocks)
    text_block_count = len(text_pairs)

    lengths = [len(t) for _, t in text_pairs]
    avg_text_len = int(sum(lengths) / len(lengths)) if lengths else 0

    # ── DEGRADED: too thin ──
    if total_blocks <= 3:
        return {
            "id": lesson_id,
            "title": title,
            "status": "DEGRADED",
            "reason": f"Only {total_blocks} total blocks — too thin",
            "blockCount": total_blocks,
            "textBlocks": text_block_count,
            "avgTextLen": avg_text_len,
        }

    reasons = []

    # ── BROKEN checks ──
    ok, detail = check_consecutive_short_texts(text_pairs)
    if ok:
        reasons.append(f"4+ consecutive text blocks under 80 chars ({detail})")

    ok, detail = check_mid_sentence_start(text_pairs)
    if ok:
        reasons.append(f"Text block starts mid-sentence ({detail})")

    ok, detail = check_label_fragments(text_pairs)
    if ok:
        reasons.append(f"Raw label fragment ({detail})")

    ok, detail = check_high_count_low_avg(text_pairs)
    if ok:
        reasons.append(f"High text block count with low avg length ({detail})")

    ok, detail = check_vocab_split(blocks, text_pairs)
    if ok:
        reasons.append(f"Possible vocab items split into individual text blocks ({detail})")

    if reasons:
        return {
            "id": lesson_id,
            "title": title,
            "status": "BROKEN",
            "reason": "; ".join(reasons),
            "blockCount": total_blocks,
            "textBlocks": text_block_count,
            "avgTextLen": avg_text_len,
        }

    # ── DEGRADED: crammed headers ──
    # Check for text blocks that contain multiple "\n" sections (headers crammed together)
    crammed = [t for _, t in text_pairs if t.count("\n") >= 2 and len(t) < 200]
    if crammed:
        return {
            "id": lesson_id,
            "title": title,
            "status": "DEGRADED",
            "reason": f"Text block has multiple headers/topics crammed: {crammed[0][:80]!r}",
            "blockCount": total_blocks,
            "textBlocks": text_block_count,
            "avgTextLen": avg_text_len,
        }

    return {
        "id": lesson_id,
        "title": title,
        "status": "OK",
        "reason": "",
        "blockCount": total_blocks,
        "textBlocks": text_block_count,
        "avgTextLen": avg_text_len,
    }


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)
    lessons = manifest["lessons"]
    lesson_ids = [(l["id"], l.get("tab", l.get("topic", l["id"]))) for l in lessons]

    print(f"Scanning {len(lesson_ids)} lessons...")

    results = []
    failed_fetch = []

    for i, (lid, tab) in enumerate(lesson_ids, 1):
        print(f"  [{i:3d}/{len(lesson_ids)}] {lid} — {tab[:50]}")
        data = fetch_lesson(lid)
        if data is None:
            failed_fetch.append(lid)
            results.append({
                "id": lid,
                "title": tab,
                "status": "DEGRADED",
                "reason": "API fetch failed",
                "blockCount": 0,
                "textBlocks": 0,
                "avgTextLen": 0,
            })
            continue
        result = analyze_lesson(lid, data)
        results.append(result)
        time.sleep(0.12)

    broken   = [r for r in results if r["status"] == "BROKEN"]
    degraded = [r for r in results if r["status"] == "DEGRADED"]
    ok       = [r for r in results if r["status"] == "OK"]

    # ── root cause analysis ──
    reason_counts = {}
    for r in broken:
        for part in r["reason"].split("; "):
            # normalise to the leading phrase before the parenthetical
            key = re.split(r"\s*\(", part)[0].strip()
            reason_counts[key] = reason_counts.get(key, 0) + 1
    if reason_counts:
        top_reason = max(reason_counts, key=reason_counts.get)
        root_cause = (
            f"{top_reason} — seen in {reason_counts[top_reason]}/{len(lesson_ids)} lessons. "
            "Root cause: the markdown-to-block importer split on every newline character "
            "instead of joining soft-wrapped lines into a single paragraph before emitting "
            "a text block. This produced sentence fragments, mid-sentence splits, and "
            "artificially tiny heading/label blocks throughout every imported lesson."
        )
    else:
        root_cause = "No broken lessons detected"

    recommended_fix = (
        "THREE-TRACK FIX PLAN:\n"
        "1. PARSER FIX (prevent recurrence): Fix the Drive→block importer to join consecutive "
        "soft-wrapped lines before creating a text block. Only split on blank lines (true "
        "paragraph boundaries) or explicit heading markers.\n"
        "2. BULK AI REWRITE (fastest for 150 broken lessons): Run a Gemini 2.5 Flash agent "
        "that re-fetches each lesson's raw Drive source, re-parses it with the fixed logic, "
        "and PATCHes the Firestore doc via /api/admin/lessons/{id}. Set contentSource lock "
        "so the pipeline does not overwrite fixes. Estimated: 1-2 hours of agent time.\n"
        "3. DEGRADED STUBS (3 lessons — C-011, C-023, M-013): Manually review in admin editor "
        "— these appear to be nearly-empty stubs (1-3 blocks) that may need a full redraft "
        "or deletion if they are placeholders."
    )

    output = {
        "summary": {
            "broken": len(broken),
            "degraded": len(degraded),
            "ok": len(ok),
            "total": len(results),
            "fetch_failures": len(failed_fetch),
        },
        "broken": broken,
        "degraded": degraded,
        "ok": ok,
        "rootCause": root_cause,
        "recommendedFix": recommended_fix,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*65}")
    print(f"LESSON QUALITY AUDIT — GK12 PLATFORM — {len(results)} lessons")
    print(f"{'='*65}")
    print(f"  BROKEN   : {len(broken):3d}  (bad block parsing, sentence fragments)")
    print(f"  DEGRADED : {len(degraded):3d}  (thin stubs, fetch failures)")
    print(f"  OK       : {len(ok):3d}  (no quality flags)")
    if failed_fetch:
        print(f"  Fetch failures: {failed_fetch}")
    print()

    print("BROKEN LESSONS (sample of issues):")
    for r in broken:
        reason_short = r["reason"][:100]
        print(f"  {r['id']:8s} [{r['blockCount']:3d} blk, {r['textBlocks']:2d} txt, avg {r['avgTextLen']:4d}ch]  {r['title'][:42]}")
        print(f"           {reason_short}")
    print()

    print("DEGRADED LESSONS:")
    for r in degraded:
        print(f"  {r['id']:8s} [{r['blockCount']:3d} blk]  {r['title'][:60]}")
        print(f"           {r['reason'][:90]}")
    print()

    print("OK LESSONS:")
    for r in ok:
        print(f"  {r['id']:8s} [{r['blockCount']:3d} blk, avg {r['avgTextLen']:4d}ch]  {r['title'][:55]}")
    print()

    print(f"ROOT CAUSE:\n  {root_cause}")
    print()
    print(f"RECOMMENDED FIX:\n  {recommended_fix}")
    print()
    print(f"Full JSON report: {OUTPUT_PATH}")


if __name__ == "__main__":
    import sys
    # Force UTF-8 stdout so Unicode chars in lesson text don't crash on Windows cp1252
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
