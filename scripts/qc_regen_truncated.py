"""
Regenerate truncated interactives in place, from the Interactive Doctor report.

Reads interactive_doctor_report.json's `regenerate` list and re-generates each
simulation/model/physics file with the FIXED generator (16k token cap + truncation
guard in qc_generate_simulations._call_claude), then OVERWRITES the same Storage
path. Does NOT touch lesson blocks (the embed already points at the file), so no
duplicate embeds. concept.html is skipped here (different generator).

Usage:
  python scripts/qc_regen_truncated.py --dry-run
  python scripts/qc_regen_truncated.py --save --limit 1     # validate one first
  python scripts/qc_regen_truncated.py --save               # all
"""

import argparse, json, os, sys, time
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from qc_generate_simulations import (
    load_env, _get_platform_key, fetch_lesson, build_excerpt,
    upload_interactive, generate_simulation, generate_physics, generate_model,
    INTERACTIVES_DIR,
)

REPORT_PATH = BASE / "interactive_doctor_report.json"

GEN_FN = {
    "simulation.html": generate_simulation,
    "physics.html":    generate_physics,
    "model.html":      generate_model,
    # concept.html is normally made by interactive_agent (Google-Doc pipeline); for a
    # one-off truncation repair, regenerate an equivalent self-contained activity from
    # the live lesson content using the fixed (32k) simulation generator.
    "concept.html":    generate_simulation,
}


def ends_complete(html: str) -> bool:
    return html.rstrip().lower().endswith("</html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--save",    action="store_true")
    ap.add_argument("--limit",   type=int, help="only process the first N files")
    args = ap.parse_args()
    if not args.dry_run and not args.save:
        print("Pass --dry-run or --save"); sys.exit(1)

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    regen = report.get("regenerate", [])

    # Group by lesson; keep only the 3 sim types this generator can make.
    by_lesson: dict[str, list[str]] = defaultdict(list)
    skipped_other = []
    for entry in regen:
        lid, fname = entry.split("/", 1)
        if fname in GEN_FN:
            by_lesson[lid].append(fname)
        else:
            skipped_other.append(entry)

    # Flatten to an ordered (lesson, filename) worklist
    work = [(lid, f) for lid in sorted(by_lesson) for f in by_lesson[lid]]
    if args.limit:
        work = work[: args.limit]

    print(f"Regenerate worklist: {len(work)} files across {len(by_lesson)} lessons")
    if skipped_other:
        print(f"Skipped (different generator, handle separately): {skipped_other}")
    if args.dry_run:
        for lid, f in work:
            print(f"  would regenerate {lid}/{f}")
        return

    env = load_env()
    platform_key = _get_platform_key()
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not platform_key:
        print("Missing ANTHROPIC_API_KEY or PIPELINE_KEY"); sys.exit(1)

    results = {"ok": [], "fail": [], "truncated": []}
    lesson_cache: dict[str, dict] = {}

    for i, (lid, fname) in enumerate(work, 1):
        print(f"\n[{i}/{len(work)}] {lid}/{fname}")
        lesson = lesson_cache.get(lid) or fetch_lesson(lid, platform_key)
        if not lesson:
            print("  fetch_error"); results["fail"].append(f"{lid}/{fname}"); continue
        lesson_cache[lid] = lesson

        title = lesson.get("title", lid)
        excerpt = build_excerpt(lesson)
        html = GEN_FN[fname](title, lid, excerpt, api_key)
        if not html:
            print("  generation returned None (truncated/invalid — not uploaded)")
            results["truncated"].append(f"{lid}/{fname}"); continue
        if not ends_complete(html):
            print("  output incomplete — skipping upload")
            results["truncated"].append(f"{lid}/{fname}"); continue

        # Save locally + overwrite the same Storage path (no block changes)
        (INTERACTIVES_DIR / lid).mkdir(parents=True, exist_ok=True)
        (INTERACTIVES_DIR / lid / fname).write_text(html, encoding="utf-8")
        url = upload_interactive(lid, fname, html, platform_key)
        if not url:
            print("  upload_failed (saved locally)")
            results["fail"].append(f"{lid}/{fname}"); continue
        print(f"  OK {len(html)} chars -> {url}")
        results["ok"].append(f"{lid}/{fname}")
        time.sleep(1)

    print("\n" + "=" * 60)
    print(f"SUMMARY: ok={len(results['ok'])} truncated={len(results['truncated'])} fail={len(results['fail'])}")
    if results["truncated"]:
        print("Still truncated (retry / raise cap):", results["truncated"])
    if results["fail"]:
        print("Failed:", results["fail"])
    (BASE / "qc_regen_truncated_log.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
