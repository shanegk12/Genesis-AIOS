---
name: add-api-route
description: Use when adding a new admin API route to the GK12 Platform, or when Shane says "add an api route", "new admin route", or "/add-api-route". Covers the required auth pattern (verifyAdminReq), error isolation, Storage download-token URLs, Firestore rules, and Gemini config gotchas. Every admin route shares one structure; missing a piece causes auth failures, silent Firestore errors, or build breaks.
---

# /add-api-route

Add a new admin API route to the GK12 Platform. Every admin route has the same required structure — missing pieces cause auth failures, silent Firestore errors, or build breaks.

## Required information

- Route path (e.g. `/api/admin/lessons/reorder`)
- HTTP method(s): GET / POST / PATCH / DELETE
- What Firestore collections does it read or write?
- Does it use Firebase Storage? Gemini? Resend email?

---

## File location

`src/app/api/admin/<route-name>/route.ts`

Copy the pattern below — do not deviate from the auth structure.

---

## Required structure

```ts
import { NextRequest, NextResponse } from "next/server";
import { adminDb, getAdminAuth } from "@/lib/firebase-admin";

function isAdmin(email: string | null | undefined): boolean {
  return (email ?? "").toLowerCase().endsWith("@gk12academy.com");
}

async function verifyAdmin(req: NextRequest): Promise<string | null> {
  const authHeader = req.headers.get("authorization");
  if (!authHeader?.startsWith("Bearer ")) return null;
  const token = authHeader.slice(7);
  try {
    const decoded = await getAdminAuth().verifyIdToken(token);
    return isAdmin(decoded.email) ? (decoded.email ?? null) : null;
  } catch {
    return null;
  }
}

export async function POST(req: NextRequest) {
  const adminEmail = await verifyAdmin(req);
  if (!adminEmail) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  let body: { ... };
  try { body = await req.json(); }
  catch { return NextResponse.json({ error: "Invalid JSON" }, { status: 400 }); }

  try {
    // main logic here
    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("[route-name] error:", err);
    return NextResponse.json({ error: "Failed", detail: (err as Error).message }, { status: 500 });
  }
}
```

---

## Checklist

### Auth
- [ ] Every handler calls `verifyAdmin(req)` and returns 401 immediately if null
- [ ] No route skips auth "for now"

### Error handling
- [ ] Main logic is wrapped in try/catch
- [ ] Each external call that can fail independently (Gemini, Resend, Storage) has its own try/catch so one failure doesn't abort the whole pipeline
- [ ] Error response includes `detail: (err as Error).message` so the client can display it

### Firebase Storage
- [ ] Uses download token URL pattern — **never `getSignedUrl`**
- [ ] Pattern: `randomUUID()` → `file.save(buffer, { metadata: { metadata: { firebaseStorageDownloadTokens: token } } })` → construct URL manually
- [ ] Reference: `src/app/api/admin/images/route.ts`

### Gemini / Imagen
- [ ] Model: `gemini-2.5-flash` (not flash-lite — 404/503 in App Hosting)
- [ ] Image model: `imagen-4.0-fast-generate-001` with `:predict` endpoint
- [ ] Short JSON responses: add `thinkingConfig: { thinkingBudget: 0 } as any` to generationConfig
- [ ] All `generateContent` calls wrapped in try/catch with a sensible fallback

### Firestore rules
- [ ] Any new collection the route writes to needs a rule in `firestore.rules`
- [ ] Admin routes use `adminDb` (Admin SDK, bypasses rules) — but client-side reads of those collections still need rules
- [ ] Deploy after adding: `firebase deploy --only firestore:rules`

### Firestore writes
- [ ] Never write `undefined` values — Firestore rejects them with a hard error
- [ ] To clear optional fields, destructure them out rather than setting to `undefined`:
  ```ts
  const { fieldToRemove: _, ...rest } = obj;
  await doc.update({ ...rest });
  ```
- [ ] Alternative: use `FieldValue.delete()` from `firebase-admin/firestore` for top-level field deletions

### Secrets (if new env var needed)
- [ ] See `/add-secret` — lazy getter, grantaccess on both backends, apphosting.yaml updated
