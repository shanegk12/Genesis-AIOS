"""One-shot script to add missing lessons to the manifest and fix bad doc refs."""
import json
from collections import Counter

MANIFEST_PATH = "scripts/lessons_manifest.json"

with open(MANIFEST_PATH, encoding="utf-8") as f:
    d = json.load(f)

lessons = d["lessons"]


def entry(lid, doc, tab_number, tab, phase, prev, ltype="lesson"):
    return {
        "id": lid, "doc": doc, "tab_number": tab_number, "tab": tab,
        "topic": tab, "phase": phase, "prev": prev, "type": ltype,
        "status": "done", "completed_at": None, "error": None,
        "qc_status": None,
    }


# ── Creationeering: 28 missing lessons ────────────────────────────────────────
c_new = [
    entry("C-001","creationeering",1,"What is Creationeering","Introduction",""),
    entry("C-002","creationeering",2,"Entrepreneurship","Introduction","What is Creationeering"),
    entry("C-003","creationeering",3,"Genesis and Creationeering","Introduction","Entrepreneurship"),
    entry("C-004","creationeering",4,"Using Math and Science as Tools","Introduction","Genesis and Creationeering"),
    entry("C-005","creationeering",5,"Units, Conversions, and Measurement","Introduction","Using Math and Science as Tools"),
    entry("C-006","creationeering",6,"Intro to Systems Thinking","Introduction","Units, Conversions, and Measurement"),
    entry("C-007","creationeering",7,"Objectives, Constraints, and Variables","Design","Intro to Systems Thinking"),
    entry("C-008","creationeering",8,"Ethics in Engineering","Design","Objectives, Constraints, and Variables"),
    entry("C-009","creationeering",9,"Understanding Process Mapping and Flowcharts","Design","Ethics in Engineering"),
    entry("C-010","creationeering",10,"Visualization and Sketching","Design","Understanding Process Mapping and Flowcharts"),
    entry("C-011","creationeering",11,"Design: Forces and Influences","Design","Visualization and Sketching"),
    entry("C-012","creationeering",12,"Design: Historical Case Studies","Design","Design: Forces and Influences"),
    entry("C-013","creationeering",13,"Form, Function, and Aesthetic","Design","Design: Historical Case Studies"),
    entry("C-014","creationeering",14,"Design Iteration and Communication","Design","Form, Function, and Aesthetic"),
    entry("C-015","creationeering",15,"Alternatives and Patents","Design","Design Iteration and Communication"),
    entry("C-016","creationeering",16,"Novelty and Innovation in Engineering","Design","Alternatives and Patents"),
    entry("C-017","creationeering",17,"Concept Generation","Design","Novelty and Innovation in Engineering"),
    entry("C-018","creationeering",18,"Fundamentals of Motion and Work","Analysis & Synthesis","Concept Generation"),
    entry("C-019","creationeering",19,"Energy Conservation, Transfer and Loss","Analysis & Synthesis","Fundamentals of Motion and Work"),
    entry("C-020","creationeering",20,"The Importance of Data in Engineering","Analysis & Synthesis","Energy Conservation, Transfer and Loss"),
    entry("C-021","creationeering",21,"Design of Experiments (One Factor at A Time)","Analysis & Synthesis","The Importance of Data in Engineering"),
    entry("C-022","creationeering",22,"Measurement Quality and Instrument Validation","Analysis & Synthesis","Design of Experiments (One Factor at A Time)"),
    entry("C-023","creationeering",23,"Modeling Reality: Physical vs. Computational","Analysis & Synthesis","Measurement Quality and Instrument Validation"),
    entry("C-024","creationeering",24,"Statistical Analysis","Analysis & Synthesis","Modeling Reality: Physical vs. Computational"),
    entry("C-026","creationeering",26,"Managing Resistive Sources","Analysis & Synthesis","What is Synthesis?"),
    entry("C-027","creationeering",27,"Stress and Strain","Analysis & Synthesis","Managing Resistive Sources"),
    entry("C-028","creationeering",28,"Protecting Your Business","Analysis & Synthesis","Stress and Strain"),
    entry("C-029","creationeering",29,"Troubleshooting and Debugging Systems","Analysis & Synthesis","Protecting Your Business"),
]

