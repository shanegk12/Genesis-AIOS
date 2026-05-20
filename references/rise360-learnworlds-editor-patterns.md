# Rise 360 & LearnWorlds Editor UI Patterns Reference

*Researched 2026-05-17. Use as reference when building TipTap Properties Panel (Phase 2).*

---

## ARTICULATE RISE 360

### 1. Sidebar / Panel Structure

**Interaction model:** Hover-triggered floating toolbar appears on block hover — not a persistent sidebar.

**Floating toolbar icons (appear top-left of block on hover):**
- **Content** (pencil) — edit block content
- **Style** (palette) — background color and text contrast
- **Format** (protractor) — spacing/padding controls
- Move, duplicate, delete

**Manage Blocks sidebar** (right side, accessed via top icon): list-view for bulk reorder, delete, copy between lessons. Secondary to the floating toolbar.

---

### 2. Properties per Block

**Style icon → background:**
- Presets: Light, Gray, Theme, Theme Tint, Dark, Black, Custom, Image
- Custom: hex code entry
- Text contrast: Auto / Light / Dark (Auto enforces 4.5:1 ratio)
- Image background: overlay (light/dark) + opacity %

**Format icon → spacing:**
- Presets: Small / Medium / Large
- Custom sliders: 0–200px, top + bottom linked by default
- Unlink: chain icon to control top/bottom independently

**Block-type-specific properties:**
- Button: label, color, link type
- Media: size, position
- Interactive: marker colors, behavior settings

---

### 3. Selection & Visual Feedback

- Hover → floating toolbar appears (no persistent selection border)
- No multiple selection
- Right-click context menu: bring forward/back, align, resize, rotate, group, duplicate, delete

---

### 4. Control Categories

| Category | Controls |
|----------|----------|
| Text | Inline formatting (via floating toolbar on text selection); typography at Theme level only |
| Layout | Padding (0–200px, linked or unlinked); block position (move up/down) |
| Effects | Background color (8 presets + custom hex); text contrast; image overlay + opacity |
| Actions | Button destination: external URL, relative URL, email (comma-separated), internal lesson link |

---

### 5. Notable UX Patterns

- **Hover-to-reveal** keeps editor clean — controls only appear when working on a block
- **Linked padding** (top = bottom) is the default; unlink is a clear affordance via chain icon
- **Preset + custom** pattern on spacing and colors — reduces decisions for simple cases
- Accessibility auto-enforced on contrast (Auto setting)

---

### 6. Video Embed

- Media icon → "Embed from Web" → paste URL or embed code
- Uses Embedly (400+ sources: YouTube, Vimeo, etc.)
- Native file uploads up to 5GB (16:9 recommended)
- Properties: forward-seek toggle (disable to require full watch), playback speed (0.25x–2x, can disable), CC, custom thumbnail
- Auto-pause on tab switch: **file uploads only** — embedded web videos do not support it
- Editor shows embedded player with sizing handles; student view adds full controls

---

### 7. CTA / Button Block

- Label text: edit inline or via sidebar
- Color: hex or theme preset; contrast auto-maintained
- Destinations: 4 types (external, relative URL, email, internal lesson)
- Single button or button stack (grid of multiple)
- Hover states: **not supported** (mobile-first design choice)

---

## LEARNWORLDS

### 1. Sidebar / Panel Structure

**Interaction model:** Click widget → right-side sideform panel slides in automatically.

**Panel tabs:**
- **Appearance** — widget-specific options (content, layout variants, icon options)
- **Layout** — box model: padding, margin, border, shadow, background

Additional tabs vary by widget type. Panel collapses when widget is deselected.

**Theme Explorer** (global, separate from per-widget panel):
- Colors, Typography, Buttons, Layout — affect all widgets by default; some per-widget overrides available

---

### 2. Properties per Widget

**Layout tab — Box Model:**
- Padding: per-side (top/right/bottom/left)
- Margin: per-side
- Border: style (Solid / Dashed / Dotted), color, border-radius
- Box shadow: depth + blur
- Background color (available on text, animation, list, image widgets)

**Layout tab — Positioning:**
- Alignment: Left / Center / Right
- Height presets: Small / Normal / Large / Extra Large
- Width presets: Full / Normal / Wide / Narrow

**Appearance tab:**
- Widget-specific options (e.g., tab layout templates for Tabs widget, icon position for icon widgets)
- Visibility toggles

---

### 3. Selection & Visual Feedback

- Click widget → right sideform panel opens
- Click empty space → deselect, panel closes
- Drag handles appear on hover for repositioning
- No right-click menu; no floating toolbar; no bubble menu

---

### 4. Control Categories

