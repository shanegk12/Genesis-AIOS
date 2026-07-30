---
name: firecrawl
description: Pull web pages down as local markdown - one page, a whole docs site, or a map of every URL on a host. Use whenever Shane pastes a URL and wants the content kept rather than glanced at, or says "scrape that", "crawl the docs", "pull these docs into references", "read the whole site", "save that page", "what does this site say". Also use whenever WebFetch comes back thin or empty, since that means the page was a JavaScript shell and WebFetch cannot render it. Runs locally with no API key and no cloud account.
---

# Local web scrape and crawl

Firecrawl-shaped, Firecrawl-free. Three verbs, no key, no account, no network
dependency beyond the site being fetched.

```bash
python .claude/skills/firecrawl/fetch.py scrape <url>              # text
python .claude/skills/firecrawl/fetch.py map    <url> --search <t> # URLs
python .claude/skills/firecrawl/fetch.py crawl  <url> --limit 25   # many pages
python .claude/skills/firecrawl/fetch.py shot   <url>              # screenshots
python .claude/skills/firecrawl/fetch.py styles <url>              # design tokens
```

Everything lands in `references/web/<host>/`:

- `pages/<slug>.md` — one file per page. Frontmatter carries the URL, title,
  fetch time, and which engine got it.
- `index.md` — the run: source, backend, page count, table of every page with
  its character count. **Start here after a crawl.**
- `map.txt` — one URL per line, from `map`.

## Which verb

| Situation | Verb |
|---|---|
| One page, want the text kept | `scrape` |
| "How big is this site / what's in it" | `map` first, always |
| A docs section, a reference set, several pages | `crawl` after `map` |
| "Does our page look right?" / responsive check | `shot` |
| "What colors and fonts is this site using?" | `styles` |
| One page, one question, don't need the text | just use `WebFetch` |

**Always `map` before you `crawl` anything you have not crawled before.** A crawl
with a bad `--include` spends its whole budget on locale duplicates and changelog
pages. `map --search` costs one request against the sitemap and shows you the
shape. `docs.firecrawl.dev` ships five translated copies of every page; a naive
crawl there is 80% wasted.

## Flags that matter

- `--limit N` — pages (crawl) or URLs (map). Default 25. Raise deliberately.
- `--include REGEX` / `--exclude REGEX` — repeatable, matched against the full
  URL. Applied to `map` as well as `crawl`. The locale filter you will reuse:
  `--exclude "/(es|fr|ja|zh|pt-BR|de|ko)/"`
- `--depth N` — link depth from the start URL. Default 3.
- `--render` — force a real browser on every page. Slow. Only when the fallback
  is not triggering on a page you know is dynamic.
- `--no-render` — never launch a browser. Fast bulk crawl of a static site.
- `--delay S` — seconds between requests, default 0.5. Raise it on a small site.
- `--stdout` — scrape only, print instead of writing. For a page you need once.
- `--ignore-robots` — off by default and should stay off for anyone else's site.

## How it decides to render

Plain `requests` first. If main-content extraction yields under 500 characters,
it assumes a JavaScript shell and re-fetches through Playwright Chromium. That is
why a YouTube watch page returns the real title instead of nothing. The output
says `[js-rendered]` and the frontmatter records it, so you always know which
engine produced a given file.

## Design verbs: `shot` and `styles`

`scrape` deliberately strips styling and layout to get clean prose. That is right
for research and useless for design work, which is what these two are for. Both
drive Chromium directly and ignore `--backend` — a Firecrawl server adds nothing.

**`shot`** — full-page screenshots at mobile (375, 2x DPR), tablet (768), and
desktop (1440), plus `shots/<slug>.html`, a contact sheet showing all three side
by side. **Open the HTML, not the PNGs.** Every page is scrolled top to bottom
before capture so lazy-loaded images are actually present; without that pass,
full-page shots come back with blank rectangles below the fold.

```bash
python .claude/skills/firecrawl/fetch.py shot https://gk12academy.com
python .claude/skills/firecrawl/fetch.py shot <url> --viewports 390,1280 --no-full-page
```

The PNGs are readable directly — read one to actually look at the page rather
than reasoning about what it probably renders like.