# ── Mousetrap: 21 missing lessons ─────────────────────────────────────────────
m_new = [
    entry("M-001","mousetrap",1,"Syllabus and Instructional Guide","Introduction","","activity"),
    entry("M-002","mousetrap",2,"Course Introduction","Introduction","Syllabus and Instructional Guide"),
    entry("M-003","mousetrap",3,"Build Kit Overview","Introduction","Course Introduction"),
    entry("M-004","mousetrap",4,"Objectives, Constraints, and Variables","Design","Build Kit Overview"),
    entry("M-005","mousetrap",5,"Prototypes","Design","Objectives, Constraints, and Variables"),
    entry("M-006","mousetrap",6,"Build 1: Little Moe Prototype Car","Design","Prototypes","build"),
    entry("M-009","mousetrap",9,"Business Plan","Design","The Arduino"),
    entry("M-010","mousetrap",10,"Business Activity: Company Identity","Design","Business Plan","activity"),
    entry("M-011","mousetrap",11,"Fundamentals of Design","Design","Business Activity: Company Identity"),
    entry("M-012","mousetrap",12,"Communicating Designs and Testing","Design","Fundamentals of Design"),
    entry("M-013","mousetrap",13,"Build 2: Iterative Design - Mark 1","Design","Communicating Designs and Testing","build"),
    entry("M-014","mousetrap",14,"Power Transmission Mechanisms","Analysis & Synthesis","Build 2: Iterative Design - Mark 1"),
    entry("M-015","mousetrap",15,"Energy Flow, Loss, and Efficiency","Analysis & Synthesis","Power Transmission Mechanisms"),
    entry("M-016","mousetrap",16,"Build 2: Iterative Design - Mark 2","Analysis & Synthesis","Energy Flow, Loss, and Efficiency","build"),
    entry("M-018","mousetrap",18,"The Dynamics of Stored Energy","Analysis & Synthesis","Analysis Activity: Calculations and Efficiency"),
    entry("M-019","mousetrap",19,"Modeling Resistive Forces","Analysis & Synthesis","The Dynamics of Stored Energy"),
    entry("M-020","mousetrap",20,"Build 3: CAD Analysis of Design Parameters","Analysis & Synthesis","Modeling Resistive Forces","build"),
    entry("M-021","mousetrap",21,"Instrumentation and Data Types","Analysis & Synthesis","Build 3: CAD Analysis of Design Parameters"),
    entry("M-022","mousetrap",22,"The Engineering Report Structure","Analysis & Synthesis","Instrumentation and Data Types"),
    entry("M-023","mousetrap",23,"Build 4: Arduino - Distance Sensor Calibration","Analysis & Synthesis","The Engineering Report Structure","build"),
    entry("M-024","mousetrap",24,"Analysis Gate Review","Analysis & Synthesis","Build 4: Arduino - Distance Sensor Calibration","activity"),
]

# ── Fix C-076 and C-088 ───────────────────────────────────────────────────────
for l in lessons:
    if l["id"] in ("C-076", "C-088"):
        l["doc"] = "creationeering"
        l["status"] = "pending"
        l["error"] = None
        print(f"Fixed {l['id']}: doc=creationeering, status=pending")

# ── Merge ─────────────────────────────────────────────────────────────────────
existing_ids = {l["id"] for l in lessons}
new_entries = [e for e in c_new + m_new if e["id"] not in existing_ids]
print(f"Adding {len(new_entries)} new entries")

all_lessons = lessons + new_entries
all_lessons.sort(key=lambda l: (l["id"][0], int(l["id"][2:])))

d["lessons"] = all_lessons

with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

# ── Summary ───────────────────────────────────────────────────────────────────
statuses = Counter(l["status"] for l in all_lessons)
print(f"\nManifest updated: {len(all_lessons)} total lessons")
print(f"Statuses: {dict(statuses)}")
for doc in ("creationeering", "mousetrap"):
    sub = [l for l in all_lessons if l["doc"] == doc]
    counts = Counter(l["status"] for l in sub)
    print(f"  {doc}: {dict(counts)}  total={len(sub)}")
