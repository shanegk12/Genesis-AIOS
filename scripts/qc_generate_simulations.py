"""
qc_generate_simulations.py

Generates a proper interactive simulation or game (simulation.html) for every
lesson using Claude claude-sonnet-5. Unlike the existing concept.html placeholder files
(which are static text overviews), simulation.html is a fully interactive
HTML5 experience — drag-and-drop, sliders, step-through simulations, scored
quizzes, or decision trees — built specifically around the lesson's content.

Workflow:
  1. Fetch lesson blocks from platform API
  2. Build a content excerpt (title + key text blocks)
  3. Call Claude to generate a self-contained interactive HTML file
  4. Save locally to scripts/interactives/{lessonId}/simulation.html
  5. Upload to Firebase Storage via platform /api/admin/images-style endpoint
  6. PATCH lesson to add an embed block pointing to the simulation

Usage:
  python scripts/qc_generate_simulations.py --dry-run          # preview only
  python scripts/qc_generate_simulations.py --save             # generate + upload
  python scripts/qc_generate_simulations.py --lesson C-007     # single lesson
  python scripts/qc_generate_simulations.py --course C         # Creationeering only
  python scripts/qc_generate_simulations.py --course M         # Mousetrap only
  python scripts/qc_generate_simulations.py --missing-only     # skip lessons that already have simulation.html
"""

import argparse, base64, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LIVE_URL         = "https://genesis-lms--genesis-modularity.us-central1.hosted.app"
INTERACTIVES_DIR = Path(__file__).parent / "interactives"
MANIFEST_PATH    = Path(__file__).parent / "lessons_manifest.json"
LOG_PATH         = Path(__file__).parent / "simulation_gen_log.json"

CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"
NAVY = "#1B3A5C"
GOLD = "#C9A84C"

SIMULATION_PROMPT = """You are building a self-contained HTML/JavaScript interactive activity \
for Genesis K-12 Academy's middle school engineering curriculum.

Lesson: "{title}"
Course: {course}

CONTENT EXCERPT:
{excerpt}

---

Create a FULLY INTERACTIVE simulation or game that lets students explore or \
demonstrate the core concept from this lesson. Requirements:

TECHNICAL:
- Single self-contained HTML file — zero CDN links, no external scripts or stylesheets
- All JavaScript and CSS inline in the file
- Works correctly inside an iframe (no window.parent or top-level navigation)
- Mobile-friendly layout (works on iPad)

DESIGN:
- GK12 color palette: navy {navy}, gold {gold}, white #ffffff, light gray #f7f9fc
- Clean, professional UI appropriate for grades 6-8
- Intuitive — students understand what to do without reading instructions
- 3-5 minutes to complete
- Ends with a score, result, or summary screen

INTERACTION — pick the type that BEST fits this lesson's concept:
- Drag-and-drop matching or sorting (good for classification/categorization concepts)
- Step-through simulation with next/back controls + "what happens?" prompts (good for processes)
- Adjustable slider simulation (adjust one variable, watch output change live — good for math/physics)
- Scored quiz with immediate feedback per question + final score (good for vocabulary/recall)
- Decision tree or branching scenario (good for design/ethics/trade-off concepts)
- Build-order activity (arrange steps in correct sequence — good for engineering processes)

CONTENT RULES:
- Base all content DIRECTLY on the lesson excerpt above — do not invent unrelated content
- Faith reference is optional and brief if included — never forced
- Grade-level language: clear, direct, no unexplained jargon

Output ONLY the complete HTML file from <!DOCTYPE html> to </html>. No explanation, no markdown fences."""


PHYSICS_PROMPT = """You are building a self-contained HTML5/JavaScript physics sandbox \
for Genesis K-12 Academy's middle school engineering curriculum.

Lesson: "{title}"
Course: {course}

CONTENT EXCERPT:
{excerpt}

---

Create a LIVE PHYSICS SANDBOX using HTML5 Canvas and pure JavaScript (no libraries). \
Students should be able to manipulate parameters and immediately see physical results.

TECHNICAL:
- Single self-contained HTML file — zero CDN, no external scripts
- HTML5 Canvas for rendering the simulation
- requestAnimationFrame game loop
- Works in an iframe (no window.parent references)
- Touch-friendly for iPad

PHYSICS SANDBOX IDEAS (pick the one most relevant to the lesson content):
- Force & motion: apply forces to an object, watch it accelerate; adjust mass/friction sliders
- Spring/energy: compress a spring, release, watch potential → kinetic energy transfer (perfect for mousetrap car)
- Projectile: set launch angle and speed, watch arc; measure distance
- Friction & surfaces: drag an object across surfaces with different coefficients
- Gear/pulley: adjust gear ratios, see mechanical advantage live
- Simple machines: lever, inclined plane, wedge — adjust and see force/distance trade-off
- Pendulum: vary length/mass, observe period change
- Wave: adjust frequency/amplitude, see wavelength change

REQUIREMENTS:
- At least 2 interactive controls (sliders, buttons, or click-drag)
- Real-time visual feedback as controls change
- Numerical readout of 1-2 key measurements
- GK12 colors: navy {navy}, gold {gold}
- Clean label for each control and measurement
- A "Reset" button

Output ONLY the complete HTML file. No explanation, no markdown fences."""


