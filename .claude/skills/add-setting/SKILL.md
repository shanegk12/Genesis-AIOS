---
name: add-setting
description: Use when adding a new section to the GK12 Platform admin settings page at /admin/settings, or when Shane says "add a setting", "new settings section", or "/add-setting". Covers all four touch points (component, SECTIONS registration, Firestore rules, loading state). Miss one and the section either never shows or hangs loading forever.
---

# /add-setting

Add a new section to the GK12 Platform admin settings page (`/admin/settings`). Involves four touch points — miss one and the section either never shows or hangs loading.

## Required information

- Section ID (e.g. `notifications`, `grading`)
- Which admin roles can see it? (options: `superAdmin`, `qcReviewer`, `contentEditor`)
- What Firestore doc does it read/write? (convention: `adminSettings/<section-id>`)

---

## Steps

### 1. Create the settings component

`src/components/admin/settings/<Name>Settings.tsx`

Required pattern — use `.finally()` not `.then()` for loading state:

```tsx
"use client";
import { useEffect, useState } from "react";
import { doc, getDoc, setDoc } from "firebase/firestore";
import { db } from "@/lib/firebase";

export default function NameSettings() {
  const [data, setData] = useState(DEFAULT_STATE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getDoc(doc(db, "adminSettings", "section-id"))
      .then((snap) => { if (snap.exists()) setData({ ...DEFAULT_STATE, ...snap.data() }); })
      .finally(() => setLoading(false));  // always use .finally — .then() hangs on Firestore errors
  }, []);

  async function save() {
    setSaving(true);
    await setDoc(doc(db, "adminSettings", "section-id"), data);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  if (loading) return <div className="text-sm text-gray-400">Loading…</div>;

  return ( /* settings UI */ );
}
```

### 2. Register in `src/app/admin/settings/page.tsx`

Add to the `SECTIONS` array:
```ts
{ id: "section-id", label: "Section Label", icon: "🔧" }
```

Add to `SECTION_ROLES`:
```ts
section-id: ["superAdmin"],   // or whichever roles apply
```

Add to the render switch:
```tsx
case "section-id": return <NameSettings />;
```

Import the component at the top.

### 3. Add Firestore rules

The `adminSettings` collection already has a blanket `isAdmin()` rule — no new rule needed unless this section introduces a **new collection**.

If new collection:
```
match /newCollection/{doc} {
  allow read, write: if isAdmin();
}
```
Then deploy: `firebase deploy --only firestore:rules`

### 4. Type definitions (if needed)

If the settings shape is complex or shared with other files, add an interface to `src/types/index.ts`.

---

## Gotchas

- **Never use `.then(...).catch()` without `.finally()`** — a Firestore PERMISSION_DENIED rejection won't call `.then()`, so `setLoading(false)` never runs and the page hangs. Always use `.finally(() => setLoading(false))`.
- The settings page uses `useAuth()` — it waits for `authLoading` to be false before calling Firestore. Don't add auth logic inside the individual settings components; the page handles it.
- Firestore `adminSettings` collection rules: `isAdmin()` checks email ends with `@gk12academy.com`. New admin emails need to be added to `adminAccounts` collection, not hardcoded.
