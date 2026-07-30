# LearnWorlds import - retired 2026-07-30

The LearnWorlds screenshot import is finished. LearnWorlds itself was superseded by
the custom platform (Genesis Education Solutions), so this batch tooling has no
remaining use.

Retired here rather than deleted, per the archive convention in CLAUDE.md.

- `screenshot_import_batch.py` - batch driver over `screenshot_import.py`. Self-contained
  (stdlib only); nothing else imported it.
- `screenshots_import_output/` - its JSON output.

**Still live in `scripts/`, deliberately not retired:** `screenshot_import.py`,
`screenshot_extract_images.py`. The `screenshots/` folder is also still in use for
screenshots of systems being built. Only the batch driver was LearnWorlds-specific.
