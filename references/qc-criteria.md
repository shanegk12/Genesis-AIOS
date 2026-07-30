# QC criteria

**This file is meant to be edited.** It holds the scoring rubric the `lesson-qc`
agent applies. The agent reads it fresh on every run, so changing a weight or
adding a rule here changes the next QC pass with no code change.

Criteria differ by project and by task type. Add a section rather than bending an
existing one to fit.

---

## How scoring works

Each applicable criterion scores **0, 1, or 2**:

- **2** — meets the bar with nothing to fix.
- **1** — usable but flawed. Worth flagging, not worth blocking.
- **0** — fails. Blocks the pass.

**Pass rule:** an item passes when it scores at least **80% of applicable points**
AND has **no zeros on a criterion marked (blocking)**. A single blocking zero
fails the item regardless of total.

Criteria marked *(context)* are not scored. They are judgment calls where the
right answer depends on the lesson's intent, and a number would be false
precision. Report them as observations for a human.

Skip criteria that do not apply and say so. Do not score a missing category as
zero.

---

## Project: Mousetrap (M-) and Creationeering (C-)

Two separate courses. Never mix IDs or content between them.

### Task type: lesson text

| Criterion | Blocking | What a 2 looks like |
|---|---|---|
| Reading level | yes | Grade 6-8. Every business or engineering term is defined at first use. |
| Cause and effect is explicit | yes | The lesson says *why*, not only *what*. No unexplained jargon. |
| Voice matches `references/voice.md` | no | Warm, professional, short sentences, no em dashes. Faith present, not forced. |
| No truncated content | yes | No block ends mid-sentence. No placeholder text left in. |
| Faith connection is specific | no | A scripture that genuinely fits the engineering concept. Stewardship is not the default. |
| Block limits respected | no | Per `feedback_lesson_rewrite_rules`. No accordion-grid where it is banned. |
| Never says "Junior Creationeers" | yes | Banned phrase. |

### Task type: assessment / question banks

| Criterion | Blocking | What a 2 looks like |
|---|---|---|
| Answerable from the lesson | yes | Nothing requires outside knowledge the lesson never taught. |
| Exactly one defensible answer | yes | For single-select. Distractors are wrong, not merely worse. |
| Distractors are plausible | no | A student who half-read the lesson could pick one. |
| Classified by ID prefix | yes | `C-` vs `M-`, not by inferred course type. |

### Task type: images

Image QC is **context-dependent by design**. Whether an image is right depends on
what the lesson is doing at that moment, so most of this is *(context)*.

| Criterion | Blocking | Notes |
|---|---|---|
| Image exists where the lesson references one | yes | A referenced-but-missing image is a hard fail. |
| Not a broken or expired URL | yes | Fetch it. A 200 on the page is not proof the image loaded. |
| Depicts what the surrounding text describes | *(context)* | Judgment. Report what it shows and what the text claims. |
| Adds something the text does not | *(context)* | Decorative is not automatically wrong. Say which it is. |
| Legible at lesson width | no | Text in the image readable without zooming. |

**Do not add images to the 95 compact labs.** They intentionally have none.

### Task type: interactives

| Criterion | Blocking | What a 2 looks like |
|---|---|---|
| Loads without console errors | yes | Open it. "It rendered" is not "it worked". |
| Self-contained | yes | No external dependencies. |
| The interaction teaches the concept | *(context)* | A widget that moves but teaches nothing scores here, not on load. |
| Works at mobile width | no | |

---

## Project: Private Eats (game)

Different domain entirely. Kept here so the agent has one place to look.

### Task type: gameplay systems

| Criterion | Blocking | What a 2 looks like |
|---|---|---|
| Validated in PIE, not just compiled | yes | A green build is not a working feature. |
| Multiplayer-correct | yes | Verified from both host and client views, not just the host. |
| Tunables in data, not code | no | UPROPERTY defaults, DeveloperSettings INIs, or DataTables. |
| No content referenced by path from C++ | yes | Route through a resolver. |

---

## Adding a project or task type

Copy a table, change the rows, name the section. Two rules:

1. **Mark blocking criteria honestly.** If everything is blocking, nothing is.
2. **Prefer *(context)* over a fake number.** A criterion you cannot score
   consistently is one that should be reported to a human, not averaged into a
   total.
