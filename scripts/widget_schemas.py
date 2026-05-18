"""
GK12 Platform Widget HTML Schemas

Canonical HTML patterns for every TipTap widget node.
These match the renderHTML() output from each TipTap extension exactly —
so HTML produced from these templates round-trips cleanly through the editor.

Used by: dev_fix_agent.py, reformat_agent.py, and any Gemini prompt that
         needs to produce or validate lesson widget markup.
"""

from typing import Literal

CalloutVariant = Literal["tip", "warning", "info", "success", "biblical"]
ColumnLayout   = Literal["2-col", "left-heavy", "right-heavy", "3-col"]
Spacing        = Literal["sm", "md", "lg"]

_SPACING_CLASS = {"sm": "my-2", "md": "my-4", "lg": "my-8"}
_COLUMN_WIDTHS = {
    "2-col":        ["50%",    "50%"],
    "left-heavy":   ["60%",    "40%"],
    "right-heavy":  ["40%",    "60%"],
    "3-col":        ["33.33%", "33.33%", "33.33%"],
}


# ── Accordion ─────────────────────────────────────────────────────────────────

def accordion(title: str, body_html: str, spacing: Spacing = "md") -> str:
    """
    Collapsible section. body_html should contain block elements (<p>, <ul>, etc.).
    Agent use: good for "deep dive" or "how it works" content under a section.
    """
    sp = _SPACING_CLASS[spacing]
    return (
        f'<details data-accordion="" class="accordion-block {sp}" open="">'
        f'<summary class="accordion-summary">{title}</summary>'
        f'<div class="accordion-body">{body_html}</div>'
        f'</details>'
    )


# ── Tabs ──────────────────────────────────────────────────────────────────────

def tabs(panels: list[dict], spacing: Spacing = "md") -> str:
    """
    Tabbed panels. panels = [{"label": str, "html": str}, ...].
    First panel is active. Minimum 2 panels.
    Agent use: comparing disciplines, showing multiple examples, before/after.
    """
    assert len(panels) >= 2, "Tabs require at least 2 panels"
    items = []
    for i, panel in enumerate(panels):
        active = "true" if i == 0 else "false"
        items.append(
            f'<div data-tab-panel="{panel["label"]}" '
            f'data-tab-active="{active}" class="tab-panel-block">'
            f'{panel["html"]}'
            f'</div>'
        )
    return (
        f'<div data-tabs="" class="tab-group-block">'
        + ''.join(items)
        + '</div>'
    )


# ── Columns ───────────────────────────────────────────────────────────────────

def columns(col_html_list: list[str], layout: ColumnLayout = "2-col") -> str:
    """
    Side-by-side column layout. col_html_list must match column count for layout.
    Agent use: term+definition, formula+explanation, image+caption.
    """
    widths = _COLUMN_WIDTHS[layout]
    assert len(col_html_list) == len(widths), (
        f"Layout {layout} needs {len(widths)} columns, got {len(col_html_list)}"
    )
    col_divs = ''.join(
        f'<div data-column="" class="column-block" style="flex: 1 1 {w}; min-width: 0;">'
        f'{html}</div>'
        for w, html in zip(widths, col_html_list)
    )
    return (
        f'<div data-columns="{layout}" class="columns-block columns-{layout}">'
        + col_divs
        + '</div>'
    )


# ── Callout ───────────────────────────────────────────────────────────────────

_CALLOUT_STYLE = (
    "border-left: 4px solid; padding: 8px 16px 12px; "
    "margin: 16px 0; border-radius: 0 6px 6px 0;"
)

def callout(variant: CalloutVariant, body_html: str) -> str:
    """
    Highlighted callout block. body_html should be <p> elements.
    Variants: tip (blue), warning (amber), info (gray), success (green),
              biblical (navy) — use biblical for scripture/faith content.
    Agent use: key points, warnings, faith connections, vocab highlights.
    """
    return (
        f'<div data-callout="{variant}" '
        f'class="callout-block callout-{variant}" style="{_CALLOUT_STYLE}">'
        f'{body_html}'
        f'</div>'
    )


# ── Carousel ──────────────────────────────────────────────────────────────────

