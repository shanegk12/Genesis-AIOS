"""Pull a YouTube video's metadata and full transcript to local text files.

WebFetch on a youtube.com URL returns the title and nothing else -- the page is a
JS shell -- so this exists to get the actual words. Auto-generated captions are
used when there is no human-authored track.

    python fetch.py "https://www.youtube.com/watch?v=ID"
    python fetch.py ID --timestamps
    python fetch.py ID --stdout
"""
import argparse
import html
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))          # .../.claude/skills/<skill>/fetch.py -> repo
DEFAULT_OUT = os.path.join(REPO, "references", "youtube")


def need_yt_dlp():
    try:
        import yt_dlp                                              # noqa: F401
        return
    except ImportError:
        sys.exit("yt-dlp is not installed.  Fix:  pip install yt-dlp")


def video_id(s):
    """Accept a full URL, a share URL, or a bare 11-char id."""
    s = s.strip()
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    m = re.search(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([\w-]{11})", s)
    if not m:
        sys.exit(f"could not find a video id in: {s}")
    return m.group(1)


def parse_vtt(raw):
    """VTT -> [(start_seconds, text)], de-duplicated.

    Auto-captions repeat each line across cues as the rolling caption builds, and
    carry inline <c> karaoke tags. Both have to go or the transcript triples in
    size and reads as gibberish.
    """
    out = []
    cue_start = None
    for line in raw.splitlines():
        line = line.rstrip()
        if "-->" in line:
            hms = line.split("-->")[0].strip()
            try:
                h, m, s = hms.split(":")
                cue_start = int(h) * 3600 + int(m) * 60 + float(s)
            except ValueError:
                cue_start = None
            continue
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        text = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()
        if not text:
            continue
        # auto-captions re-emit the previous line as the cue scrolls
        if out and (text == out[-1][1] or text in out[-1][1]):
            continue
        out.append((cue_start if cue_start is not None else 0.0, text))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="YouTube URL or bare 11-character video id")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--timestamps", action="store_true",
                    help="also print chapters and the TSV path")
    ap.add_argument("--stdout", action="store_true",
                    help="print the transcript instead of writing files")
    a = ap.parse_args()

    need_yt_dlp()
    import yt_dlp

    vid = video_id(a.url)
    url = f"https://www.youtube.com/watch?v={vid}"

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                           "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)

    # Prefer a human-authored English track; fall back to auto-captions. Both are
    # keyed by locale ("en", "en-US", "en-orig"), so match on prefix.
    def pick(d):
        for k in sorted(d or {}):
            if k.split("-")[0].lower() == "en":
                return d[k]
        return None

    track = pick(info.get("subtitles")) or pick(info.get("automatic_captions"))
    automatic = not pick(info.get("subtitles"))
    if not track:
        sys.exit(f"no English captions available for {vid} "
                 f"({info.get('title')!r}) -- nothing to transcribe.")

    vtt_url = next((f["url"] for f in track if f.get("ext") == "vtt"), track[0]["url"])
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        raw = ydl.urlopen(vtt_url).read().decode("utf8", "replace")

    cues = parse_vtt(raw)
    if not cues:
        sys.exit("caption file parsed to zero lines -- format may have changed.")
    prose = re.sub(r"\s+", " ", " ".join(t for _, t in cues)).strip()

    if a.stdout:
        print(prose)
        return

    dest = os.path.join(a.out, vid)
    os.makedirs(dest, exist_ok=True)

    meta = {
        "id": vid, "url": url,
        "title": info.get("title"),
        "channel": info.get("uploader") or info.get("channel"),
        "upload_date": info.get("upload_date"),
        "duration_sec": info.get("duration"),
        "captions": "auto-generated" if automatic else "author-provided",
        "chapters": [{"start": c.get("start_time"), "title": c.get("title")}
                     for c in (info.get("chapters") or [])],
        "description": info.get("description"),
    }
    with open(os.path.join(dest, "meta.json"), "w", encoding="utf8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    with open(os.path.join(dest, "transcript.txt"), "w", encoding="utf8") as f:
        f.write(prose + "\n")
    with open(os.path.join(dest, "transcript.tsv"), "w", encoding="utf8") as f:
        for t, txt in cues:
            f.write(f"{t:.2f}\t{txt}\n")

    mins = (info.get("duration") or 0) / 60
    print(f"{meta['title']}")
    print(f"  {meta['channel']}   {mins:.0f} min   {meta['captions']}")
    print(f"  {len(prose):,} chars, {len(cues):,} cues")
    print(f"  -> {os.path.join(dest, 'transcript.txt')}   <- READ THIS")
    if a.timestamps:
        print(f"  -> {os.path.join(dest, 'transcript.tsv')}")
        for c in meta["chapters"]:
            print(f"     {c['start']:>7.0f}s  {c['title']}")


if __name__ == "__main__":
    main()
