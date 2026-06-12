/**
 * Seeds modules and units for the Mousetrap Build Middle School course.
 * Run once: node scripts/seed_mousetrap_modules.js
 */
const { initializeApp, getApps } = require("firebase-admin/app");
const { getFirestore } = require("firebase-admin/firestore");

if (getApps().length === 0) initializeApp({ projectId: "genesis-modularity" });
const db = getFirestore();

// Mousetrap is bundled inside the Creationeering course (one license covers both)
const COURSE_ID = "creationeering-ms";

// MT units nest inside the existing Creationeering "Module N" documents (no separate MT-Module-* docs)
const UNITS = [
  // Module 1 — Thinking Like an Engineer (M-001 to M-007)
  { id: "MT-1-1", moduleId: "Module 1", title: "Engineering Foundations", order: 1, lessonIds: ["M-001","M-002","M-003","M-004"] },
  { id: "MT-1-2", moduleId: "Module 1", title: "Systems and OCV", order: 2, lessonIds: ["M-005","M-006","M-007"] },
  // Module 2 — Design (M-008 to M-013)
  { id: "MT-2-1", moduleId: "Module 2", title: "Design Process", order: 1, lessonIds: ["M-008","M-009","M-010","M-011"] },
  { id: "MT-2-2", moduleId: "Module 2", title: "Prototyping", order: 2, lessonIds: ["M-012","M-013"] },
  // Module 3 — Analysis & Synthesis (M-014 to M-023)
  { id: "MT-3-1", moduleId: "Module 3", title: "Force and Motion", order: 1, lessonIds: ["M-014","M-015","M-016","M-017","M-018"] },
  { id: "MT-3-2", moduleId: "Module 3", title: "Energy and Modeling", order: 2, lessonIds: ["M-019","M-020","M-021","M-022","M-023"] },
  // Module 4 — Procurement (M-024 to M-028)
  { id: "MT-4-1", moduleId: "Module 4", title: "Materials and Sourcing", order: 1, lessonIds: ["M-024","M-025","M-026","M-027","M-028"] },
  // Module 5 — Fabrication (M-029 to M-031)
  { id: "MT-5-1", moduleId: "Module 5", title: "Build Techniques", order: 1, lessonIds: ["M-029","M-030","M-031"] },
  // Module 6 — Logistics (M-032 to M-039)
  { id: "MT-6-1", moduleId: "Module 6", title: "Planning and Flow", order: 1, lessonIds: ["M-032","M-033","M-034","M-035","M-036"] },
  { id: "MT-6-2", moduleId: "Module 6", title: "Documentation", order: 2, lessonIds: ["M-037","M-038","M-039"] },
  // Module 7 — Assembly (M-040 to M-047)
  { id: "MT-7-1", moduleId: "Module 7", title: "Build 1 and 2", order: 1, lessonIds: ["M-040","M-041","M-042","M-043","M-044"] },
  { id: "MT-7-2", moduleId: "Module 7", title: "Iteration", order: 2, lessonIds: ["M-045","M-046","M-047"] },
  // Module 8 — Performance (M-048 to M-055)
  { id: "MT-8-1", moduleId: "Module 8", title: "Testing and Optimization", order: 1, lessonIds: ["M-048","M-049","M-050","M-051","M-052"] },
  { id: "MT-8-2", moduleId: "Module 8", title: "Final Build", order: 2, lessonIds: ["M-053","M-054","M-055"] },
  // Module 9 — Decommissioning (M-056 to M-070)
  { id: "MT-9-1", moduleId: "Module 9", title: "Reflection and Documentation", order: 1, lessonIds: ["M-056","M-057","M-058","M-059","M-060","M-061","M-062"] },
  { id: "MT-9-2", moduleId: "Module 9", title: "Sustainability and Legacy", order: 2, lessonIds: ["M-063","M-064","M-065","M-066","M-067","M-068","M-069","M-070"] },
];

async function seed() {
  const batch = db.batch();

  for (const unit of UNITS) {
    batch.set(db.collection("units").doc(unit.id), { ...unit, courseId: COURSE_ID });
  }

  await batch.commit();
  console.log(`Seeded ${UNITS.length} MT units for ${COURSE_ID}`);

  // Update lesson moduleId/unitId — skip missing docs gracefully
  let updated = 0, skipped = 0;
  for (const unit of UNITS) {
    for (const lessonId of unit.lessonIds) {
      const ref = db.collection("lessons").doc(lessonId);
      const snap = await ref.get();
      if (snap.exists) {
        await ref.update({ moduleId: unit.moduleId, unitId: unit.id });
        updated++;
      } else {
        console.log(`  skip ${lessonId} — not in Firestore yet`);
        skipped++;
      }
    }
  }
  console.log(`Updated ${updated} lessons, skipped ${skipped} (not yet imported)`);

  // Also fix courseId on M- lesson documents (pipeline sets "mousetrap-ms" but
  // Mousetrap is bundled inside creationeering-ms for single-license access)
  let courseFixed = 0;
  const mLessons = await db.collection("lessons").where("courseId", "==", "mousetrap-ms").get();
  for (const snap of mLessons.docs) {
    await snap.ref.update({ courseId: COURSE_ID });
    courseFixed++;
  }
  console.log(`Fixed courseId on ${courseFixed} Mousetrap lessons → ${COURSE_ID}`);
}

seed().catch(console.error);