| Category | Controls |
|----------|----------|
| Text | Direct inline edit; typography via Theme Explorer (some per-widget overrides) |
| Layout | Padding, margin (per-side); alignment (L/C/R); height + width presets |
| Effects | Background color; border (style, color, radius); box shadow; opacity (limited) |
| Actions | Button: external URL, internal link, email, custom action; link opens same tab or new tab |

---

### 5. Notable UX Patterns

- **Tab-based sidebar** (Appearance / Layout) — groups related controls, reduces cognitive load
- **Section-first architecture** — sections are containers; widgets live inside sections; section properties cascade down
- **Two-level property management** — Theme Explorer for globals, sideform for per-widget overrides
- **Preset + box model** — height/width have named presets but full box model is accessible beneath
- Negative margins discouraged (break responsive layout on narrow screens)

---

### 6. Video Embed

- Sources: YouTube (embed code), Vimeo (account connection + video ID), native uploads, Wistia
- Entry: paste embed code or select from school video library
- **Interactive Video Editor** (Learning Center plan): overlay text/images/quiz questions on timeline
- Native uploads: subtitles, interactive transcript, auto-pause support
- External embeds (Vimeo/Wistia links): no thumbnail, subtitle, or interactive transcript support
- Editor preview shows player with controls; student view shows full player + configured interactive elements

---

### 7. CTA / Button Widget

- Text: edit inline or via properties panel
- Color: theme-linked (Large / Normal / Small size variants) with per-button override
- Full-width toggle: expands button across container
- Icon support: add icon, position (left/right), icon color
- Hover state: color change supported via Actions tab (unlike Rise 360)
- Box model: margin, border, border-radius, background color override
- Link types: external URL, internal link, email, custom action

---

## COMPARISON TABLES

### Selection Model
| | Rise 360 | LearnWorlds |
|---|---|---|
| Trigger | Hover on block | Click widget |
| Panel position | Floating toolbar (left) | Right sidebar |
| Visual feedback | Toolbar appears | Sideform slides in |
| Multiple select | No | No |
| Right-click menu | Yes | No |

### Spacing Controls
| | Rise 360 | LearnWorlds |
|---|---|---|
| Presets | S / M / L | S / Normal / L / XL (height) |
| Custom range | 0–200px slider | Per-side px input |
| Linked sides | Yes (unlink via chain icon) | Per-side independently |

### Video
| | Rise 360 | LearnWorlds |
|---|---|---|
| Entry | "Embed from Web" → paste URL | Paste embed code / library |
| Sources | 400+ (Embedly) | YouTube, Vimeo, native, Wistia |
| Interactive | No (file uploads only) | Yes (Interactive Video Editor, LC+) |
| Auto-pause | File uploads only | Not documented |

### Button / CTA
| | Rise 360 | LearnWorlds |
|---|---|---|
| Color input | Hex or preset | Theme-linked + override |
| Link types | 4 | 4 |
| Hover state | No | Yes (Actions tab) |
| Icon support | No | Yes |

---

## RECOMMENDATIONS FOR TIPTAP PROPERTIES PANEL

### Panel structure
- Use **tab-based right sidebar** (LearnWorlds pattern): Appearance / Layout / Effects / Actions
- **Click to select** widget → panel slides in; click away → closes
- Avoids hover-only paradigm (better touch/keyboard support)

### Spacing controls
- Offer **S / M / L presets** + custom px inputs (steal from both tools)
- **Linked top+bottom** by default with a clear unlink affordance (chain icon, Rise pattern)
- Range: 0–200px covers 99% of use cases

### Color controls
- **8 named presets** (Light, Gray, Theme, Theme Tint, Dark, Black, Custom, Image) + hex input — Rise pattern is cleaner than LW's pure theme-inheritance
- Auto text contrast for accessibility

### Video embed node
- "Embed from Web" URL input → detect YouTube/Vimeo → render iframe
- Expose: playback speed toggle (enable/disable), forward-seek toggle
- Optional: custom thumbnail URL field

### Button / CTA node
- 4 link types: external URL, relative URL, email, internal lesson anchor
- Hex color input + contrast warning
- Hover color option (LearnWorlds does this; Rise skips it — include it)
- Icon support is nice-to-have, not required for v1

### Bubble menu (text selection)
- Rise uses a floating toolbar on text hover — adapt this as a **bubble menu on text selection** in TipTap
- Include: B / I / U / Link / Color — the 80% use case
- Keep it minimal; full controls stay in the Properties Panel

---

*Sources: Articulate support docs, Rise 360 help center, LearnWorlds support articles, Swift eLearning blog. Researched 2026-05-17.*
