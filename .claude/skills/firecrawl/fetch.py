"""Pull web pages into local markdown the way Firecrawl does, without the cloud.

Five verbs. Three mirror the Firecrawl v2 API so the mental model transfers; two
exist because markdown extraction throws away exactly what design work needs.

    python fetch.py scrape <url>              one page  -> markdown
    python fetch.py map    <url>              discover every URL on a site
    python fetch.py crawl  <url> --limit 40   walk a site -> one file per page
    python fetch.py shot   <url>              screenshots at 3 viewports
    python fetch.py styles <url>              palette, fonts, type scale, buttons

Two interchangeable backends, chosen automatically:

  local      requests -> (Playwright only if the page turns out to be a JS shell)
             -> trafilatura main-content extraction. No server, no key, no Docker.

  firecrawl  POST to a self-hosted Firecrawl at FIRECRAWL_API_URL (default
             http://localhost:3002) when one is actually answering. Same output
             files either way, so nothing downstream has to care which ran.

The backend used is printed and written into every file's frontmatter. Never
report a page as fetched without saying which engine got it -- the two differ on
sites with bot protection, and a silent fallback is how you end up quoting a
consent banner as documentation.

Politeness is on by default: robots.txt is honoured and requests are spaced.
--ignore-robots exists for pages you own; it is not the default for a reason.
"""
import argparse
import os
import re
import sys
import time
import urllib.robotparser
import warnings
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag

# Sitemaps are XML but get the HTML parser on purpose -- html.parser is stdlib and
# handles them fine, and lxml is one more dependency for no gain here. bs4 warns
# about it on every sitemap; the warning has to be silenced by category, since its
# message text never contains the class name.
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass                                  # need() gives the real message later

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))          # .../.claude/skills/<skill>/fetch.py -> repo
DEFAULT_OUT = os.path.join(REPO, "references", "web")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

# Below this many characters of extracted prose, assume the HTML was a shell and
# the real content is behind JavaScript. Tuned high enough to catch SPA roots,
# low enough that a genuinely short page (a 404, a stub) does not pay for a
# browser launch twice.
THIN_CHARS = 500

DEFAULT_SERVER = os.environ.get("FIRECRAWL_API_URL", "http://localhost:3002").rstrip("/")


# --------------------------------------------------------------------------- deps

def need(mod, pip_name=None):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"{mod} is not installed.  Fix:  pip install {pip_name or mod}")


# --------------------------------------------------------------------------- util

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def host_of(url):
    return urlparse(url).netloc.lower().lstrip("www.") or "unknown-host"


def clean(url):
    """Drop the fragment and trailing slash so /docs and /docs/#x are one page."""
    url, _ = urldefrag(url)
    if url.endswith("/") and urlparse(url).path != "/":
        url = url[:-1]
    return url


def slugify(url, taken):
    """A filename that still tells you which page it was.

    Windows path limit is the real constraint here, so the slug is capped and
    collisions get a counter rather than silently overwriting a sibling page.
    """
    p = urlparse(url)
    raw = (p.path or "/").strip("/")
    if p.query:
        raw = f"{raw}-{p.query}"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-").lower() or "index"
    slug = slug[:80].rstrip("-.")
    if slug.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}:
        slug = "_" + slug
    base, n = slug, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    taken.add(slug)
    return slug


def frontmatter(url, title, backend, rendered):
    return (f"---\nurl: {url}\ntitle: {(title or '').replace(chr(10), ' ')}\n"
            f"fetched: {now()}\nbackend: {backend}"
            f"{' (js-rendered)' if rendered else ''}\n---\n\n")


# --------------------------------------------------------------------- local engine

_robots = {}


