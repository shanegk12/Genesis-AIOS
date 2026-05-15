# Tomorrow's Plan — 2026-05-14

Three blocks. Content in the morning, AIOS wiring midday, automations in the afternoon.

---

## Block 1 — Morning: Content

**Goal:** Make real progress on the mid-June deadline.

1. **Pull the MSENG 1 Drive folder** — map what modules exist vs. what's missing. Get a clear picture of where modules 4-8 stand before writing anything.
2. **Draft one Creationeering module using the new prompt template** — run the improved Gemini prompt (`references/lesson-prompt-template.md`) on the next module in sequence. Compare output quality to previous drafts. Iterate the prompt if needed.
3. **Build course outline — modules 4-9** — open the LearnWorlds builder and the Google Doc side by side. Block each module with objectives, constraints, materials list. No full drafts yet — just the skeleton so drafting has a target.

---

## Block 2 — Midday: AIOS Leveling Up

**Goal:** Make gws reliable and get Google Tasks wired to your iPhone.

1. **Fix the gws JSON param issue** — write a small Python helper script (`scripts/gws_query.py`) that accepts a service/command/params and handles the quoting cleanly. This makes every future Drive/Gmail/Calendar query one line.
2. **Wire Google Tasks → iPhone Reminders (free, zero setup)**
   - On your iPhone: Settings → Mail → Accounts → Add Account → Google → sign in with `shane@gk12academy.com` → enable Reminders
   - Tasks you create in Google Tasks (or that I create via `gws tasks`) will appear in your iPhone Reminders app with native notifications
3. **Install ntfy on your iPhone** — free push notification app. I can send alerts to your phone via a simple script call. No account required.
   - Download **ntfy** from the App Store
   - Subscribe to a private topic (we'll name it `genesis-aios-shane`)
   - I'll build a `scripts/notify.py` that sends to that topic

---

## Block 3 — Afternoon: Automations

**Goal:** Ship two automations that save time this week.

### Automation 1 — Monday Morning Briefing
Every Monday, I pull your week from Google Calendar + open Tasks and send a 3-bullet priority brief to your phone via ntfy. Covers: what's on the calendar, what tasks are due, and one reminder of your top 90-day priority.

### Automation 2 — Lesson Draft Pipeline
Instead of copy-pasting the prompt into Gemini, a script takes a module number + topic + previous lesson topic and outputs a ready-to-paste Gemini prompt with all fields pre-filled from the template. Saves ~5 minutes per module, eliminates missed fields.

---

## What you'll need ready

- iPhone nearby for the Reminders + ntfy setup (10 min)
- LearnWorlds open for the build course outline block
- The Google Doc where Gemini drafts live — share the link so I can read it directly via gws

---

## Success by end of day

- [ ] Modules 4-9 build course skeleton done
- [ ] One Creationeering module drafted via improved prompt
- [ ] Google Tasks syncing to iPhone Reminders
- [ ] ntfy installed, genesis-aios-shane topic live
- [ ] Monday briefing automation scripted
- [ ] Lesson draft pipeline script working
