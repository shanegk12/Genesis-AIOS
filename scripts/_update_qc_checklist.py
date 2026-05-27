"""Replace QC Checklist Google Doc with updated admin checklist."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _gws_auth import get_credentials
from googleapiclient.discovery import build

DOC_ID = "1rJFoXjirhNHTJDrOhU1C-gt3DV4q_Gbpgo9IJcZeOgM"

creds = get_credentials()
docs = build("docs", "v1", credentials=creds)

# ── Read current doc to get end index ─────────────────────────────────────────
doc = docs.documents().get(documentId=DOC_ID).execute()
body = doc.get("body", {})
content = body.get("content", [])
end_index = content[-1]["endIndex"] - 1 if content else 1

# ── Clear existing content ─────────────────────────────────────────────────────
requests = []
if end_index > 1:
    requests.append({
        "deleteContentRange": {
            "range": {"startIndex": 1, "endIndex": end_index}
        }
    })

# ── Build new content ──────────────────────────────────────────────────────────
lines = [
    ("GENESIS K-12 ACADEMY — LESSON QC CHECKLIST", "TITLE"),
    ("For use by QC admins reviewing lessons before publication. Work through each section in order. Mark Pass / Fail / Fix Needed next to each item.", "SUBTITLE"),

    ("", "NORMAL"),
    ("SECTION 1: AI WRITER COMMON BUGS", "HEADING_1"),

    ("", "NORMAL"),
    ("1.1  Vocabulary / Word Wall", "HEADING_2"),
    ("☐  All vocab terms are bolded the first time they appear in the lesson body", "NORMAL"),
    ("☐  Word wall block is present and uses the bordered-note block type (not a plain paragraph)", "NORMAL"),
    ("☐  Vocab terms in the word wall match exactly what is bolded in the body text", "NORMAL"),
    ("☐  No duplicate vocab entries across the same lesson", "NORMAL"),
    ("☐  Flashcard interactive (if present) matches the word wall terms", "NORMAL"),

    ("", "NORMAL"),
    ("1.2  Block Structure", "HEADING_2"),
    ("☐  No raw Markdown inside an HTML block (look for ** ** or ## headings inside a single content block)", "NORMAL"),
    ("☐  Tabs use the interactive-tabs block type with button navigation, not the old accordion block", "NORMAL"),
    ("☐  Accordion blocks have been converted or flagged for conversion", "NORMAL"),
    ("☐  Headings are split into their own blocks — no heading text fused into a paragraph block", "NORMAL"),
    ("☐  No wall-of-text paragraphs over ~150 words — AI tends to dump content into single blocks", "NORMAL"),
    ("☐  Numbered or bulleted lists use list blocks, not hand-typed 1. 2. 3. in a paragraph", "NORMAL"),

    ("", "NORMAL"),
    ("1.3  Content Quality", "HEADING_2"),
    ("☐  No filler phrases: 'In this lesson we will...', 'As we have learned...', 'It is important to note...'", "NORMAL"),
    ("☐  No hallucinated facts — double-check any specific numbers, dates, or citations", "NORMAL"),
    ("☐  Cause-and-effect is concrete and accurate (no vague 'this causes that' without explanation)", "NORMAL"),
    ("☐  Reading level is appropriate for middle school (Grade 6–8 range)", "NORMAL"),
    ("☐  No unexplained jargon — every technical term is defined the first time it appears", "NORMAL"),
    ("☐  Lesson length is consistent with module peers (not drastically shorter or longer)", "NORMAL"),

    ("", "NORMAL"),
    ("1.4  Locked Content", "HEADING_2"),
    ("☐  If the lesson has been manually edited post-import, confirm contentSource is set to 'manual' in Firestore to prevent pipeline overwrites", "NORMAL"),

    ("", "NORMAL"),
    ("SECTION 2: BRANDING CHECKLIST", "HEADING_1"),

    ("", "NORMAL"),
    ("2.1  Trademarks and Names", "HEADING_2"),
    ("☐  'Creationeering™' — trademark symbol present on first use per lesson", "NORMAL"),
    ("☐  'Mousetrap Car Build' — no shortening to just 'kit' or 'mousetrap car' without the full name on first use", "NORMAL"),
    ("☐  'Created to Create™' — tagline spelled correctly if used", "NORMAL"),
    ("☐  'Genesis K-12 Academy' — no abbreviations (GK12, Genesis Academy, etc.) in student-facing text", "NORMAL"),

    ("", "NORMAL"),
    ("2.2  Voice and Tone", "HEADING_2"),
    ("☐  Short sentences — no run-ons", "NORMAL"),
    ("☐  No em dashes (—) — replace with a comma, period, or rewrite the sentence", "NORMAL"),
    ("☐  Bullet points used in place of long explanatory paragraphs where appropriate", "NORMAL"),
    ("☐  Warm but professional tone — not overly casual, not dry or academic", "NORMAL"),
    ("☐  Faith is present but not forced — it reads naturally, not like a tag-on devotional", "NORMAL"),
    ("☐  No first-person 'I' or 'we' referring to the AI writer — rewrite as passive or third-person", "NORMAL"),

    ("", "NORMAL"),
    ("2.3  Contact and URL References", "HEADING_2"),
    ("☐  Any email references use team@gk12academy.com", "NORMAL"),
    ("☐  Any platform URL references use modularity.gk12academy.com", "NORMAL"),

    ("", "NORMAL"),
    ("SECTION 3: CONTENT AND MEDIA ALIGNMENT", "HEADING_1"),

    ("", "NORMAL"),
    ("3.1  Images", "HEADING_2"),
    ("☐  Every lesson has at least one image (no lessons ship without media)", "NORMAL"),
    ("☐  Image matches the lesson topic — not generic stock that could belong to any lesson", "NORMAL"),
    ("☐  If the image has a text overlay, the overlay text does not duplicate or contradict the lesson body text", "NORMAL"),
    ("☐  Placeholder images (grey boxes) have been replaced before the lesson goes live", "NORMAL"),
    ("☐  Image quality is sufficient — not blurry, pixelated, or oddly cropped", "NORMAL"),
    ("☐  Images of physical objects (mousetrap car, materials) match the actual kit components", "NORMAL"),

    ("", "NORMAL"),
    ("3.2  Interactives", "HEADING_2"),
    ("☐  Interactive block (if present) matches the core concept being taught in that lesson", "NORMAL"),
    ("☐  Flashcard set covers the same vocabulary as the word wall — no extra or missing terms", "NORMAL"),
    ("☐  Quiz questions align with the stated learning objectives for the lesson", "NORMAL"),
    ("☐  Interactive tabs organize content logically — labels are clear and not redundant", "NORMAL"),
    ("☐  No broken or blank interactives — if the embed fails, flag for re-upload", "NORMAL"),

    ("", "NORMAL"),
    ("3.3  Faith Integration", "HEADING_2"),
    ("☐  Each lesson includes at least one faith connection — a Scripture reference, a reflection prompt, or a 'Created to Create' principle", "NORMAL"),
    ("☐  Faith connection is tied to the engineering concept, not dropped in as a standalone paragraph", "NORMAL"),
    ("☐  Theological accuracy — no speculative or non-orthodox statements", "NORMAL"),

    ("", "NORMAL"),
    ("3.4  Module Alignment", "HEADING_2"),
    ("☐  Lesson ID matches the correct module (C-001 through C-159 for Creationeering; M- for Mousetrap Build)", "NORMAL"),
    ("☐  Lesson topic fits the module theme — check the module overview if unsure", "NORMAL"),
    ("☐  Progression makes sense — lesson builds on the previous lesson's concepts", "NORMAL"),
    ("☐  No content overlap with adjacent lessons in the same module", "NORMAL"),

    ("", "NORMAL"),
    ("SECTION 4: FINAL SIGN-OFF", "HEADING_1"),

    ("", "NORMAL"),
    ("☐  All Section 1–3 items pass (or flagged issues logged in the QC report)", "NORMAL"),
    ("☐  Lesson status updated to 'reviewed' in the QC tracker", "NORMAL"),
    ("☐  Any flagged lessons handed off to the content team with specific notes", "NORMAL"),
    ("", "NORMAL"),
    ("Reviewed by: ___________________________     Date: _______________", "NORMAL"),
    ("Lesson ID(s): ___________________________", "NORMAL"),
]

# ── Insert text requests ───────────────────────────────────────────────────────
insert_requests = []
insert_text = ""
for text, style in lines:
    insert_text += text + "\n"

insert_requests.append({
    "insertText": {
        "location": {"index": 1},
        "text": insert_text,
    }
})

# First clear, then insert
if requests:
    docs.documents().batchUpdate(
        documentId=DOC_ID,
        body={"requests": requests}
    ).execute()

docs.documents().batchUpdate(
    documentId=DOC_ID,
    body={"requests": insert_requests}
).execute()

# ── Apply heading styles ───────────────────────────────────────────────────────
# Re-fetch to get accurate indices
doc = docs.documents().get(documentId=DOC_ID).execute()
doc_content = doc.get("body", {}).get("content", [])

style_requests = []
current_index = 1
for text, style in lines:
    length = len(text) + 1  # +1 for newline
    if style != "NORMAL" and text:
        named_style = style  # TITLE, SUBTITLE, HEADING_1, HEADING_2
        style_requests.append({
            "updateParagraphStyle": {
                "range": {
                    "startIndex": current_index,
                    "endIndex": current_index + length,
                },
                "paragraphStyle": {"namedStyleType": named_style},
                "fields": "namedStyleType",
            }
        })
    current_index += length

if style_requests:
    docs.documents().batchUpdate(
        documentId=DOC_ID,
        body={"requests": style_requests}
    ).execute()

print("Done. QC Checklist updated.")
print(f"https://docs.google.com/document/d/{DOC_ID}/edit")
