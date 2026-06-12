"""
Interactive Doctor — static health scan of GK12 HTML5 interactives.

Scans scripts/interactives/{lessonId}/*.html and reports, per file:
  - truncated / malformed (missing </body></html>, unbalanced <script> tags)
  - JS syntax errors (optional, --js-check, via `node --check`)
  - CSP-incompatible patterns (the serve route runs default-src 'none';
    script-src 'unsafe-inline' — so eval, external fetch/src, workers all break)
  - reporting status: has gk12.report()? has form inputs (workbook candidate)?

Writes scripts/interactive_doctor_report.json and prints a summary + worklists.

Usage:
  python scripts/interactive_doctor.py                 # all, no JS syntax check
  python scripts/interactive_doctor.py --js-check      # also run node --check
  python scripts/interactive_doctor.py --course M      # only M-* lessons
  python scripts/interactive_doctor.py --dir some/path # custom interactives dir
"""

import argparse, json, re, sys, subprocess, tempfile, os
from pathlib import Path
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_DIR = Path(__file__).parent / "interactives"
REPORT_PATH = Path(__file__).parent / "interactive_doctor_report.json"

# CSP-incompatible patterns under: default-src 'none'; script-src 'unsafe-inline'
CSP_PATTERNS = {
    "eval":            re.compile(r"\beval\s*\("),
    "new_function":    re.compile(r"\bnew\s+Function\s*\("),
    "web_worker":      re.compile(r"\bnew\s+Worker\s*\("),
    "import_scripts":  re.compile(r"\bimportScripts\s*\("),
    "object_url":      re.compile(r"URL\.createObjectURL"),
    "fetch":           re.compile(r"\bfetch\s*\("),
    "xhr":             re.compile(r"\bXMLHttpRequest\b"),
    "websocket":       re.compile(r"\bWebSocket\b"),
    "dynamic_import":  re.compile(r"[^.\w]import\s*\("),
    "ext_src":         re.compile(r"""<(?:script|link|img|iframe|audio|video|source)\b[^>]*\b(?:src|href)\s*=\s*['"]https?://""", re.I),
    "css_import_ext":  re.compile(r"@import\s+(?:url\()?['\"]?https?://", re.I),
}

INPUT_RE   = re.compile(r"<(?:input|textarea|select)\b|contenteditable", re.I)
SCRIPT_RE  = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.I | re.S)
SCRIPT_OPEN_RE  = re.compile(r"<script\b", re.I)
SCRIPT_CLOSE_RE = re.compile(r"</script\s*>", re.I)
SRC_ATTR_RE = re.compile(r"""\bsrc\s*=\s*['"]([^'"]+)['"]""", re.I)


def has_node() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def inline_scripts(html: str):
    """Return list of inline (non-src) script bodies."""
    out = []
    for attrs, body in SCRIPT_RE.findall(html):
        if SRC_ATTR_RE.search(attrs):
            continue
        if body.strip():
            out.append(body)
    return out


def js_syntax_errors(scripts, tmpdir) -> list:
    """Run `node --check` on each inline script; return list of error summaries."""
    errs = []
    for i, body in enumerate(scripts):
        p = Path(tmpdir) / f"s{i}.mjs"
        p.write_text(body, encoding="utf-8")
        try:
            r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                msg = (r.stderr or "").strip().splitlines()
                errs.append(msg[-1] if msg else "syntax error")
        except Exception as e:
            errs.append(f"check failed: {e}")
    return errs