def allowed(url, ignore):
    if ignore:
        return True
    p = urlparse(url)
    root = f"{p.scheme}://{p.netloc}"
    rp = _robots.get(root)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(root + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp.allow_all = True          # no robots.txt reachable == not a refusal
        _robots[root] = rp
    try:
        return rp.can_fetch(UA, url)
    except Exception:
        return True


def render(url, wait_ms):
    """Load the page in a real browser. Only called when plain HTML came back thin."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(user_agent=UA)
            pg.goto(url, wait_until="networkidle", timeout=45000)
            if wait_ms:
                pg.wait_for_timeout(wait_ms)
            return pg.content()
        finally:
            b.close()


def respace(md):
    """trafilatura emits `Welcome to[Firecrawl](url)!` -- no space before the link.

    Harmless to a parser, but these files get read by a person and by me, and
    glued words change how a sentence scans. Prose lines only: inside a fenced
    block or an indented block, `)` followed by a letter is usually real code.
    """
    out, fenced = [], False
    for line in md.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        if fenced or line.startswith(("    ", "\t")):
            out.append(line)
            continue
        line = re.sub(r"(?<=[a-zA-Z0-9.,;:!?])\[", " [", line)
        line = re.sub(r"\)(?=[a-zA-Z0-9])", ") ", line)
        out.append(line)
    return "\n".join(out)


def to_markdown(html, url):
    """Main content only -- strip nav, headers, footers, cookie bars.

    trafilatura is the primary because it is what `onlyMainContent` amounts to.
    markdownify on <main>/<article> is the fallback for pages it declines to
    parse (short pages, unusual markup), and is deliberately dumber.
    """
    import trafilatura
    md = trafilatura.extract(html, output_format="markdown", include_links=True,
                             include_tables=True, url=url, favor_precision=False)
    if md and len(md) >= 200:
        return respace(md)

    from bs4 import BeautifulSoup
    from markdownify import markdownify
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                     "aside", "form", "svg"]):
        tag.decompose()
    node = soup.find("main") or soup.find("article") or soup.body or soup
    out = markdownify(str(node), heading_style="ATX").strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def title_of(html):
    import trafilatura
    try:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            return meta.title
    except Exception:
        pass
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def local_scrape(url, force_render=False, no_render=False, wait_ms=0, timeout=30):
    """-> (markdown, title, html, rendered_bool). Raises on transport failure."""
    import requests
    html, rendered = "", False

    if not force_render:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en"},
                         timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype:
            # A PDF or a JSON endpoint. Hand back the bytes as-is rather than
            # pretending an HTML extractor said something meaningful about it.
            return (r.text if "text" in ctype or "json" in ctype
                    else f"[non-text content: {ctype}, {len(r.content):,} bytes]"), "", "", False
        html = r.text

    md = to_markdown(html, url) if html else ""
    if (force_render or len(md) < THIN_CHARS) and not no_render:
        try:
            html = render(url, wait_ms)
            md, rendered = to_markdown(html, url), True
        except Exception as e:
            if not html:
                raise
            print(f"    ! render failed ({type(e).__name__}), keeping static HTML", file=sys.stderr)

    return md, title_of(html), html, rendered


# --------------------------------------------------------------------- design tools

# Named after what they are for, not their pixel width -- the point of the sweep
# is "does it work on a phone", and 375 is the narrowest phone still worth caring
# about. Heights are viewport heights only; every shot is full-page.
VIEWPORTS = [("mobile", 375, 812), ("tablet", 768, 1024), ("desktop", 1440, 900)]

# Colours reach us as rgb(), rgba(), lab() and oklab() -- Tailwind v4 emits the
# last two, and neither is pastable into anything. Rather than implement Lab to
# sRGB by hand, paint one pixel and read it back: the browser already owns the
# conversion, and it is the same conversion the user is actually seeing.
HEX_FN = """
  const _c = document.createElement('canvas'); _c.width = _c.height = 1;
  const _x = _c.getContext('2d', {willReadFrequently: true});
  const hex = (v) => {
    if (!v || v === 'none') return null;
    _x.clearRect(0, 0, 1, 1);
    _x.fillStyle = '#000'; _x.fillStyle = v;
    _x.fillRect(0, 0, 1, 1);
    const d = _x.getImageData(0, 0, 1, 1).data;
    const h = '#' + [d[0], d[1], d[2]].map(n => n.toString(16).padStart(2, '0')).join('');
    return d[3] < 255 ? h + ' @' + (d[3] / 255).toFixed(2) : h;
  };
"""

STYLE_JS = """() => {
  %s
  const els = [], buttons = [];
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const s = getComputedStyle(el);
    const transparent = s.backgroundColor === 'rgba(0, 0, 0, 0)';
    els.push({
      tag: el.tagName, area: Math.round(r.width * r.height),
      color: hex(s.color), bg: transparent ? null : hex(s.backgroundColor),
      ff: s.fontFamily, fs: parseFloat(s.fontSize), fw: s.fontWeight,
      lh: s.lineHeight, ls: s.letterSpacing,
      text: (el.childElementCount === 0 && el.textContent.trim().length > 0)
    });
    const cls = (typeof el.className === 'string' ? el.className : '');
    const isBtn = el.tagName === 'BUTTON' || el.getAttribute('role') === 'button'
                  || /\\bbtn\\b|\\bbutton\\b/i.test(cls);
    if (isBtn && buttons.length < 40) {
      buttons.push({label: el.textContent.trim().slice(0, 30),
                    bg: hex(s.backgroundColor), color: hex(s.color),
                    radius: s.borderRadius, padding: s.padding,
                    fs: s.fontSize, fw: s.fontWeight,
                    border: s.borderWidth === '0px' ? null : s.border});
    }
  }
  const m = (n) => (document.querySelector(`meta[name="${n}"]`)
                 || document.querySelector(`meta[property="og:${n}"]`) || {}).content || null;
  return {els, buttons, meta: {title: document.title, description: m('description'),
          themeColor: m('theme-color'), lang: document.documentElement.lang}};
}""" % HEX_FN


def settle(pg, wait_ms=0):
    """Scroll the whole page before measuring or shooting.

    Lazy-loaded images and scroll-triggered animations are the norm now. Without
    this a full-page screenshot has blank rectangles where the below-the-fold
    images should be, which looks like a broken site rather than a broken shot.
    """
    pg.evaluate("""async () => {
      const step = Math.floor(window.innerHeight * 0.8);
      for (let y = 0; y < document.body.scrollHeight; y += step) {
        window.scrollTo(0, y);
        await new Promise(r => setTimeout(r, 120));
      }
      window.scrollTo(0, 0);
      await new Promise(r => setTimeout(r, 250));
    }""")
    if wait_ms:
        pg.wait_for_timeout(wait_ms)


def shoot(url, dest, slug, viewports, wait_ms, full_page=True):
    from playwright.sync_api import sync_playwright
    os.makedirs(os.path.join(dest, "shots"), exist_ok=True)
    made = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            for name, w, h in viewports:
                pg = b.new_page(viewport={"width": w, "height": h}, user_agent=UA,
                                is_mobile=(name == "mobile"),
                                device_scale_factor=2 if name == "mobile" else 1)
                pg.goto(url, wait_until="networkidle", timeout=60000)
                settle(pg, wait_ms)
                path = os.path.join(dest, "shots", f"{slug}-{name}.png")
                pg.screenshot(path=path, full_page=full_page)
                height = pg.evaluate("document.body.scrollHeight")
                made.append((name, w, height, path))
                pg.close()
        finally:
            b.close()
    return made


def contact_sheet(dest, slug, url, made):
    """One HTML file showing every viewport side by side.

    Three PNGs in a folder do not answer "does this hold together"; three columns
    scaled to the same height do, and it opens in a browser with no tooling.
    """
    cols = "\n".join(
        f'<figure><figcaption>{n} &mdash; {w}px wide &times; {h}px tall</figcaption>'
        f'<img src="{os.path.basename(p)}" alt="{n}"></figure>'
        for n, w, h, p in made)
    html = f"""<!doctype html><meta charset="utf-8">
