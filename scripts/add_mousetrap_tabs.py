"""
Adds the remaining Mousetrap course lesson tabs to the Google Doc.
Runs a single batchUpdate with all 46 createTab requests.
"""

import subprocess, json, sys, tempfile, os

DOC_ID = "1lgCiQjWdS3k7a4M8ku8EnRmn9VVV6DyKtJInCVuOFxc"

NEW_TABS = [
    "Engineering Notebook: Entry 5",
    # Topic 7: Materials and Sourcing
    "Lesson: Bill of Materials",
    "Lesson: Material Preparation",
    "Build: Inventory Checks and Verifications",
    # Topic 8: Fabrication
    "Lesson: Precision Finishing and Tolerance",
    "Lesson: Sourcing Alternatives and Costing",
    "Build: Material Processing",
    "Procurement Activity: Bill of Materials",
    # Topic 9: Project Flow and Scheduling
    "Lesson: Project Phases and Dependencies",
    "Lesson: Critical Paths and Calculating Time",
    "Business Activity: Break Even Analysis and Pricing",
    "Business Activity: Patents, IP Principles + Engineer Liability Scenario",
    # Topic 10: Supply Chain and Distribution
    "Lesson: External Supply Chains",
    "Lesson: Risks and Contingencies",
    "Logistics Activity: Supply Chain Map and Risk Analysis",
    "Business Activity: Customer Persona + Honest Marketing Standards",
    # Topic 11: Assembly Planning and Quality
    "Lesson: Assembly Blueprint and Safety Review",
    "Lesson: Frame, Axle, and Wheel Integration",
    "Build: Body and Mousetrap",
    "Build: Power System and Axles",
    # Topic 12: Systems and Production Control
    "Lesson: Component Alignment and Quality",
    "Lesson: Post-Build Systems",
    "Build: Braking System and Test",
    "Build: Arduino Station and Test",
    # Topic 13: Performance Optimization and Iteration
    "Lesson: Test Protocol and Baselines",
    "Lesson: Variables and Optimization Cycle",
    "Performance Activity: Baselines and Predictions",
    "Build: Variable Confirmation Tests",
    # Topic 14: Function, Verification, and Certification
    "Lesson: Final Function Verification",
    "Lesson: Performance Data",
    "Build: Optimization Tests",
    "Performance Activity: Final Runs and Data Presentation",
    # Topic 15: Lifecycle Analysis and Environmental Impact
    "Lesson: Product End-of-Life Analysis",
    "Lesson: Sustainable Materials",
    "Business Activity: Product Sheet Design + 2-Minute Pitch Practice",
    # Topic 16: Innovation and Future Planning
    "Lesson: V2.0 Design in Sustainability",
    "Lesson: Total Cost and Lifecycle Improvement Plan",
    "Sustainability Activity: Future Designs",
    "Business Activity: Org Chart + Production Gantt Chart",
    # Topic 17: Reuse and Disposal
    "Lesson: Classifying End of Life",
    "Lesson: Principles of E-Waste and Safe Disposal",
    "Business Activity: Business Plan Compilation + Pitch Rehearsal",
    # Topic 18: End-of-Life Actions
    "Lesson: Salvage Value and Resource Recovery",
    "Lesson: Closing a Project",
    "Death and Recycling Activity: End of Life Classification",
    "Final Activity: Parent Pitch Night",
]

requests = [
    {"createTab": {"tabProperties": {"title": title}}}
    for title in NEW_TABS
]

body = {"requests": requests}
params = {"documentId": DOC_ID}

# Write JSON to temp files to avoid shell quoting issues
tmp_dir = tempfile.gettempdir()
params_file = os.path.join(tmp_dir, "gws_params.json")
body_file = os.path.join(tmp_dir, "gws_body.json")

with open(params_file, "w", encoding="utf-8") as f:
    json.dump(params, f)
with open(body_file, "w", encoding="utf-8") as f:
    json.dump(body, f)

print(f"Adding {len(NEW_TABS)} tabs to Mousetrap course doc...")

# Use @file syntax if supported, otherwise read and pass inline
cmd = f'gws docs documents batchUpdate --params @"{params_file}" --json @"{body_file}"'
result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

# Filter keyring noise
output = "\n".join(l for l in result.stdout.splitlines() if not l.startswith("Using keyring"))
stderr = result.stderr.strip()

if result.returncode == 0:
    print(f"Success! {len(NEW_TABS)} tabs added.")
    print(output[:500] if output else "")
else:
    print(f"Error (exit {result.returncode}):")
    print(stderr or output)
    sys.exit(1)
