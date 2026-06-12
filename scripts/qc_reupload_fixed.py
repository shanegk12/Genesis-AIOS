"""
Re-upload locally-regenerated interactives whose Storage upload failed (e.g. a
network blip). Reads qc_regen_truncated_log.json's "fail" list; each of those was
regenerated and written locally complete, only the upload failed. Verifies the
local file ends with </html> before pushing.

Usage: python scripts/qc_reupload_fixed.py
"""
import json, sys, time
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from qc_generate_simulations import _get_platform_key, upload_interactive, INTERACTIVES_DIR

log = json.loads((BASE / "qc_regen_truncated_log.json").read_text(encoding="utf-8"))
targets = log.get("fail", [])
key = _get_platform_key()

print(f"Re-uploading {len(targets)} files")
ok, fail = [], []
for entry in targets:
    lid, fname = entry.split("/", 1)
    p = INTERACTIVES_DIR / lid / fname
    if not p.exists():
        fail.append(f"{entry} (no local file)"); print("MISS", entry); continue
    html = p.read_text(encoding="utf-8")
    if not html.rstrip().lower().endswith("</html>"):
        fail.append(f"{entry} (local incomplete)"); print("INCOMPLETE", entry); continue
    url = upload_interactive(lid, fname, html, key)
    if url:
        ok.append(entry); print("OK  ", entry)
    else:
        fail.append(entry); print("FAIL", entry)
    time.sleep(0.4)

print(f"\nRe-upload done: ok={len(ok)} fail={len(fail)}")
if fail:
    print("Still failed:", fail)
(BASE / "qc_reupload_fixed_log.json").write_text(json.dumps({"ok": ok, "fail": fail}, indent=2), encoding="utf-8")