MODEL_PROMPT = """You are building a self-contained HTML5/JavaScript 3D system viewer \
for Genesis K-12 Academy's middle school engineering curriculum.

Lesson: "{title}"
Course: {course}

CONTENT EXCERPT:
{excerpt}

---

Create an INTERACTIVE 3D ISOMETRIC VIEWER using HTML5 Canvas or CSS 3D transforms \
(no Three.js or external libraries). Students can rotate, label, and explore a \
simplified 3D model of an engineering system from the lesson.

TECHNICAL:
- Single self-contained HTML file — zero CDN, no external scripts
- Use CSS 3D transforms OR HTML5 Canvas with isometric projection math
- Works in an iframe
- Touch/mouse rotation

VIEWER CONCEPTS (pick based on lesson content):
- Component diagram: labeled isometric view of the mousetrap car showing chassis, axle, wheel, lever arm
- System diagram: isometric building/structure with labeled load paths
- Machine cross-section: gear assembly, pulley system, or lever mechanism in 3D
- Process flow: 3D pipeline or system showing inputs → process → outputs
- Engineering drawing: orthographic 3 views (front/side/top) of a designed component

REQUIREMENTS:
- Click-and-drag or button rotation (at least left/right rotation)
- Labeled callouts for 3-5 key components
- "Exploded view" button that separates components to show how they fit together
- Component list sidebar with brief descriptions
- GK12 colors: navy {navy}, gold {gold}
- Clean, diagram-style aesthetic (not realistic textures)

Output ONLY the complete HTML file. No explanation, no markdown fences."""


# ── Env ───────────────────────────────────────────────────────────────────────

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
                    return _line.split('=', 1)[1].strip().strip('"\'')
    return ''


# ── Platform API ──────────────────────────────────────────────────────────────

def fetch_lesson(lesson_id: str, platform_key: str) -> dict | None:
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}",
        headers={"Authorization": f"Bearer {platform_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  Fetch error: {e}")
        return None


def upload_interactive(lesson_id: str, filename: str, html: str, platform_key: str) -> str | None:
    """Upload HTML to Firebase Storage via /api/admin/interactives. Returns proxy URL or None."""
    payload = json.dumps({
        "lessonId": lesson_id,
        "filename": filename,
        "mimeType": "text/html; charset=utf-8",
        "dataBase64": base64.b64encode(html.encode("utf-8")).decode(),
    }).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/interactives", data=payload,
        headers={"Authorization": f"Bearer {platform_key}", "Content-Type": "application/json"},
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


