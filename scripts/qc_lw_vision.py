"""
Genesis K-12 QC — LearnWorlds Screenshot Vision Check

Reads screenshots from D:\\AIOS\\screenshots\\{course}\\{lesson_folder}\\
Maps folder names to lesson IDs via fuzzy title matching, then sends
a sample of screenshots to Claude Vision for formatting analysis.

Output: actionable recommendations per lesson saved to qc_lw_vision_report.json

Usage:
  python scripts/qc_lw_vision.py --list              # show folder→ID mapping
  python scripts/qc_lw_vision.py --all               # analyze all folders
  python scripts/qc_lw_vision.py --course C          # Creationeering only
  python scripts/qc_lw_vision.py --course M          # Mousetrap only
  python scripts/qc_lw_vision.py --folder "Entrepreneurship"  # single folder
  python scripts/qc_lw_vision.py --all --save        # save report to JSON

Requires in .env:
  ANTHROPIC_API_KEY
"""

import argparse, base64, json, os, re, sys, time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCREENSHOTS_ROOT = Path(__file__).parent.parent / "screenshots"
REPORT_PATH      = Path(__file__).parent / "qc_lw_vision_report.json"
MAX_IMAGES       = 8   # max screenshots to send per lesson

# ── Title → ID map (fetched 2026-05-20) ────────────────────────────────────────
LESSON_TITLES = {
    "C-001": "What is Creationeering",
    "C-002": "Entrepreneurship",
    "C-003": "Genesis and Creationeering",
    "C-004": "Using Math and Science as Tools",
    "C-005": "Units, Conversions, and Measurement",
    "C-006": "Intro to Systems Thinking",
    "C-007": "Objectives, Constraints, and Variables",
    "C-008": "Ethics in Engineering",
    "C-009": "Understanding Process Mapping and Flowcharts",
    "C-010": "Visualization and Sketching",
    "C-011": "Design: Forces and Influences",
    "C-012": "Design: Historical Case Studies",
    "C-013": "Form, Function, and Aesthetic",
    "C-014": "Design Iteration and Communication",
    "C-015": "Alternatives and Patents",
    "C-016": "Novelty and Innovation in Engineering",
    "C-017": "Concept Generation",
    "C-018": "Fundamentals of Motion and Work",
    "C-019": "Energy Conservation, Transfer and Loss",
    "C-020": "The Importance of Data in Engineering",
    "C-021": "Design of Experiments (One Factor at A Time)",
    "C-022": "Measurement Quality and Instrument Validation",
    "C-023": "Modeling Reality: Physical vs. Computational",
    "C-024": "Statistical Analysis",
    "C-025": "What is Synthesis?",
    "C-026": "Managing Resistive Sources",
    "C-027": "Stress and Strain",
    "C-028": "Protecting Your Business",
    "C-029": "Troubleshooting and Debugging Systems",
    "C-030": "What is Procurement?",
    "C-031": "Material Properties and Selection",
    "C-032": "Procurement: Cost Analysis and Budgeting",
    "C-033": "Standardization vs. Custom Fabrication",
    "C-034": "Quality Assurance and Material Inspection",
    "C-035": "Technical Specifications",
    "C-036": "Fabrication",
    "C-037": "Hazards and Operations",
    "C-038": "Resource Management and Loss Prevention",
    "C-039": "Precision Measurement and Tolerances",
    "C-040": "What is Logistics?",
    "C-041": "Timeline Development and Milestones",
    "C-042": "Critical Path Method (CPM)",
    "C-043": "Risk Assessment",
    "C-044": "Planning and Buffer Time",
    "C-045": "Global Supply Management",
    "C-046": "Inventory and Warehouse Management",
    "C-047": "Shipping, Transport, and Compliance",
    "C-048": "Reverse Logistics and End-of-Life Flow",
    "C-049": "Just-In-Time vs. Just-In-Case",
    "C-050": "What is Assembly?",
    "C-051": "Fabrication Methods and Integrity",
    "C-052": "Quality Control During Assembly",
    "C-053": "Reading and Interpreting Blueprints",
    "C-054": "Sequencing and Assembly Lines",
    "C-055": "Systems Integration and Interoperability",
    "C-056": "Verification, Validation, and Testing",
    "C-057": "Configuration Management and Baselines",
    "C-058": "Human Factors in Production Systems",
    "C-059": "Feedback Loops and Process Involvement",
    "C-060": "What is Performance?",
    "C-061": "Experimental Design and Testing Protocols",
    "C-062": "Continuous Improvement",
    "C-063": "Data-Defined Performance",
    "C-064": "Optimization Techniques and Trade-Offs",
    "C-065": "Functional Requirements and Specifications",
    "C-066": "Performance Validation",
    "C-067": "Failure Analysis and Reliability Engineering",
    "C-068": "Product Certification and Regulatory Compliance",
    "C-069": "Customer Acceptance and Final Delivery",
    "C-070": "Cradle-to-Cradle Design Philosophy",
    "C-071": "The 3 R's: Reduce, Reuse, Recycle",
    "C-072": "Environmental Footprint and Carbon Accounting",
    "C-073": "Material Toxicity and Hazard Minimization",
    "C-074": "Waste Stream Management and Circular Economy",
    "C-075": "Design for Disassembly and Recycling",
    "C-076": "System Upgrades and Backward Compatibility",
    "C-077": "Innovation for Resource-Limited Environments",
    "C-078": "Durability",
    "C-079": "Total Cost of Ownership",
    "C-080": "The Ethics of End-of-Life (EOL) Responsibility",
    "C-081": "Material Recovery and Salvage Value",
    "C-082": "Hazardous Waste and Safe Disposal Protocol",
    "C-083": "Life Extension and Maintenance Philosophy",
    "C-084": "Legislation and Global E-Waste Policy",
    "C-085": "Decommissioning Procedures and System Shutdown",
    "C-086": "Data Security and System Wipe",
    "C-087": "Recycling Logistics and Infrastructure",
    "C-088": "The Engineer's Role in Product Afterlife",
    "C-089": "Formal System Closure and Documentation",
    "M-001": "Syllabus and Instructional Guide",
    "M-002": "Course Introduction",
    "M-003": "Build Kit Overview",
    "M-004": "Objectives, Constraints, and Variables",
    "M-005": "Prototypes",
    "M-006": "Build 1: Little Moe Prototype Car",
    "M-007": "Digital Measurement",
    "M-008": "The Arduino",
    "M-009": "Business Plan",
    "M-010": "Business Activity: Company Identity",
    "M-011": "Fundamentals of Design",
    "M-012": "Communicating Designs and Testing",
    "M-013": "Build 2: Iterative Design - Mark 1",
    "M-014": "Power Transmission Mechanisms",
    "M-015": "Energy Flow, Loss, and Efficiency",
    "M-016": "Build 2: Iterative Design - Mark 2",
    "M-017": "Analysis Activity: Calculations and Efficiency",
    "M-018": "The Dynamics of Stored Energy",
    "M-019": "Modeling Resistive Forces",
    "M-020": "Build 3: CAD Analysis of Design Parameters",
    "M-021": "Instrumentation and Data Types",
    "M-022": "The Engineering Report Structure",
    "M-023": "Build 4: Arduino - Distance Sensor Calibration",
    "M-024": "Analysis Gate Review",
    "M-025": "Engineering Notebook: Entry 5",
    "M-026": "Lesson: Bill of Materials",
    "M-027": "Lesson: Material Preparation",
    "M-028": "Build: Inventory Checks and Verifications",
    "M-029": "Lesson: Precision Finishing and Tolerance",
    "M-030": "Lesson: Sourcing Alternatives and Costing",
    "M-031": "Build: Material Processing",
    "M-032": "Procurement Activity: Bill of Materials",
    "M-033": "Lesson: Project Phases and Dependencies",
    "M-034": "Lesson: Critical Paths and Calculating Time",
    "M-036": "BA: Patents, IP + Engineer Liability",
    "M-037": "Lesson: External Supply Chains",
    "M-038": "Lesson: Risks and Contingencies",
    "M-039": "Logistics: Supply Chain Map and Risk Analysis",
    "M-040": "BA: Customer Persona + Marketing Standards",
    "M-041": "Lesson: Assembly Blueprint and Safety Review",
    "M-042": "Lesson: Frame, Axle, and Wheel Integration",
    "M-043": "Build: Body and Mousetrap",
    "M-044": "Build: Power System and Axles",
    "M-045": "Lesson: Component Alignment and Quality",
    "M-046": "Lesson: Post-Build Systems",
    "M-047": "Build: Braking System and Test",
    "M-048": "Build: Arduino Station and Test",
    "M-049": "Lesson: Test Protocol and Baselines",
    "M-050": "Lesson: Variables and Optimization Cycle",
    "M-051": "Performance Activity: Baselines and Predictions",
    "M-052": "Build: Variable Confirmation Tests",
    "M-053": "Lesson: Final Function Verification",
    "M-054": "Lesson: Performance Data",
    "M-055": "Build: Optimization Tests",
    "M-056": "Performance Activity: Final Runs and Data",
    "M-057": "Lesson: Product End-of-Life Analysis",
    "M-058": "Lesson: Sustainable Materials",
    "M-059": "BA: Product Sheet + 2-Minute Pitch Practice",
    "M-061": "Lesson: Total Cost and Lifecycle Improvement Plan",
    "M-062": "Sustainability Activity: Future Designs",
    "M-063": "BA: Org Chart + Production Gantt Chart",
    "M-064": "Lesson: Classifying End of Life",
    "M-065": "Lesson: Principles of E-Waste and Safe Disposal",
    "M-067": "Lesson: Salvage Value and Resource Recovery",
    "M-068": "Lesson: Closing a Project",
    "M-070": "Final Activity: Parent Pitch Night",
}