def diagnose(path: Path, do_js: bool, tmpdir: str) -> dict:
    raw = path.read_bytes()
    html = raw.decode("utf-8", errors="replace")
    tail = html.rstrip()[-400:].lower()

    opens = len(SCRIPT_OPEN_RE.findall(html))
    closes = len(SCRIPT_CLOSE_RE.findall(html))

    issues = []
    # ── structural / truncation ──
    has_html_close = "</html>" in html.lower()
    has_body_close = "</body>" in html.lower()
    if opens != closes:
        issues.append(f"unbalanced <script> tags ({opens} open / {closes} close)")
    if not has_html_close:
        issues.append("missing </html> (likely truncated)")
    elif not has_body_close:
        issues.append("missing </body>")
    # ends mid-tag or mid-word with no terminator
    if not tail.endswith((">", "</html>")) and "</html>" not in tail:
        issues.append("file ends mid-content (truncated)")

    truncated = any("trunc" in i or "unbalanced" in i or "missing </html>" in i for i in issues)

    # Distinguish a cheap trailing-tag patch from a mid-logic truncation that
    # needs regeneration. Patchable = all scripts closed AND body content looks
    # complete (ends at </body> or a closed </script>), only final tags missing.
    scripts_balanced = opens == closes
    body_complete = ("</body" in tail) or html.rstrip().lower().endswith("</script>")
    if truncated:
        fix_class = "patch-tags" if (scripts_balanced and body_complete) else "regenerate"
    else:
        fix_class = "none"

    scripts = inline_scripts(html)

    # ── CSP risks ──
    csp_hits = sorted({name for name, rx in CSP_PATTERNS.items() if rx.search(html)})

    # ── reporting status ──
    has_report = "gk12.report" in html
    has_restore = "gk12OnRestore" in html
    has_inputs = bool(INPUT_RE.search(html))

    # ── JS syntax ──
    js_errs = []
    if do_js and scripts:
        js_errs = js_syntax_errors(scripts, tmpdir)

    # classify
    if truncated or js_errs:
        health = "broken"
    elif csp_hits:
        health = "csp-risk"
    else:
        health = "healthy"

    return {
        "lessonId": path.parent.name,
        "file": path.name,
        "bytes": len(raw),
        "health": health,
        "issues": issues,
        "fixClass": fix_class,
        "jsErrors": js_errs,
        "cspRisks": csp_hits,
        "hasInputs": has_inputs,
        "hasReport": has_report,
        "hasRestore": has_restore,
        # needs conversion = student-input interactive that doesn't yet report
        "needsReportingConversion": has_inputs and not has_report,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--js-check", action="store_true", help="run node --check on inline scripts")
    ap.add_argument("--course", choices=["C", "M"], help="limit to a course prefix")
    ap.add_argument("--dir", help="interactives dir (default scripts/interactives)")
    args = ap.parse_args()

    root = Path(args.dir) if args.dir else DEFAULT_DIR
    if not root.exists():
        print(f"No interactives dir at {root}")
        sys.exit(1)

    do_js = args.js_check and has_node()
    if args.js_check and not do_js:
        print("[warn] node not found — skipping JS syntax check")

    lesson_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.course:
        lesson_dirs = [d for d in lesson_dirs if d.name.startswith(args.course + "-")]

    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for d in lesson_dirs:
            for f in sorted(d.glob("*.html")):
                results.append(diagnose(f, do_js, tmp))

    # ── summary ──
    n = len(results)
    health = Counter(r["health"] for r in results)
    broken = [r for r in results if r["health"] == "broken"]
    csp = [r for r in results if r["health"] == "csp-risk"]
    needs_conv = [r for r in results if r["needsReportingConversion"]]
    already_report = [r for r in results if r["hasReport"]]
    csp_counter = Counter(c for r in results for c in r["cspRisks"])

    print(f"\nInteractive Doctor — {n} files in {len(lesson_dirs)} lessons (JS check: {'on' if do_js else 'off'})")
    print("=" * 64)
    print(f"  healthy:   {health['healthy']}")
    print(f"  csp-risk:  {health['csp-risk']}")
    print(f"  broken:    {health['broken']}")
    print(f"\n  reporting-ready (has gk12.report): {len(already_report)}")
    print(f"  need reporting conversion (inputs, no report): {len(needs_conv)}")

    if csp_counter:
        print("\n  CSP-incompatible patterns (file counts):")
        for name, c in csp_counter.most_common():
            print(f"    {name:16} {c}")

    patch_tags = [r for r in broken if r["fixClass"] == "patch-tags"]
    regen = [r for r in broken if r["fixClass"] == "regenerate"]
    if broken:
        print(f"\n  BROKEN breakdown: {len(patch_tags)} patch-tags (cheap) · {len(regen)} regenerate (mid-logic)")
        print(f"  patch-tags: {', '.join(f'{r['lessonId']}/{r['file']}' for r in patch_tags) or '(none)'}")
        print(f"\n  regenerate ({len(regen)}):")
        for r in regen[:40]:
            print(f"    {r['lessonId']}/{r['file']}")
        if len(regen) > 40:
            print(f"    …and {len(regen) - 40} more (see report JSON)")

    payload = {
        "summary": {
            "files": n,
            "lessons": len(lesson_dirs),
            "jsCheck": do_js,
            "health": dict(health),
            "reportingReady": len(already_report),
            "needsReportingConversion": len(needs_conv),
            "cspPatternCounts": dict(csp_counter),
        },
        "brokenFiles": [f"{r['lessonId']}/{r['file']}" for r in broken],
        "patchTags": [f"{r['lessonId']}/{r['file']}" for r in patch_tags],
        "regenerate": [f"{r['lessonId']}/{r['file']}" for r in regen],
        "needsConversion": sorted({r["lessonId"] for r in needs_conv}),
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nFull report → {REPORT_PATH}")


if __name__ == "__main__":
    main()
