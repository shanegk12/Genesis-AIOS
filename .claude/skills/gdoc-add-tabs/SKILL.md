---
name: gdoc-add-tabs
description: Use when you need to add one or more tabs to a Google Doc. Trigger on "add tabs to the doc", "create a new tab in the doc", "add lessons to the Google Doc", or when an agent needs to write structured data into a Google Doc as a new tab. Works with any doc accessible via gws. Handles tab title truncation, JSON body construction, and the correct batchUpdate call automatically.
---

## What this skill does

Adds one or more named tabs to a Google Doc in a single `batchUpdate` API call via the `gws` CLI. Handles all known failure modes (see Lessons Learned below). Can be used standalone or called by other agents/skills that need to write scoped data into a doc.

---

## Inputs

- **Doc ID** — the Google Doc ID (from the URL or `.env`). Required.
- **Tab titles** — a list of tab names to add. Required.
- **Insertion point** — optional. Defaults to appending after the last existing tab.

Common doc IDs are in `d:\AIOS\.env`:
- `GOOGLE_DOC_CREATIONEERING_LESSON_BOOK` — 89-tab Creationeering course
- `GOOGLE_DOC_MOUSETRAP_COURSE` — Mousetrap build course

---

## Execution

### Step 1: Collect inputs

Ask for the doc ID and list of tab titles if not provided. If the user says "add these to the Mousetrap doc" or "add these to the Creationeering book", resolve the doc ID from `.env`.

### Step 2: Validate tab titles

**Hard rule:** Google Docs API rejects any tab title over 50 characters with a 400 error.

Before building the request:
- Check every title: `len(title) <= 50`
- For any title over 50 chars, truncate smartly (preserve meaning — shorten prefix like "Business Activity:" to "BA:" before cutting the end)
- Show the user a before/after table for any title that was shortened and confirm before proceeding

### Step 3: Build the JSON body

Write the request body to a Windows temp file to avoid shell quoting issues with large payloads:

```python
import json, os, tempfile

doc_id = "YOUR_DOC_ID"
tab_titles = ["Tab 1", "Tab 2", ...]  # validated, all <= 50 chars

body = {
    "requests": [
        {"addDocumentTab": {"tabProperties": {"title": t}}}
        for t in tab_titles
    ]
}

path = os.path.join(tempfile.gettempdir(), "gdoc_tabs_body.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(body, f)
```

### Step 4: Run the batchUpdate via Bash

Use the Bash tool (not Python subprocess) to invoke gws. Pass the JSON body via shell variable read from the temp file:

```bash
BODY=$(cat "C:\Users\Shane\AppData\Local\Temp\gdoc_tabs_body.json") \
  && gws docs documents batchUpdate \
     --params '{"documentId":"DOC_ID_HERE"}' \
     --json "$BODY" 2>&1 | grep -v "Using keyring"
```

### Step 5: Confirm and report

Parse the response. For each successful `addDocumentTab` reply, the API returns the tab's assigned index and tabId. Report:
- How many tabs were added
- The index range they occupy (e.g., "tabs 25-70")
- Any titles that were truncated and what they were shortened to

---

## Lessons Learned (from 2026-05-14)

| Failure | Cause | Fix |
|---|---|---|
| `gws auth` error on startup | Credentials created on a different machine, keyring can't decrypt | Run `gws auth logout && gws auth login` to re-authenticate |
| `FileNotFoundError` from Python subprocess | `shell=False` can't find `gws` on Windows PATH | Use the Bash tool directly instead of Python subprocess |
| `createTab: Unknown property` | Wrong operation name | Use `addDocumentTab`, not `createTab` |
| `400: tab title cannot be longer than 50 characters` | Long titles fail silently until the API rejects the whole batch | Validate all titles before calling; truncate to ≤50 chars |
| `@file` not supported by gws | gws doesn't read JSON from file paths | Write JSON to temp file, read with `$(cat ...)` in Bash |

---

## Critical rules

1. **Always validate title lengths before calling.** One long title fails the entire batch.
2. **Use Bash tool for the gws call, not Python subprocess.** subprocess can't resolve gws on Windows without `shell=True`, and `shell=True` makes quoting fragile with large JSON.
3. **Temp file for the JSON body.** Never try to inline a large JSON payload directly in a bash command string.
4. **`addDocumentTab` is the correct operation.** Not `createTab`.
5. **Confirm truncations with the user** before writing — shortened titles may lose context.
6. **Never delete or reorder existing tabs** unless explicitly asked. This skill appends only.
