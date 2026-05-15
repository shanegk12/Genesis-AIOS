# AIS-OS Intake

This is the source-of-truth file for your AIOS. Fill it in by typing, voice-pasting (Wispr Flow / OS dictation), or running `/onboard` for a guided conversation. Whichever mode, this file is what `/onboard` reads to scaffold your Day-1 setup.

**Hard cap: 7 questions.** Each answerable in under 60 seconds. Don't overthink — you can edit and re-run `/onboard` any time.

---

## Q1 — Who are you, what do you sell, who do you sell it to?

Identity, offer, ICP. One paragraph each is fine.

```
My name is Shane Reynolds, I am a recent Liberty University School of Civil Engineering Alumnis. I currently am a partner in a K-12 Grade Homeschool Engineering Education company. I write the curriculum, build the labs, and manage the day to day operations within the company. In my free time, I coach men's lacrosse at Auburn University and help my brother with his handyman company.

My K-12 Company is called Genesis K-12 Academy. We offer a hands-on, faith based engineering education with a split Creationeering and build courses. Creationeering is the paradigm that introduces engineering and business as interconnected, showing that the intentionality in design mimics that of God via objectives, constraints, and variables seen in intelligent design. Right now, we have a middle school engineering course in development along with a mousetrap build course. We hope to create multiple builds per age group (K-2nd, 3rd-5th, 6th-8th, and 9th-12th). The idea is to help kids learn how to use science and math as tools for engineering while spending more time building and less on a computer with 18 week courses instead of box subscriptions.

We are serving homeschool families through a set of LearnWorlds courses. The families range from homeschool clusters, single families, or church groups. Some are Christian, others are not. We are attempting to launch this summer at an event in Tennessee, so I will know more about our audience after we begin sales.
```

---

## Q2 — Paste 1-2 things you've written recently. Don't edit them.

An email, a LinkedIn post, a DM, a doc — anything that sounds like you when you're not trying. **Paste verbatim.** Do not type these mid-conversation with Claude — chat-shaped samples are worse than no samples (voice contamination).

```
Hi Graysen,
As Dr. Mark said Ethan and I would be more than happy to answer any questions you have about our K12 engineering curriculum company. If you would prefer to meet on teams, send us some meeting times that you are available for, and we can correlate schedules. I'm on my PC all day so just reach out! 

Blessings,

Shane Reynolds
COO | Genesis K12 Academy
```

```
Nanotechnology isn't used in hospitals because it's difficult to mass-produce. Two production methods exist: top-down and bottom-up. The top-down method involves dividing a set of raw materials into smaller pieces to build a product. Bottom-up is a method that combines smaller pieces (such as molecules) to construct a product. However, making something so small on a large scale can lead to many defects and errors, and even the slightest variation in size can alter the material's properties. This means that the entire system could become compromised, potentially causing harm to patients.
```

---

## Q3 — What are your 2-3 biggest priorities for the next 90 days?

Quarterly priorities. Not yearly aspirations. Things that, if not done by July, would make you say "I wasted Q2."

```
1. By mid-June: build course drafted + first 8 modules of the Creationeering course drafted.
2. By end of May (if still on track): Summer Camp course completed.
3. By end of June: full MS course wrapped. Launch event in July. First MS course sales beginning in August.
4. By August: second project in development (HS course or alternate format, pending closeout meeting).
```

---

## Q4 — Where does revenue actually land, and where is it tracked?

Multiple answers OK. Stripe? Skool? GoHighLevel? QuickBooks? A spreadsheet?

```
Pre-revenue. Currently funded by an angel investor; funds land in a business bank account. Payment system not yet set up — planning to use LearnWorlds for the storefront and QuickBooks for bookkeeping once sales begin at/after the July launch event.
```

---

## Q5 — Where do you talk to customers, your team, and the outside world day-to-day?

Email (which one — Gmail / Outlook)? Slack? Teams? DMs (Skool / Discord / iMessage)? Phone?

```
Google Workspace (Gmail) for all business communication. Customer and beta tester outreach via Gmail or phone depending on relationship. Social media being set up — media content ready by June. Most inbound leads come via referral from Dr. Mark Horstemeyer (mentor and close friend). Internal team communication with co-founder Ethan is primarily Gmail and phone.
```

---

## Q6 — Where do meeting recordings, notes, and important docs live?

Granola? Otter? Fireflies? Google Drive? Notion? Dropbox? A folder on your desktop you keep meaning to organize?

```
Primary docs: Google Drive (via Google Workspace). Some older scope drafts still in Microsoft Excel locally. Previous course references accessible via a former Liberty University Online Academy employee account (still active for consulting purposes) — not integrated into current workflow.
```

---

## Q7 — What's the one task that eats your week, and where do you currently track work?

The single biggest time-suck or recurring drudgery. Plus where tasks/projects live (ClickUp / Asana / Linear / Notion / a notebook).

```
Biggest time-suck: writing and editing curriculum. Initial AI drafts (Gemini) don't match the required tone and miss important pedagogical elements. Re-formatting text, creating images, and formatting lessons inside LearnWorlds consumes most of the week. No current task tracking system — jumps between lessons to hit progress goals. Now full-time, trying to add structure. A to-do system would need push notifications to phone and desktop to be useful. Sticky notes worked well in college.
```

---

When this file is filled, run `/onboard` (or re-run it) and the wizard will scaffold your Day-1 file set: `context/`, `references/voice.md`, populated `connections.md`, and a filled `CLAUDE.md`.
