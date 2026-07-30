---
name: youtube-transcript
description: Pull the title, channel, description, chapters and full transcript of a YouTube video into a local text file so it can actually be read and mined. Use whenever Shane pastes a YouTube link as a reference, asks what a video says, or wants a technique from a video applied to our systems. WebFetch on a youtube.com URL returns only the title — it cannot read the transcript, so always use this skill instead.
---

# YouTube transcript

Shane sends YouTube links as references for how to build or improve our systems
(video pipeline, agents, tooling). `WebFetch` on a YouTube URL returns the title and
nothing else — the page is a JS shell. This skill gets the real content.

## Run it

```bash
python .claude/skills/youtube-transcript/fetch.py "<url-or-video-id>"
```

Writes to `references/youtube/<video-id>/` (gitignored-safe, small text only):

- `meta.json`   — title, channel, upload date, duration, description, chapters
- `transcript.txt` — plain prose, one paragraph, deduped
- `transcript.tsv` — `start_seconds<TAB>text`, for quoting a specific moment

Then **read `transcript.txt`**. It is the point of the skill; do not stop at `meta.json`.

Useful flags:

- `--timestamps` also print the TSV path and a chapter list to stdout
- `--out <dir>` write somewhere else
- `--stdout` print the transcript instead of writing files (short videos only)

## Requirements

`yt-dlp` (pip). The script checks and tells you the install command if missing.
No API key. No cookies for public videos.

## Reading the result well

These are usually 30–60 minute tutorials, so the transcript runs 30k–60k characters.
Read the whole file once — the useful parts are rarely where you expect.

Pull out, explicitly:

1. **The named tools and versions.** Verify each actually exists (`npm view <pkg>`,
   `git ls-remote`) before building on it. Presenters demo pre-release things.
2. **What the presenter says did NOT work.** This is the highest-value content and
   the part summaries drop. Failed attempts, warnings, and "I wouldn't post this"
   moments save the most time.
3. **Cost and limits.** Token burn, render time, rate limits, plan tiers. Compare
   against how many times *we* would run it — their per-run cost times our volume.
4. **What is already solved on our side.** Presenters demo from zero. We usually
   have measured specs and working stages, so a chunk of any tutorial is
   re-deriving something we already have better. Say which parts those are rather
   than rebuilding them.

## Then

Report to Shane what actually changes for us, not a video summary. If it argues for
a change to a system, name the file and the change. Log anything decided in
`decisions/log.md`.

## Caveats

- **Auto-captions have no punctuation of their own** and mis-transcribe product
  names (tool names, model IDs, "Cloud Code" for "Claude Code"). Never quote a
  spelling from a transcript as authoritative — check it.
- Timestamps are caption-cue times, close but not frame-accurate.
- Age-restricted or private videos fail. Say so; do not work around it.
