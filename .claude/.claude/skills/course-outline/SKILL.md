---
name: course-outline
description: Use when Shane asks to outline a course module, build the course skeleton, check completion status, or generate a timeline. Trigger on "outline the course", "what modules are left", "course timeline", "build the skeleton", or "what's left to write". Works for both the Creationeering course (89 lessons, 9 modules) and the Mousetrap Build course (24 lessons).
---

## What this skill does

Two outputs, one run:

1. **Module Skeleton** — for each requested module, generates a structured block: learning objectives, constraints, materials list, and lesson titles. Ready to hand to Gemini or use as a drafting target.
2. **Completion Timeline** — a tracking grid showing every lesson, its module, target draft date, and status (Done / In Progress / Empty). Anchored to the July launch and mid-June checkpoint.

Run it once to get oriented. Re-run any time after drafting sessions to update the tracker.

---

## Inputs this skill reads

- Memory: `project_genesis_k12_priorities.md` — course status, drive IDs, deadlines
- `context/priorities.md` — launch dates and milestones
- `.env` — Google Doc IDs for live status (optional, if re-checking Drive)

**Key facts (pre-loaded from 2026-05-14 audit):**

### Creationeering Course — 89 lessons, 9 modules, 18 weeks (2 weeks per module)

| Module | Name | Tabs | Status |
|---|---|---|---|
| 1 | Thinking | 1-9 | Done |
| 2 | Design | 10-17 | Done |
| 3 | Analysis & Synthesis | 18-29 | Partial (tab 25 empty) |
| 4 | Procurement | 30-35 | Empty |
| 5 | Fabrication | 36-39 | Empty |
| 6 | Logistics | 40-49 | Empty |
| 7 | Assembly | 50-59 | Empty |
| 8 | Performance | 60-69 | Empty |
| 9 | Decommissioning | 70-89 | Empty |

Gap: 62 lessons (tab 25 + all of modules 4-9)

### Mousetrap Build Course — 24 lessons

Gap: 3 lessons (tabs 7, 8, 17 — Digital Measurement, The Arduino, Analysis Activity: Calculations and Efficiency)

### Deadlines
- Mid-June checkpoint: ~2026-06-15 — Build course drafted + 8 Creationeering modules done
- Full launch: July 2026 (Tennessee event) — all 89 + 24 lessons complete

---

## Execution

### Step 1: Clarify scope

Ask Shane:
1. Which course? (Creationeering / Mousetrap / Both)
2. Which modules to outline? (default: all empty/partial ones)
3. Does he want the full timeline sheet, or just the module skeleton?

If he says "all" or "let's go" without specifics — default to Creationeering modules 3-9 + Mousetrap gaps, and generate both outputs.

### Step 2: Generate Module Skeletons

For each requested module, print a structured block:

```
## Module [N] — [Name]
**Weeks:** [X–Y] of 18
**Lesson count:** [N]
**Status:** Empty / Partial

### Learning Objectives
By the end of this module, students will be able to:
- [Objective 1 — concrete, measurable, middle-school level]
- [Objective 2]
- [Objective 3]

### Constraints
- **Audience:** Middle school (grades 6-8), homeschool setting
- **Session length:** ~45-60 min per lesson
- **Lab tie-in:** [How this module connects to Little Moe / Mark 1 / Mark 2 / no lab]
- **Faith integration:** [One-line faith angle relevant to this module's theme]

### Materials / Resources Needed
- [Material or resource 1]
- [Material or resource 2]
- (list only what's non-obvious — standard paper/pencil not needed)

### Lessons in This Module
| # | Title | Status |
|---|---|---|
| [tab #] | [Lesson title from the doc] | Empty / Done |
```

Objectives and faith integration should be specific to the module topic — not generic. Use the Nine Pillars of Creationeering as the conceptual backbone:
- Thinking: curiosity, systems awareness, foundational frameworks
- Design: intentional form, function, aesthetics — God as the ultimate Designer
- Analysis & Synthesis: data, measurement, making sense of observations
- Procurement: stewardship, wise resource selection, cost-consciousness
- Fabrication: craft, precision, materials as God's provision
- Logistics: planning, time stewardship, sequencing
- Assembly: integration, teamwork (Ecclesiastes 4:9-10), fitting parts into wholes
- Performance: validation, iteration, honoring commitments
- Decommissioning: stewardship of end-of-life, environmental responsibility, cradle-to-cradle

### Step 3: Generate Completion Timeline

Print a timeline anchored to today's date and the July launch.

**Header block:**
```
## Course Completion Timeline
Today: [date]
Mid-June checkpoint: 2026-06-15 (~[N] weeks away)
July launch: 2026-07-[TBD] (~[N] weeks away)
Lessons remaining: [N] of 89 (Creationeering) + [N] of 24 (Mousetrap)
Required pace: ~[N] lessons/week to hit July launch
```

**Per-module timeline (Creationeering):**

| Module | Name | Lessons | Target Draft By | Status |
|---|---|---|---|---|
| 1 | Thinking | 9 | Done | Done |
| 2 | Design | 8 | Done | Done |
| 3 | Analysis & Synthesis | 12 | 2026-06-01 | 11 done, 1 empty |
| 4 | Procurement | 6 | 2026-06-08 | Empty |
| 5 | Fabrication | 4 | 2026-06-15 | Empty |
| 6 | Logistics | 10 | 2026-06-22 | Empty |
| 7 | Assembly | 10 | 2026-06-29 | Empty |
| 8 | Performance | 10 | 2026-07-06 | Empty |
| 9 | Decommissioning | 20 | 2026-07-13 | Empty |

Space modules evenly across available weeks. If the pace is unsustainable (>10 lessons/week), flag it plainly and suggest: focus the mid-June checkpoint on modules 3-5 first, then 6-9 in late June / early July.

**Mousetrap gaps:**
| Tab | Title | Target Draft By | Status |
|---|---|---|---|
| 7 | Digital Measurement | 2026-06-01 | Empty |
| 8 | The Arduino | 2026-06-01 | Empty |
| 17 | Analysis Activity: Calculations and Efficiency | 2026-06-08 | Empty |

### Step 4: Save to file

After printing both outputs, ask:
> "Save this to `context/course-outline-[date].md` so you have a reference for drafting sessions?"

If yes, write the full output to that file. This becomes the working doc Shane can open alongside the Lesson Book.

---

## Critical implementation rules

1. **Module skeletons must be specific.** Generic objectives ("students will understand procurement") are not acceptable. Each objective should name a concrete skill or deliverable tied to the module's topic.
2. **Faith integration is one line per module — woven in, not bolted on.** Do not add a separate "faith section" to each objective. One connector in the Constraints block is enough.
3. **Lesson titles come from the actual doc tab list** — do not invent titles. If a tab title is ambiguous, list it as-is.
4. **Pace math must be honest.** If 65 lessons in 7 weeks = 9.3 lessons/week, say that. Don't soften it.
5. **Timeline dates are targets, not commitments.** Label them "Target Draft By," not "Due."
6. **Only write `context/course-outline-[date].md` if Shane confirms.** No silent writes.
7. **Re-run is idempotent.** If Shane runs this again after drafting some lessons, update the status column from Drive data if he asks — otherwise use memory.