<title>{slug} - viewport sweep</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#f6f7f9;color:#111}}
 h1{{font-size:16px;margin:0 0 4px}} a{{color:#1b3a5c}}
 .row{{display:flex;gap:20px;align-items:flex-start;overflow-x:auto;padding-bottom:12px}}
 figure{{margin:0;flex:0 0 auto}}
 figcaption{{font-size:12px;color:#555;margin-bottom:6px}}
 img{{max-height:78vh;width:auto;border:1px solid #d5d8dd;border-radius:6px;background:#fff}}
 @media (prefers-color-scheme:dark){{body{{background:#14161a;color:#eee}}
  figcaption{{color:#aaa}} img{{border-color:#333}} a{{color:#8fb6e0}}}}
</style>
<h1>{slug}</h1><p><a href="{url}">{url}</a> &middot; {now()}</p>
<div class="row">{cols}</div>
"""
    path = os.path.join(dest, "shots", f"{slug}.html")
    with open(path, "w", encoding="utf8") as f:
        f.write(html)
    return path


def read_styles(url, wait_ms):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": 1440, "height": 900}, user_agent=UA)
            pg.goto(url, wait_until="networkidle", timeout=60000)
            settle(pg, wait_ms)
            return pg.evaluate(STYLE_JS)
        finally:
            b.close()


def swatch(hexval):
    """A colour chip that survives being read offline.

    An external placeholder-image service would be a network round trip inside a
    deliberately local tool, and it would quietly hand our palette to a third
    party every time the file is opened. Inline SVG owes nobody anything.
    """
    h = hexval.lstrip("#").split(" ")[0]
    return (f'![](data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="32" height="16"><rect width="32" height="16" rx="3" fill="%23{h}" '
            f'stroke="%23888" stroke-width="1"/></svg>)')


def radius(css):
    """Chrome computes `border-radius: 9999px` to 33554400px. Say what it means."""
    try:
        if max(float(p.rstrip("px")) for p in css.split() if p.endswith("px")) >= 9999:
            return "pill"
    except ValueError:
        pass
    return css


def style_report(url, data, top):
    """Aggregate raw computed styles into something a person can act on.

    Backgrounds are ranked by painted area and text colours by how many elements
    carry them, because those are the two questions worth asking: what dominates
    the page, and what is the type actually set in. Near-identical colours are
    NOT merged -- #1b3a5c and #1b395b differing is a fact about the site, and
    silently collapsing them would hide a real inconsistency.
    """
    els, meta = data["els"], data["meta"]
    bg_area, text_n, fonts = {}, {}, {}
    for e in els:
        if e["bg"]:
            bg_area[e["bg"]] = bg_area.get(e["bg"], 0) + e["area"]
        if e["text"] and e["color"]:
            text_n[e["color"]] = text_n.get(e["color"], 0) + 1
        if e["text"]:
            fonts[e["ff"]] = fonts.get(e["ff"], 0) + 1

    scale = {}
    for e in els:
        if e["tag"] in ("H1", "H2", "H3", "H4", "H5", "H6", "P", "LI", "A", "BUTTON"):
            scale.setdefault(e["tag"], {})[(e["fs"], e["fw"], e["lh"])] = \
                scale.setdefault(e["tag"], {}).get((e["fs"], e["fw"], e["lh"]), 0) + 1

    L = [f"# Styles — {meta.get('title') or host_of(url)}", "",
         f"- source: {url}", f"- captured: {now()} at 1440px",
         f"- visible elements measured: {len(els):,}"]
    if meta.get("themeColor"):
        L.append(f"- declared theme-color: `{meta['themeColor']}`")
    L += ["", "## Palette", "",
          f"Backgrounds by painted area — {len(bg_area)} distinct"
          f"{f', top {top}' if len(bg_area) > top else ''}.", "",
          "| swatch | hex | area (px²) | share |", "|---|---|---:|---:|"]
    total = sum(bg_area.values()) or 1
    for c, a in sorted(bg_area.items(), key=lambda kv: -kv[1])[:top]:
        L.append(f"| {swatch(c)} | `{c}` | {a:,} | {a / total:.1%} |")

    L += ["", f"Text colours by element count — {len(text_n)} distinct.", "",
          "| swatch | hex | elements |", "|---|---|---:|"]
    for c, n in sorted(text_n.items(), key=lambda kv: -kv[1])[:top]:
        L.append(f"| {swatch(c)} | `{c}` | {n} |")

    L += ["", "## Typography", "", "| font stack | text elements |", "|---|---:|"]
    for f, n in sorted(fonts.items(), key=lambda kv: -kv[1])[:8]:
        L.append(f"| `{f}` | {n} |")

    L += ["", "### Type scale", "", "| tag | size | weight | line-height | count |",
          "|---|---:|---:|---|---:|"]
    for tag in ("H1", "H2", "H3", "H4", "H5", "H6", "P", "LI", "A", "BUTTON"):
        for (fs, fw, lh), n in sorted(scale.get(tag, {}).items(), key=lambda kv: -kv[0][0]):
            L.append(f"| {tag} | {fs:g}px | {fw} | {lh} | {n} |")

    btns = {}
    for b in data["buttons"]:
        btns.setdefault((b["bg"], b["color"], b["radius"], b["padding"], b["fs"], b["fw"]),
                        []).append(b["label"])
    if btns:
        L += ["", "## Buttons", "", "| bg | text | radius | padding | size/weight | example |",
              "|---|---|---|---|---|---|"]
        for (bg, col, rad, pad, fs, fw), labels in list(btns.items())[:10]:
            ex = (labels[0] or "(icon)").replace("|", "\\|")[:24]
            L.append(f"| `{bg}` | `{col}` | {radius(rad)} | {pad or '0'} | "
                     f"{fs}/{fw} | {ex} |")

    # A paste-ready block is the whole point -- a table you have to retype is a
    # report, not a tool.
    def distinct(counts, n):
        # Alpha variants collapse to the same hex once the @0.68 is dropped, so
        # dedupe AFTER stripping it -- otherwise the block ships --bg-1 and
        # --bg-6 both set to #ffffff.
        seen, out = set(), []
        for c, _ in sorted(counts.items(), key=lambda kv: -kv[1]):
            base = c.split(" ")[0]
            if base not in seen:
                seen.add(base)
                out.append(base)
            if len(out) == n:
                break
        return out

    L += ["", "## Paste-ready", "", "```css", ":root {"]
    for i, c in enumerate(distinct(bg_area, 6), 1):
        L.append(f"  --bg-{i}: {c};")
    for i, c in enumerate(distinct(text_n, 4), 1):
        L.append(f"  --text-{i}: {c};")
    for i, f in enumerate(sorted(fonts, key=lambda k: -fonts[k])[:2], 1):
        L.append(f"  --font-{i}: {f};")
    L += ["}", "```", ""]
    return "\n".join(L)


def harvest_links(html, base):
    from bs4 import BeautifulSoup
    host = urlparse(base).netloc
    out = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = clean(urljoin(base, href))
        if urlparse(full).netloc == host and urlparse(full).scheme in ("http", "https"):
            out.append(full)
    return out


def sitemap_urls(root, timeout=20):
    """Sitemap first -- it is the site telling you its own shape, and it is one
    request instead of a crawl. Handles sitemap indexes one level deep."""
    import requests
    from bs4 import BeautifulSoup

    candidates = [f"{root}/sitemap.xml", f"{root}/sitemap_index.xml"]
    try:
        rb = requests.get(f"{root}/robots.txt", headers={"User-Agent": UA}, timeout=timeout)
        candidates += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rb.text)
    except Exception:
        pass

    found, seen_maps = [], set()
    queue = list(dict.fromkeys(candidates))
    while queue and len(found) < 50000:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            r = requests.get(sm, headers={"User-Agent": UA}, timeout=timeout)
            if r.status_code != 200 or "<" not in r.text[:200]:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            if soup.find("sitemapindex") and len(seen_maps) < 25:
                queue += [l.get_text(strip=True) for l in soup.select("sitemap > loc")]
            found += [l.get_text(strip=True) for l in soup.select("url > loc")]
        except Exception:
            continue
    return list(dict.fromkeys(clean(u) for u in found if u))


def local_map(url, limit, search, timeout, ignore_robots):
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    urls = sitemap_urls(root, timeout)
    source = "sitemap"

    if len(urls) < 5:
        # No usable sitemap. Two levels of links off the start page is enough to
        # see the shape of a docs site without turning map into a full crawl.
        source = "link-harvest"
        seen, frontier, urls = {clean(url)}, [clean(url)], [clean(url)]
        for _ in range(2):
            nxt = []
            for u in frontier[:40]:
                if not allowed(u, ignore_robots):
                    continue
                try:
                    _, _, html, _ = local_scrape(u, no_render=True, timeout=timeout)
                except Exception:
                    continue
                for link in harvest_links(html, u):
                    if link not in seen:
                        seen.add(link)
                        urls.append(link)
                        nxt.append(link)
                time.sleep(0.2)
            frontier = nxt
            if len(urls) >= limit:
                break

    if search:
        s = search.lower()
        # Relevance ordering, same idea as Firecrawl's /map search: URL hits first.
        urls = sorted([u for u in urls if s in u.lower()],
                      key=lambda u: (s not in urlparse(u).path.lower(), len(u)))
    return urls[:limit], source


# ------------------------------------------------------------------ firecrawl backend

def server_up(server, timeout=2):
    import requests
    try:
        r = requests.get(server, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def fc_post(server, path, body, timeout=180):
    import requests
    r = requests.post(f"{server}{path}", json=body, timeout=timeout,
                      headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def fc_scrape(server, url):
    j = fc_post(server, "/v2/scrape",
                {"url": url, "formats": ["markdown"], "onlyMainContent": True})
    d = j.get("data") or {}
    return d.get("markdown") or "", (d.get("metadata") or {}).get("title") or ""


def fc_map(server, url, limit, search):
    body = {"url": url, "limit": limit}
    if search:
        body["search"] = search
    j = fc_post(server, "/v2/map", body)
    links = (j.get("data") or {}).get("links") or j.get("links") or []
    return [l if isinstance(l, str) else l.get("url") for l in links if l]


def fc_crawl(server, url, limit, include, exclude, depth):
    import requests
    body = {"url": url, "limit": limit,
            "scrapeOptions": {"formats": ["markdown"], "onlyMainContent": True}}
    if include:
        body["includePaths"] = include
    if exclude:
        body["excludePaths"] = exclude
    if depth:
        body["maxDiscoveryDepth"] = depth

    job = fc_post(server, "/v2/crawl", body)
    jid = job.get("id")
    if not jid:
        sys.exit(f"self-hosted Firecrawl returned no job id: {job}")

    pages, nxt = [], f"{server}/v2/crawl/{jid}"
    while nxt:
        time.sleep(3)
        r = requests.get(nxt, timeout=120)
        r.raise_for_status()
        j = r.json()
        pages += j.get("data") or []
        status = j.get("status")
        print(f"    {status}: {len(pages)} page(s)", file=sys.stderr)
        if status in ("completed", "failed", "cancelled"):
            nxt = j.get("next") if status == "completed" and j.get("next") else None
        if status == "failed":
            sys.exit(f"crawl job failed: {j.get('error')}")
    return pages


# ------------------------------------------------------------------------- writing

def write_page(dest, slug, url, title, md, backend, rendered):
    os.makedirs(os.path.join(dest, "pages"), exist_ok=True)
    path = os.path.join(dest, "pages", slug + ".md")
    with open(path, "w", encoding="utf8") as f:
        f.write(frontmatter(url, title, backend, rendered) + (md or "").strip() + "\n")
    return path


def write_index(dest, source_url, backend, verb, rows, extra=""):
    path = os.path.join(dest, "index.md")
    with open(path, "w", encoding="utf8") as f:
        f.write(f"# {host_of(source_url)}\n\n"
                f"- source: {source_url}\n- verb: {verb}\n- backend: {backend}\n"
                f"- fetched: {now()}\n- pages: {len(rows)}\n\n{extra}"
                "| page | chars | file |\n|---|---:|---|\n")
        for title, url, chars, rel in rows:
            t = (title or url).replace("|", "\\|")[:70]
            f.write(f"| [{t}]({url}) | {chars:,} | `{rel}` |\n")
    return path


# ---------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Local Firecrawl-shaped web scraper.")
    ap.add_argument("verb", choices=["scrape", "map", "crawl", "shot", "styles"])
    ap.add_argument("url")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--backend", choices=["auto", "local", "firecrawl"], default="auto")
    ap.add_argument("--server", default=DEFAULT_SERVER,
                    help="self-hosted Firecrawl base URL (default $FIRECRAWL_API_URL)")
    ap.add_argument("--limit", type=int, default=25, help="max pages (crawl) / URLs (map)")
    ap.add_argument("--depth", type=int, default=3, help="max link depth from the start URL")
    ap.add_argument("--include", action="append", default=[], help="regex a URL must match")
    ap.add_argument("--exclude", action="append", default=[], help="regex a URL must not match")
    ap.add_argument("--search", help="map only: filter URLs by substring, ranked")
    ap.add_argument("--render", action="store_true", help="force a browser on every page")
    ap.add_argument("--no-render", action="store_true", help="never launch a browser")
    ap.add_argument("--wait", type=int, default=0, help="ms to wait after render")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--ignore-robots", action="store_true")
    ap.add_argument("--stdout", action="store_true", help="scrape only: print, write nothing")
    ap.add_argument("--viewports", help="shot only: comma-separated widths, e.g. 375,1440")
    ap.add_argument("--no-full-page", action="store_true",
                    help="shot only: capture the fold only, not the whole page")
    ap.add_argument("--top", type=int, default=12,
                    help="styles only: how many colours to report per table")
    a = ap.parse_args()

    need("requests")
    need("bs4", "beautifulsoup4")
    need("trafilatura")

    url = clean(a.url if "://" in a.url else "https://" + a.url)

    backend = a.backend
    if backend == "auto":
        backend = "firecrawl" if server_up(a.server) else "local"
    if backend == "firecrawl" and not server_up(a.server):
        sys.exit(f"no Firecrawl answering at {a.server}. Start it, or use --backend local.")
    label = f"firecrawl-selfhosted ({a.server})" if backend == "firecrawl" else "local"

    dest = os.path.join(a.out, host_of(url).replace(":", "_"))
    inc = [re.compile(p) for p in a.include]
    exc = [re.compile(p) for p in a.exclude]
    print(f"{a.verb} {url}\n  backend: {label}", file=sys.stderr)

    # ------------------------------------------------------- shot / styles (local)
    # Both drive Chromium directly. A self-hosted Firecrawl adds nothing here, so
    # they ignore --backend rather than pretending it applies.
    if a.verb in ("shot", "styles"):
        need("playwright")
        if not allowed(url, a.ignore_robots):
            sys.exit("robots.txt disallows this URL. --ignore-robots to override "
                     "(fine on a site you own).")
        os.makedirs(dest, exist_ok=True)
        slug = slugify(url, set())

        if a.verb == "shot":
            vps = VIEWPORTS
            if a.viewports:
                vps = [(f"w{w.strip()}", int(w.strip()), 900)
                       for w in a.viewports.split(",") if w.strip()]
            made = shoot(url, dest, slug, vps, a.wait, not a.no_full_page)
            sheet = contact_sheet(dest, slug, url, made)
            for name, w, h, p in made:
                print(f"  {name:<8} {w:>5}px wide, {h:,}px tall  -> {p}")
            print(f"  -> {sheet}   <- OPEN THIS (all viewports side by side)")
            return

        data = read_styles(url, a.wait)
        md = style_report(url, data, a.top)
        path = os.path.join(dest, f"styles-{slug}.md")
        with open(path, "w", encoding="utf8") as f:
            f.write(md)
        print(f"  {len(data['els']):,} elements measured, "
              f"{len(data['buttons'])} button(s)\n  -> {path}   <- READ THIS")
        return

    # ------------------------------------------------------------------ scrape
    if a.verb == "scrape":
        if not allowed(url, a.ignore_robots):
            sys.exit("robots.txt disallows this URL. --ignore-robots to override.")
        if backend == "firecrawl":
            md, title = fc_scrape(a.server, url)
            rendered = False
        else:
            md, title, _, rendered = local_scrape(url, a.render, a.no_render,
                                                  a.wait, a.timeout)
        if a.stdout:
            print(md)
            return
        os.makedirs(dest, exist_ok=True)
        slug = slugify(url, set())
        path = write_page(dest, slug, url, title, md, label, rendered)
        write_index(dest, url, label, "scrape",
                    [(title, url, len(md), f"pages/{slug}.md")])
        print(f"  {title or '(untitled)'}\n  {len(md):,} chars"
              f"{'  [js-rendered]' if rendered else ''}\n  -> {path}   <- READ THIS")
        return

    # --------------------------------------------------------------------- map
    if a.verb == "map":
        # Filter before the limit, or a site with translated copies of every page
        # (docs.firecrawl.dev has five) spends the whole budget on locales.
        wide = max(a.limit * 20, 500)
        if backend == "firecrawl":
            urls, source = fc_map(a.server, url, wide, a.search), "firecrawl"
        else:
            urls, source = local_map(url, wide, a.search, a.timeout, a.ignore_robots)
        if inc:
            urls = [u for u in urls if any(r.search(u) for r in inc)]
        if exc:
            urls = [u for u in urls if not any(r.search(u) for r in exc)]
        urls = urls[:a.limit]
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "map.txt")
        with open(path, "w", encoding="utf8") as f:
            f.write("\n".join(urls) + "\n")
        print(f"  {len(urls)} URL(s) via {source}\n  -> {path}")
        for u in urls[:20]:
            print(f"     {u}")
        if len(urls) > 20:
            print(f"     ... {len(urls) - 20} more")
        return

    # ------------------------------------------------------------------- crawl
    if backend == "firecrawl":
        pages = fc_crawl(a.server, url, a.limit, a.include, a.exclude, a.depth)
        rows, taken = [], set()
        os.makedirs(dest, exist_ok=True)
        for p in pages:
            meta = p.get("metadata") or {}
            purl = meta.get("sourceURL") or meta.get("url") or url
            md = p.get("markdown") or ""
            slug = slugify(purl, taken)
            write_page(dest, slug, purl, meta.get("title"), md, label, False)
            rows.append((meta.get("title"), purl, len(md), f"pages/{slug}.md"))
    else:
        # Breadth-first from the start URL. Sequential on purpose: this is one
        # laptop hitting someone else's server, and --delay is the whole
        # politeness budget. Sitemap seeds the queue when there is one.
        seeds = sitemap_urls(f"{urlparse(url).scheme}://{urlparse(url).netloc}", a.timeout)
        queue = [(url, 0)] + [(u, 1) for u in seeds if u != url]
        seen, rows, taken = {url}, [], set()
        os.makedirs(dest, exist_ok=True)

        while queue and len(rows) < a.limit:
            u, d = queue.pop(0)
            if d > a.depth:
                continue
            if inc and not any(r.search(u) for r in inc):
                continue
            if any(r.search(u) for r in exc):
                continue
            if not allowed(u, a.ignore_robots):
                print(f"    - robots: {u}", file=sys.stderr)
                continue
            try:
                md, title, html, rendered = local_scrape(u, a.render, a.no_render,
                                                         a.wait, a.timeout)
            except Exception as e:
                print(f"    ! {type(e).__name__}: {u}", file=sys.stderr)
                continue
            slug = slugify(u, taken)
            write_page(dest, slug, u, title, md, label, rendered)
            rows.append((title, u, len(md), f"pages/{slug}.md"))
            print(f"    [{len(rows)}/{a.limit}] {len(md):>6,}ch  {u}", file=sys.stderr)
            if html and d < a.depth:
                for link in harvest_links(html, u):
                    if link not in seen:
                        seen.add(link)
                        queue.append((link, d + 1))
            time.sleep(a.delay)

    idx = write_index(dest, url, label, "crawl", rows)
    total = sum(r[2] for r in rows)
    print(f"  {len(rows)} page(s), {total:,} chars\n  -> {idx}   <- START HERE")


if __name__ == "__main__":
    main()
