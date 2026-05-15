"""
Genesis K-12 Media Agent

Reads a lesson draft and generates one image prompt per major section.
Prompts are written to scripts/media_prompts.json, keyed by lesson ID.
Use the prompts with Midjourney, DALL-E, or any image generator.

Usage (standalone):
  python media_agent.py --draft-file path/to/draft.txt --lesson-id C-030 --topic "What is Procurement?" --doc creationeering
"""

import argparse, json, os, sys, urllib.request, urllib.error

MANIFEST_PATH      = os.path.join(os.path.dirname(__file__), "lessons_manifest.json")
MEDIA_PROMPTS_PATH = os.path.join(os.path.dirname(__file__), "media_prompts.json")
STYLE_GUIDE_PATH   = os.path.join(os.path.dirname(__file__), "..", "references", "image-style-guide.md")

GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

MEDIA_PROMPT = """You are generating image prompts for a middle school engineering curriculum published by Genesis K-12 Academy. For this lesson draft, create educational illustration prompts — one for the lesson cover and one per major content section (Part 1, Part 2, etc.).

Requirements for each prompt:
- 60-90 words
- Describes a specific illustration, diagram, or realistic photo
- Age-appropriate for 6th-8th grade
- Visually represents the key engineering concept of that section
- Avoids abstract or symbolic imagery — be concrete and descriptive
- Style: clean educational illustration, bright colors, technical but accessible

LESSON TOPIC: {topic}
COURSE: {course}

DRAFT (first 5000 chars):
{draft}

Return ONLY a JSON array — no markdown, no other text. Each object must have exactly these fields:
[
  {{"section": "Cover", "concept": "one-phrase concept", "prompt": "image prompt here", "aspectRatio": "16:9"}},
  {{"section": "Part 1: [title]", "concept": "one-phrase concept", "prompt": "image prompt here", "aspectRatio": "16:9"}},
  ...
]

For aspectRatio: choose "16:9" for wide diagrams, multi-element infographics, process flows, and most content images (default). Choose "1:1" only for cover images with a single central focal point or portrait-style close-ups."""


def load_env():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def call_gemini(api_key, prompt):
    import re
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 2048}
    }).encode("utf-8")

    url = f"{GEMINI_URL}?key={api_key}"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data["candidates"][0]["content"].get("parts", [])
        text_parts = [p["text"] for p in parts if not p.get("thought", False) and "text" in p]
        text = "\n".join(text_parts).strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # Find first JSON array in case thinking text precedes it
        start = text.find("[")
        if start > 0:
            text = text[start:]
        return json.loads(text)
    except Exception as e:
        print(f"Media agent Gemini error: {e}")
        return None


def load_media_prompts():
    if os.path.exists(MEDIA_PROMPTS_PATH):
        with open(MEDIA_PROMPTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_media_prompts(data):
    with open(MEDIA_PROMPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_style_prefix():
    """Read the image style guide and extract the prompt prefix."""
    if not os.path.exists(STYLE_GUIDE_PATH):
        return "Educational illustration for a middle school engineering curriculum. Clean technical style, navy blue and orange color palette, bright and engaging, appropriate for ages 11-14. No text in image. 16:9 composition."
    with open(STYLE_GUIDE_PATH, encoding="utf-8") as f:
        content = f.read()
    # Extract the prompt template block
    import re
    match = re.search(r"```\n(Educational illustration.*?)\n```", content, re.DOTALL)
    if match:
        return match.group(1).replace("[YOUR PROMPT HERE]", "").strip()
    return "Educational illustration, clean technical style, navy blue and orange, middle school curriculum, 16:9."


def run_media(draft_text, lesson_id, topic, doc, api_key):
    course_label = "Creationeering" if doc == "creationeering" else "Mousetrap Build"
    style_prefix = load_style_prefix()
    prompt = MEDIA_PROMPT.format(
        topic=topic,
        course=course_label,
        draft=draft_text[:5000]
    )
    # Append style instructions so Gemini writes prompts that include the style spec
    prompt += f"\n\nIMPORTANT: Begin every prompt in your JSON output with this exact prefix:\n\"{style_prefix}\""

    prompts = call_gemini(api_key, prompt)
    if not prompts:
        print(f"  Media: failed to generate prompts for {lesson_id}")
        return False

    media_data = load_media_prompts()
    media_data[lesson_id] = {
        "topic":   topic,
        "doc":     doc,
        "prompts": prompts
    }
    save_media_prompts(media_data)
    print(f"  Media: {len(prompts)} image prompts saved for {lesson_id}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Genesis K-12 Media Agent")
    parser.add_argument("--draft-file",  required=True, help="Path to draft text file")
    parser.add_argument("--lesson-id",   required=True, help="Lesson ID (e.g. C-030)")
    parser.add_argument("--topic",       required=True, help="Lesson topic")
    parser.add_argument("--doc",         required=True, choices=["creationeering", "mousetrap"])
    args = parser.parse_args()

    if not os.path.exists(args.draft_file):
        print(f"Draft file not found: {args.draft_file}")
        sys.exit(1)

    with open(args.draft_file, encoding="utf-8") as f:
        draft_text = f.read()

    env = load_env()
    api_key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found")
        sys.exit(1)

    print(f"Media: [{args.lesson_id}] {args.topic}")
    success = run_media(draft_text, args.lesson_id, args.topic, args.doc, api_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