# Reverse: normalized title → ID
def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9 ]', ' ', s.lower()).split()

def _title_tokens(s: str) -> set:
    return set(_norm(s))

# Build ID lookup by normalized title
# Manual overrides for cases fuzzy matching can't resolve (acronyms, renamed lessons, duplicates)
MANUAL_OVERRIDES: dict[str, str] = {
    "OCV": "M-004",                               # Objectives, Constraints, Variables (Mousetrap)
    "Mousetrap Course Intro": "M-002",             # "Course Introduction" in platform
    "Understanding Design": "C-010",               # Visualization and Sketching (renamed)
    "Objectives Constraints and Variables": "C-007",  # same title exists in M-004; screenshots are in Creationeering folder
    "Prototyping and Iterative Design": "M-005",   # Prototypes (Mousetrap)
}

# Build ID → normalized title map (store all IDs per key for course-aware lookup)
_ID_BY_NORM: dict[str, list[str]] = {}
for _id, _title in LESSON_TITLES.items():
    _key = " ".join(_norm(_title))
    _ID_BY_NORM.setdefault(_key, []).append(_id)


def fuzzy_match_id(folder_name: str) -> tuple[str | None, float]:
    """Return (lesson_id, score) where score is 0-1 jaccard similarity."""
    query_tokens = _title_tokens(folder_name)
    best_id, best_score = None, 0.0
    for norm_title, ids in _ID_BY_NORM.items():
        title_tokens = set(norm_title.split())
        if not query_tokens or not title_tokens:
            continue
        intersection = len(query_tokens & title_tokens)
        union = len(query_tokens | title_tokens)
        score = intersection / union if union else 0
        if score > best_score:
            best_score = score
            best_id = ids[0]  # pick first; course-aware re-match happens in main
    return best_id, best_score