**`styles`** — the design tokens off a live page: background palette ranked by
**painted area**, text colours ranked by element count, font stacks, the full
type scale by tag, button treatments, and a paste-ready `:root` CSS block.

```bash
python .claude/skills/firecrawl/fetch.py styles https://gk12academy.com --top 20
```

Things that matter about the numbers:

- **Every colour is normalised to hex through the browser.** Tailwind v4 emits
  `lab()` and `oklab()`, which are unpastable; a canvas pixel read converts them
  using the same maths the visitor's browser used. Alpha shows as `#1b395b @0.68`.
- **Backgrounds rank by area, not count.** One hero section outweighs forty
  chips, and that reflects what the page actually looks like.
- **Near-identical colours are NOT merged.** If `#1b3a5c` and `#1b395b` both
  appear, that is a real inconsistency on the site, and collapsing them would
  hide it. Say so when you see it.
- `border-radius: 9999px` computes to `33554400px`; it is reported as `pill`.

## Backends

`--backend auto` (the default) checks `FIRECRAWL_API_URL`, default
`http://localhost:3002`. If a self-hosted Firecrawl answers there, it uses it;
otherwise it uses the local engine. **Same files, same layout, either way** — so
nothing downstream has to care, and standing up Docker later changes nothing
about how this skill is called. See `SELFHOST.md` for that path and for what it
does and does not buy.

Say which backend ran when you report results. The two differ on sites with bot
protection, and a quiet fallback is how a consent banner gets quoted as
documentation.

## Do not use this for

- **YouTube.** Use `/youtube-transcript`. This skill gets a video page's title
  and description; the transcript is a different mechanism entirely.
- **Authenticated pages.** No cookie or session support. It will fetch the login
  page and that page will look like a successful scrape. Check what you got.
- **A page you want summarised once and then forgotten.** `WebFetch` is cheaper.

## After a crawl

Read `index.md`, then read the pages that matter — not all of them. Then:

- If it is a reference we will use repeatedly (an API, a standard, a framework),
  distil it into `references/<topic>.md` in our own words and cite the source
  URL. The raw crawl is scaffolding, not the reference.
- `references/web/` is gitignored. It does not reach Ethan or Cade. Anything that
  should reach them has to be written somewhere else.
- Say plainly which pages came back thin or failed. A crawl that reports 25 pages
  where 6 are cookie banners is a failed crawl, not a 25-page crawl.

## Triggers, and wiring them on a second machine

Three things route work here. Two of them ship in git, one does not.

1. **This skill's description** — ships (`.claude/skills/` is un-ignored).
2. **`UserPromptSubmit`** — a URL plus intent to pull it down. Logic is in
   `scripts/aios_hooks.py --mode prompt`, which ships.
3. **`PostToolUse` on `WebFetch`** — response under 600 chars, or containing a
   "enable JavaScript" / bot-check marker. Logic is
   `scripts/aios_hooks.py --mode webfetch`, which ships.

`.claude/settings.json` is **gitignored and per-machine**, so hooks 2 and 3 are
inert on a fresh clone until this is pasted into its `hooks.PostToolUse` array
(hook 2 rides the existing `UserPromptSubmit` entry and needs nothing):

```json
{
  "matcher": "WebFetch",
  "hooks": [
    {
      "type": "command",
      "command": "python \"$CLAUDE_PROJECT_DIR/scripts/aios_hooks.py\" --mode webfetch 2>/dev/null || true",
      "timeout": 10
    }
  ]
}
```

Deps on a fresh machine — note the skill has its **own** requirements file,
deliberately kept out of the repo root because the root one is baked into the
Cloud Run pipeline image:

```bash
pip install -r .claude/skills/firecrawl/requirements.txt
python -m playwright install chromium
```

## Limits worth stating out loud

- No proxy rotation and no anti-bot handling. Cloudflare-protected sites will
  fail, and they fail by returning a challenge page that looks like content.
  The WebFetch hook catches the obvious cases; check the character counts for
  the rest.
- Sequential by design. A 100-page crawl is minutes, not seconds. That is the
  politeness budget, not a bug to optimise away.
- `robots.txt` is honoured. Blocked URLs are printed and skipped.