def patch_lesson_blocks(lesson_id: str, blocks: list, platform_key: str) -> bool:
    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        f"{LIVE_URL}/api/admin/lessons/{lesson_id}", data=payload,
        headers={"Authorization": f"Bearer {platform_key}", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("ok", False)
    except Exception as e:
        print(f"  PATCH error: {e}")
        return False


# ── Content extraction ────────────────────────────────────────────────────────

def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def build_excerpt(lesson: dict, max_chars: int = 2000) -> str:
    """Extract readable text from lesson blocks for use as AI context."""
    blocks = lesson.get("blocks", [])
    parts = []
    total = 0
    for block in blocks:
        btype = block.get("type", "")
        if btype == "text":
            text = strip_tags(block.get("data", {}).get("html", "")).strip()
            if text and total + len(text) < max_chars:
                parts.append(text)
                total += len(text)
        elif btype == "vocab":
            items = block.get("data", {}).get("items", [])
            for item in items[:5]:
                t, d = item.get("term", ""), item.get("definition", "")
                if t and d:
                    parts.append(f"{t}: {d}")
                    total += len(t) + len(d)
        elif btype == "callout":
            text = strip_tags(block.get("data", {}).get("html", "")).strip()
            if text:
                parts.append(f"[Note] {text[:200]}")
                total += len(text)
        if total >= max_chars:
            break
    return "\n".join(parts)[:max_chars]


# ── Claude generation ─────────────────────────────────────────────────────────

# Heavy interactives (simulation/model/physics) run ~7-8k output tokens — the old
# 8192 cap truncated them mid-logic. Sonnet 4.6 supports far larger output; give
# generous headroom so nothing is cut off.
MAX_OUTPUT_TOKENS = 32000


def _call_claude(prompt: str, api_key: str) -> str | None:
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        CLAUDE_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Refuse truncated output — better to skip than write a broken interactive.
        if data.get("stop_reason") == "max_tokens":
            print(f"  [skip] response hit max_tokens ({MAX_OUTPUT_TOKENS}) — truncated, not writing")
            return None
        text = data["content"][0]["text"].strip()
        text = re.sub(r"^```html\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^```\s*",     "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$",     "", text.strip())
        if not text.startswith("<!"):
            return None
        # Completeness guard — a valid full document ends at </html>.
        if not text.rstrip().lower().endswith("</html>"):
            print("  [skip] output does not end with </html> — incomplete, not writing")
            return None
        return text
    except urllib.error.HTTPError as e:
        print(f"  Claude API error {e.code}: {e.read().decode('utf-8')[:300]}")
        return None
    except Exception as e:
        print(f"  Claude API error: {e}")
        return None


def generate_simulation(title: str, lesson_id: str, excerpt: str, api_key: str) -> str | None:
    course = "Creationeering" if lesson_id.startswith("C-") else "Mousetrap Build"
    prompt = SIMULATION_PROMPT.format(
        title=title, course=course, excerpt=excerpt, navy=NAVY, gold=GOLD
    )

    return _call_claude(prompt, api_key)


def generate_physics(title: str, lesson_id: str, excerpt: str, api_key: str) -> str | None:
    course = "Creationeering" if lesson_id.startswith("C-") else "Mousetrap Build"
    prompt = PHYSICS_PROMPT.format(
        title=title, course=course, excerpt=excerpt, navy=NAVY, gold=GOLD
    )
    return _call_claude(prompt, api_key)


def generate_model(title: str, lesson_id: str, excerpt: str, api_key: str) -> str | None:
    course = "Creationeering" if lesson_id.startswith("C-") else "Mousetrap Build"
    prompt = MODEL_PROMPT.format(
        title=title, course=course, excerpt=excerpt, navy=NAVY, gold=GOLD
    )
    return _call_claude(prompt, api_key)


# ── Embed block helpers ───────────────────────────────────────────────────────

def make_embed_block(url: str, label: str = "Interactive Simulation") -> dict:
    import random, string
    bid = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return {
        "id": bid,
        "type": "embed",
        "data": {"src": url, "height": 520, "label": label},
        "meta": {"spacing": "md", "qcStatus": "approved"},
    }


def already_has_simulation_embed(blocks: list) -> bool:
    """Check if any embed block points to a simulation.html."""
    return any(
        b.get("type") == "embed" and "simulation" in b.get("data", {}).get("src", "")
        for b in blocks
    )


# ── Main processing ───────────────────────────────────────────────────────────

INTERACTIVE_TYPES = [
    ("simulation.html", "Interactive Simulation", generate_simulation),
    ("physics.html",    "Physics Sandbox",        generate_physics),
    ("model.html",      "3D System Viewer",       generate_model),
]


def process_lesson(lesson_id: str, env: dict, platform_key: str, dry_run: bool, missing_only: bool,
                   types: list[str] | None = None) -> dict:
    local_dir = INTERACTIVES_DIR / lesson_id

    # Fetch lesson
    lesson = fetch_lesson(lesson_id, platform_key)
    if not lesson:
        return {"id": lesson_id, "status": "fetch_error"}

    title   = lesson.get("title", lesson_id)
    blocks  = lesson.get("blocks", [])
    excerpt = build_excerpt(lesson)
    if not excerpt.strip():
        return {"id": lesson_id, "status": "no_content"}

    print(f"\n  [{lesson_id}] {title} ({len(blocks)} blocks, {len(excerpt)} chars)")

    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")

    targets = [(f, lbl, fn) for f, lbl, fn in INTERACTIVE_TYPES if types is None or f in types]
    generated = 0
    skipped = 0

    for filename, label, gen_fn in targets:
        local_file = local_dir / filename
        if missing_only and local_file.exists():
            skipped += 1
            continue
        if already_has_simulation_embed(blocks) and filename == "simulation.html":
            skipped += 1
            continue

        if dry_run:
            print(f"    DRY RUN: would generate {filename}")
            continue

        if not api_key:
            return {"id": lesson_id, "status": "no_api_key"}

        print(f"    Generating {filename}...")
        html = gen_fn(title, lesson_id, excerpt, api_key)
        if not html:
            print(f"    {filename}: generation failed")
            continue

        print(f"    {filename}: {len(html)} chars — uploading...")
        local_dir.mkdir(parents=True, exist_ok=True)
        local_file.write_text(html, encoding="utf-8")

        url = upload_interactive(lesson_id, filename, html, platform_key)
        if not url:
            print(f"    {filename}: upload failed (saved locally)")
            continue

        print(f"    {filename}: uploaded → {url}")
        new_block = make_embed_block(url, label)
        blocks = list(blocks) + [new_block]
        generated += 1
        time.sleep(1)

    if dry_run:
        return {"id": lesson_id, "status": "dry_run", "would_generate": len(targets) - skipped}

    if generated == 0:
        return {"id": lesson_id, "status": "skipped" if skipped else "all_failed", "skipped": skipped}

    ok = patch_lesson_blocks(lesson_id, blocks, platform_key)
    status = "done" if ok else "patch_failed"
    print(f"  [{lesson_id}] {'OK' if ok else 'PATCH FAILED'}: {generated} generated")
    return {"id": lesson_id, "status": status, "generated": generated}


def main():
    parser = argparse.ArgumentParser(description="Generate simulation.html interactives for GK12 lessons")
    parser.add_argument("--dry-run",      action="store_true")
    parser.add_argument("--save",         action="store_true")
    parser.add_argument("--lesson",       help="Single lesson ID, e.g. C-007")
    parser.add_argument("--course",       choices=["C", "M"], help="Creationeering (C) or Mousetrap (M)")
    parser.add_argument("--missing-only", action="store_true", default=True,
                        help="Skip lessons that already have the file locally (default: True)")
    parser.add_argument("--regenerate",   action="store_true",
                        help="Regenerate even if file already exists")
    parser.add_argument("--types",        nargs="+",
                        choices=["simulation.html", "physics.html", "model.html"],
                        help="Which types to generate (default: all three)")
    parser.add_argument("--targets-file", help="JSON file with {simulation:[...], physics:[...], model:[...]} target lists")
    args = parser.parse_args()

    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    missing_only = not args.regenerate

    env = load_env()
    platform_key = _get_platform_key()
    if not platform_key:
        print("PIPELINE_KEY not found in .env"); sys.exit(1)

    # Build lesson list
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    all_lessons = [l["id"] for l in manifest["lessons"]]

    # Load per-type target lists from file if provided
    targets_by_type: dict | None = None
    if getattr(args, "targets_file", None):
        targets_by_type = json.loads(Path(args.targets_file).read_text(encoding="utf-8"))
        # Flatten to all unique IDs for the main lesson loop
        all_target_ids = set()
        for v in targets_by_type.values():
            if isinstance(v, list):
                all_target_ids.update(v)
        lesson_ids = [lid for lid in all_lessons if lid in all_target_ids]
        print(f"  Targets file: {len(lesson_ids)} lessons across types")
    elif args.lesson:
        lesson_ids = [args.lesson.upper()]
    elif args.course:
        lesson_ids = [lid for lid in all_lessons if lid.startswith(args.course + "-")]
    else:
        lesson_ids = all_lessons

    mode = "DRY RUN" if args.dry_run else "SAVE"
    print(f"\nQC Generate Simulations [{mode}] — {len(lesson_ids)} lesson(s)")
    print(f"Missing-only: {missing_only} | Model: {CLAUDE_MODEL}")
    print("=" * 60)

    log = {}
    if LOG_PATH.exists():
        try:
            log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    results = []
    counts: dict[str, int] = {}
    types_filter = args.types or None

    for i, lid in enumerate(lesson_ids, 1):
        print(f"[{i}/{len(lesson_ids)}]", end="")
        # If a targets file was provided, filter which types apply to this lesson
        if targets_by_type:
            lesson_types = []
            if lid in targets_by_type.get("simulation", []):
                lesson_types.append("simulation.html")
            if lid in targets_by_type.get("physics", []):
                lesson_types.append("physics.html")
            if lid in targets_by_type.get("model", []):
                lesson_types.append("model.html")
            effective_types = lesson_types or None
        else:
            effective_types = types_filter

        r = process_lesson(lid, env, platform_key, dry_run=args.dry_run,
                           missing_only=missing_only, types=effective_types)
        results.append(r)
        s = r["status"]
        counts[s] = counts.get(s, 0) + 1
        if r["status"] == "done":
            log[lid] = r
        time.sleep(0.3)  # avoid hammering APIs

    if args.save and log:
        LOG_PATH.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'='*60}")
    print("SUMMARY:", counts)
    errors = [r for r in results if r["status"] in ("generation_failed", "fetch_error", "upload_failed", "patch_failed")]
    if errors:
        print("Errors:", [r["id"] for r in errors])


if __name__ == "__main__":
    main()