def load_env() -> dict:
    env_path = Path(__file__).parent.parent / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def sample_images(folder: Path, max_n: int = MAX_IMAGES) -> list[Path]:
    """Return up to max_n PNG/JPG files, evenly spread across the full set."""
    files = sorted(folder.glob("*.png")) + sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.jpeg"))
    if not files:
        return []
    if len(files) <= max_n:
        return files
    # Evenly sample: always include first and last
    step = (len(files) - 1) / (max_n - 1)
    indices = sorted(set(round(i * step) for i in range(max_n)))
    return [files[i] for i in indices]


def analyze_folder(client, folder: Path, lesson_id: str, lesson_title: str) -> dict:
    images = sample_images(folder)
    if not images:
        return {"error": "no images found"}

    content = []
    for img_path in images:
        raw = img_path.read_bytes()
        b64 = base64.standard_b64encode(raw).decode("utf-8")
        mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        })

    content.append({
        "type": "text",
        "text": f"""You are reviewing LearnWorlds screenshots of a Genesis K-12 middle school engineering lesson to identify formatting improvements for our custom LMS platform.

Lesson: "{lesson_title}" (ID: {lesson_id})
Screenshots shown: {len(images)} of {len(list(folder.glob('*.png')) + list(folder.glob('*.jpg')))} total (evenly sampled)

IMPORTANT CONTEXT:
- Our platform uses these block types: text, heading (h2/h3), callout (info/tip/warning/biblical), vocab (term-definition grid), tabs, accordion, accordion-grid, image, divider, carousel, columns, embed
- Some lessons in LearnWorlds are improperly formatted — focus on the CONTENT and what block types would best present it, not on replicating LW formatting exactly
- The audience is 6th-8th grade homeschool students
- WATCH FOR REDUNDANT STEP IMAGES: If you see a full process/overview infographic (e.g. "The Creative Process", "Engineering Design Steps", "7 Phases of X") AND the lesson also shows individual photos of each step separately, flag those individual step photos as likely redundant — they are duplicated content that will be imported as extra blocks. Note this in formatting_issues.
- IMAGE QUALITY: Note any images that have excessive whitespace or padding around the subject, awkward crops, or subject matter that doesn't match the section heading.

Analyze these screenshots and return JSON only — no other text:
{{
  "sections_found": ["list of major section names visible"],
  "formatting_issues": ["issues with how content is currently organized"],
  "block_recommendations": [
    {{"section": "section name", "current": "what it looks like now", "recommended_block": "block type", "reason": "why"}}
  ],
  "content_notes": "any content gaps, errors, or quality notes (max 100 words)",
  "priority": "high/medium/low"
}}

"priority" = high if there are clear structural problems that hurt readability, medium if there are improvements worth making, low if the lesson looks well-structured already.""",
    })

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        messages=[{"role": "user", "content": content}],
    )
    raw = resp.content[0].text.strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"raw": raw, "error": "json_parse_failed"}


