# GK12 Academy — Image Style Guide for AI-Generated Lesson Images

Used by `media_agent.py` when writing image prompts and by `image_agent.py` when calling Imagen 4.

---

## Brand Identity

**Logo mark:** A navy blue gear/cog wheel containing a gold circle. Inside the circle: a gold Latin cross (faith) above an open gold book (knowledge). The wordmark reads "Genesis" in large serif type and "K-12 Academy" below a gold horizontal rule — all in deep navy.

**Logo file:** `references/gk12-logo.png` (primary, white background)

**Colorways:**
- Primary: Navy gear + navy serif text + gold cross/book/rule, white background
- Secondary: White gear + white serif text + gold cross/book, navy background

---

## Brand Colors (exact)

| Name          | Hex       | Use                          |
|---------------|-----------|------------------------------|
| GK12 Navy     | `#1B2A5C` | Primary text, gear, icons    |
| GK12 Gold     | `#C9A84C` | Cross, book, rule, accents   |
| White         | `#FFFFFF`  | Background (primary)         |
| Light Gray    | `#F5F5F5`  | Secondary background         |

---

## Visual Identity

**Style:** Clean educational illustration. Think technical textbook meets modern explainer graphic — precise but not cold. Every image should look like it belongs in a well-produced middle school STEM course.

**Color palette:** Anchored to GK12 brand.
- Primary: GK12 Navy (`#1B2A5C`) and GK12 Gold (`#C9A84C`) on white
- Accent: Light blues, warm grays for supporting elements
- Avoid: Neon, pastels, muddy browns, oversaturated colors, orange (not on-brand)

**Line quality:** Clear outlines on diagram elements. No hand-drawn/sketchy style. Flat illustration with subtle depth (no heavy drop shadows or gradients).

**Typography in images:** Minimal. Labels only where necessary. Clean sans-serif font.

---

## Subject Matter Rules

**Engineering concepts:**
- Show real processes, not metaphors. If the lesson is about force diagrams, draw the actual force diagram.
- Include scale references when helpful (ruler, human hand, familiar object)
- Technical labels are encouraged for diagrams
- Show cause-and-effect relationships visually when possible

**Multiscale Modeling:**
- When illustrating a multiscale connection, show both scales side by side (macro view + zoomed atomic/micro view) with a clear visual bridge between them

**Faith integration in imagery:**
- Never use religious symbols (crosses, doves, etc.) unless the lesson explicitly calls for it
- Faith presence should be thematic, not iconographic — a sense of design, order, and beauty in creation
- Natural imagery (light, water, materials) can carry this tone without being heavy-handed

---

## Audience

- Middle schoolers, ages 11-14
- Homeschool context — images may be viewed at home on a laptop or tablet
- No depictions of violence, danger, or inappropriate content
- If people appear, use diverse, age-appropriate figures in engineering/classroom contexts

---

## Technical Specifications

- Aspect ratio: 16:9
- Style suffix to append to every prompt: `educational illustration, clean lines, Genesis K-12 Academy navy (#1B2A5C) and gold (#C9A84C) color palette, white background, middle school curriculum, engineering textbook style, bright and professional`
- Do NOT use: photorealistic, hyper-detailed, dark moody backgrounds, fantasy elements, anime style, orange (off-brand)

---

## Prompt Template

Prepend this to every image prompt before sending to Imagen:

```
Educational illustration for Genesis K-12 Academy's middle school engineering curriculum. Clean technical style, color palette of deep navy blue (#1B2A5C) and warm gold (#C9A84C) on white background, professional and engaging, appropriate for ages 11-14. No text in image. 16:9 composition. [YOUR PROMPT HERE]
```
