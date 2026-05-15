import json, subprocess, shutil, tempfile, os, sys

sys.path.insert(0, os.path.dirname(__file__))
from lesson_pipeline import gws_run

doc_id = "1oKMuj29QBxEz7ji4GedBiUP0b3a3ESr20L_OK128IEY"
data = gws_run({"documentId": doc_id, "includeTabsContent": True}, subcommand="docs documents get")

# Show top-level keys
print("Top-level keys:", list(data.keys()))

# Show tabs structure
tabs = data.get("tabs", [])
print(f"tabs count: {len(tabs)}")

print("\nAll tab titles (first 35):")
for t in tabs[:35]:
    props = t.get("tabProperties", {})
    print(f"  [{props.get('index'):3d}] id={props.get('tabId'):8s}  title={props.get('title')}")
