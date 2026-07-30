# HS course content pipeline

The pipeline for building the **high school** course. Captured 2026-07-30 from
Shane's description. This is the intended design, not a built system: some pieces
exist, some do not, and the marking below says which.

Supersedes the MS-era pipeline. **LearnWorlds and Google Docs are both out.** They
were migration paths, not sources of truth, and both migrations are finished.

---

## The four sources

Course content is derived only from these. Anything else needs a reason.

| # | Source | Status | Notes |
|---|---|---|---|
| 1 | Excel scope and sequence document | **not built yet** | The spine. Defines what gets taught and in what order. |
| 2 | The MS Creationeering course | exists | Both a content source and the **style exemplar** the QC pass measures against. |
| 3 | Dr. Horstemeyer's paper | exists | Subject-matter source. |
| 4 | Vetted research and sources | case by case | Per-topic, and **references are required**. Not a general licence to search. |

---

## The build sequence

Local work first, platform last. The ordering matters: each stage is cheaper to
fix than the one after it.

1. **Write the text locally** using Claude. Lesson, assignment, or lab.
2. **Check the text** for validity, grade level, grammar, style, and tone. Fix
   before proceeding; text problems get more expensive once they are inside blocks.
3. **Convert to content blocks.**
4. **Generate and place images**, paired to both the block type and the surrounding
   text. Not decoration applied afterward.
5. **QC the whole piece** against the MS course as the example. This is the gate.
6. **Upload to the course on Firebase** once it passes.

The reason the QC gate sits before upload: local iteration exists to work out as
many kinks as possible before anything reaches the platform.

---

## Platform QC is the safety net, not the first line

Things will still slip through, and uploads themselves can fail. **Platform QC
double-checks content once it is on the platform** and confirms it displays
correctly. It catches what local QC could not see, because local QC never sees the
rendered result.

Two distinct jobs, easily confused:

- **Local QC** iterates on content before it exists on the platform.
- **Platform QC** verifies what actually landed, and flags items in the platform
  for a human or an agent to fix.

---

## Where edits happen

- **In the platform:** lessons, assessments, and content edits generally.
- **Locally:** anything in depth, such as a code file. And all pre-upload iteration.

If **Bez** uses the revision agent to rewrite flagged sections, that path stays
needed. Do not retire `scripts/revision_agent.py` on the assumption it is orphaned;
its Google Docs coupling is a thing to change, not a reason to remove it.

---

## Costs that are not waste

The media library, the blocks that import photos, and the crop function all carry
API cost. That is the price of work that cannot be done locally and is not worth
hand-writing into a prompt. Treat these as legitimate spend, not as something to
optimise away. Model choice for each call still follows `references/model-routing.md`.

---

## Status

The pipeline change was expected. It has **not** been built, and building it was
deliberately not the work of 2026-07-30, which was systems upgrades and
housekeeping. This file exists so the design is not re-derived from scratch.

Open before building: the Excel scope and sequence document (source 1) does not
exist yet, and it is the spine the rest hangs from.