def get_all_folders() -> list[tuple[Path, str]]:
    """Return (folder_path, course_prefix) for every lesson subfolder."""
    pairs = []
    for course_dir in sorted(SCREENSHOTS_ROOT.iterdir()):
        if not course_dir.is_dir():
            continue
        prefix = "C" if "creationeering" in course_dir.name.lower() else "M"
        for lesson_dir in sorted(course_dir.iterdir()):
            if lesson_dir.is_dir():
                pairs.append((lesson_dir, prefix))
    return pairs


def main():
    parser = argparse.ArgumentParser(description="QC LearnWorlds Vision Check")
    parser.add_argument("--list",   action="store_true", help="Show folder→ID mapping and exit")
    parser.add_argument("--all",    action="store_true", help="Analyze all screenshot folders")
    parser.add_argument("--course", choices=["C", "M"], help="Analyze one course only")
    parser.add_argument("--folder", help="Analyze a single folder by name (partial match OK)")
    parser.add_argument("--save",   action="store_true", help="Save results to qc_lw_vision_report.json")
    parser.add_argument("--min-score", type=float, default=0.3,
                        help="Minimum fuzzy match score to accept (default 0.3)")
    args = parser.parse_args()

    if not SCREENSHOTS_ROOT.exists():
        print(f"Screenshots folder not found: {SCREENSHOTS_ROOT}")
        sys.exit(1)

    all_folders = get_all_folders()

    # Filter
    if args.folder:
        query = args.folder.lower()
        all_folders = [(f, p) for f, p in all_folders if query in f.name.lower()]
        if not all_folders:
            print(f"No folder matching '{args.folder}'")
            sys.exit(1)
    elif args.course:
        all_folders = [(f, p) for f, p in all_folders if p == args.course]
    elif not args.all and not args.list:
        parser.error("Provide --all, --course, --folder, or --list")

    # Build mapping table
    mapping = []
    for folder, prefix in all_folders:
        # Manual overrides take priority
        if folder.name in MANUAL_OVERRIDES:
            lid   = MANUAL_OVERRIDES[folder.name]
            score = 1.0
        else:
            lid, score = fuzzy_match_id(folder.name)
            # If match is wrong course, re-run filtering to expected course prefix
            if lid and not lid.startswith(prefix):
                query_tokens = _title_tokens(folder.name)
                best_id, best_score = None, 0.0
                for norm_title, ids in _ID_BY_NORM.items():
                    course_ids = [i for i in ids if i.startswith(prefix)]
                    if not course_ids:
                        continue
                    title_tokens = set(norm_title.split())
                    if not query_tokens or not title_tokens:
                        continue
                    intersection = len(query_tokens & title_tokens)
                    union = len(query_tokens | title_tokens)
                    s = intersection / union if union else 0
                    if s > best_score:
                        best_score = s
                        best_id = course_ids[0]
                if best_id and best_score >= args.min_score:
                    lid, score = best_id, best_score

        img_count = len(list(folder.glob("*.png"))) + len(list(folder.glob("*.jpg")))
        mapping.append({
            "folder": folder.name,
            "folder_path": folder,
            "lesson_id": lid if score >= args.min_score else None,
            "lesson_title": LESSON_TITLES.get(lid, "") if lid else "",
            "score": round(score, 2),
            "images": img_count,
        })

    if args.list:
        print(f"\n{'Folder':<45} {'ID':<8} {'Score':>6} {'#Imgs':>6}  {'Platform Title'}")
        print("-" * 100)
        for m in mapping:
            lid = m["lesson_id"] or "NO MATCH"
            print(f"  {m['folder']:<43} {lid:<8} {m['score']:>6.2f} {m['images']:>6}  {m['lesson_title']}")
        unmatched = sum(1 for m in mapping if not m["lesson_id"])
        print(f"\n{len(mapping)} folders, {unmatched} unmatched.")
        return

    # Run vision analysis
    env = load_env()
    api_key = env.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found in .env")
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic not installed. Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)

    print(f"\nGenesis K-12 QC — LearnWorlds Vision Check")
    print(f"{len(mapping)} folders to analyze")
    print("=" * 60)

    results = {}
    if args.save and REPORT_PATH.exists():
        try:
            results = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results = {}

    high = medium = low = errors = 0

    for m in mapping:
        folder_name = m["folder"]
        lid = m["lesson_id"]
        title = m["lesson_title"]
        img_count = m["images"]

        if not lid:
            print(f"\n  [SKIP] '{folder_name}' — no lesson ID match (score {m['score']:.2f})")
            errors += 1
            continue

        print(f"\n  {lid} — {folder_name} ({img_count} imgs, sampling up to {MAX_IMAGES})")
        print(f"    → Platform title: {title}")

        try:
            result = analyze_folder(client, m["folder_path"], lid, title)
        except Exception as e:
            print(f"    [ERR] {e}")
            result = {"error": str(e)}
            errors += 1
            continue

        priority = result.get("priority", "medium")
        recs = result.get("block_recommendations", [])
        issues = result.get("formatting_issues", [])

        print(f"    priority={priority}  recs={len(recs)}  issues={len(issues)}")
        for issue in issues[:3]:
            print(f"      • {issue}")
        for rec in recs[:3]:
            print(f"      → [{rec.get('recommended_block','')}] {rec.get('section','')} — {rec.get('reason','')[:60]}")

        results[lid] = {
            "folder": folder_name,
            "lessonTitle": title,
            "imagesTotal": img_count,
            "imagesSampled": min(img_count, MAX_IMAGES),
            "result": result,
        }

        if priority == "high":
            high += 1
        elif priority == "medium":
            medium += 1
        else:
            low += 1

        time.sleep(1.0)  # avoid rate limit

    print(f"\n{'='*60}")
    print(f"Done. high={high} medium={medium} low={low} errors={errors}")

    if args.save:
        REPORT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report saved to {REPORT_PATH}")
    else:
        print("Run with --save to persist results.")


if __name__ == "__main__":
    main()