def carousel(slides: list[dict]) -> str:
    """
    Image carousel. slides = [{"src": str, "caption": str}, ...].
    Agent use: step-by-step visual sequences, multiple related images.
    When no real src is available use IMAGE_NEEDED placeholder.
    """
    slide_html = ''.join(
        f'<figure class="carousel-slide">'
        f'<img src="{s["src"]}" alt="{s["caption"]}" class="carousel-img">'
        f'<figcaption class="carousel-caption">{s["caption"]}</figcaption>'
        f'</figure>'
        for s in slides
    )
    return (
        f'<div data-carousel="" class="carousel-block">'
        f'<div class="carousel-track">{slide_html}</div>'
        f'</div>'
    )


# ── Image placeholder ─────────────────────────────────────────────────────────

def image_needed(description: str) -> str:
    """
    Placeholder paragraph inserted when an image is required but not yet sourced.
    The image pipeline reads these and fills in real URLs.
    description: 1 sentence describing what the image should show.
    """
    return f'<p><em>[IMAGE NEEDED: {description}]</em></p>'


# ── Prompt snippet ────────────────────────────────────────────────────────────

WIDGET_REFERENCE = """
## Available widgets — use these HTML patterns exactly

### Accordion (collapsible section)
<details data-accordion="" class="accordion-block my-4" open="">
  <summary class="accordion-summary">Section Title</summary>
  <div class="accordion-body">
    <p>Body paragraph...</p>
  </div>
</details>

### Tabs (2+ panels)
<div data-tabs="" class="tab-group-block">
  <div data-tab-panel="Tab 1" data-tab-active="true" class="tab-panel-block">
    <p>Content for tab 1...</p>
  </div>
  <div data-tab-panel="Tab 2" data-tab-active="false" class="tab-panel-block">
    <p>Content for tab 2...</p>
  </div>
</div>

### Columns — 2-col (50/50)
<div data-columns="2-col" class="columns-block columns-2-col">
  <div data-column="" class="column-block" style="flex: 1 1 50%; min-width: 0;">
    <p>Left column content...</p>
  </div>
  <div data-column="" class="column-block" style="flex: 1 1 50%; min-width: 0;">
    <p>Right column content...</p>
  </div>
</div>

### Columns — left-heavy (60/40), right-heavy (40/60), 3-col (33/33/33)
Replace data-columns="2-col" and class suffix, adjust flex values accordingly.

### Callout (tip | warning | info | success | biblical)
<div data-callout="tip" class="callout-block callout-tip" style="border-left: 4px solid; padding: 8px 16px 12px; margin: 16px 0; border-radius: 0 6px 6px 0;">
  <p>Callout text...</p>
</div>

### Image placeholder (when no real image URL is available)
<p><em>[IMAGE NEEDED: one sentence describing what the image should show]</em></p>

### Image carousel
<div data-carousel="" class="carousel-block">
  <div class="carousel-track">
    <figure class="carousel-slide">
      <img src="URL_OR_PLACEHOLDER" alt="Caption" class="carousel-img">
      <figcaption class="carousel-caption">Caption</figcaption>
    </figure>
  </div>
</div>

## Rules for widget use
- Use tabs to compare 2-4 related topics (engineering disciplines, before/after, examples)
- Use accordions for "deeper dive" content, definitions, or optional reading
- Use columns for term+definition, formula+explanation, or image+caption pairs
- Use callout "biblical" only for scripture or explicit faith connections
- Every tab panel and accordion with >2 paragraphs needs an image or [IMAGE NEEDED]
- Headings inside widgets: use <strong> or <h4>, not <h2>/<h3>
"""


# ── Quick helpers for agent use ───────────────────────────────────────────────

def wrap_in_tabs_from_list(items: list[dict]) -> str:
    """
    Convenience: build tabs from list of {label, paragraphs: [str], image_src?: str}.
    """
    panels = []
    for item in items:
        paras = ''.join(f'<p>{p}</p>' for p in item['paragraphs'])
        if item.get('image_src'):
            paras += f'<img src="{item["image_src"]}" alt="{item["label"]}">'
        elif len(item['paragraphs']) > 2:
            paras += image_needed(f'{item["label"]} visual example')
        panels.append({'label': item['label'], 'html': paras})
    return tabs(panels)


def wrap_vocabulary(terms: list[dict]) -> str:
    """
    Build a 2-column vocabulary grid from list of {term, definition}.
    Two terms per row using nested columns.
    """
    rows = []
    for i in range(0, len(terms), 2):
        pair = terms[i:i+2]
        cols = []
        for t in pair:
            cols.append(f'<p><strong>{t["term"]}</strong><br>{t["definition"]}</p>')
        if len(cols) == 1:
            cols.append('<p></p>')
        rows.append(columns(cols, "2-col"))
    return ''.join(rows)
