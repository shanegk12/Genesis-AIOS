---
name: deploy
description: Use when shipping a change to production on the GK12 Platform, or when Shane says "deploy", "ship it", "push to prod", or "/deploy". Enforces the staging-then-main workflow with the validation checklist between them. Never push straight to main without a staging validation.
---

# /deploy

Ship a change from the local branch to production on the GK12 Platform. Always goes staging → main. Never push directly to main without a staging validation.

## Workflow

### 1. Commit locally (if not already done)

```powershell
git add <specific files>   # never git add -A — avoid accidentally staging .env or large binaries
git commit -m "type: description"
```

### 2. Push to staging

```powershell
git push origin staging
```

App Hosting picks up the push automatically. Watch the build at:
Firebase Console → App Hosting → `genesis-lms-staging`

Staging and prod share the same Firestore database. Any Firestore writes on staging are real.

### 3. Validate on staging

- Open the staging URL and exercise the changed feature
- Check the browser console for errors
- If the change touches an API route, test it end-to-end
- If the change adds a Firestore collection, verify `firestore.rules` was updated and deployed

### 4. Deploy Firestore rules (if changed)

```powershell
firebase deploy --only firestore:rules
```

Rules are shared across prod and staging — deploy once, applies everywhere.

### 5. Merge to main (prod)

```powershell
git push origin main
```

Prod build starts automatically. Watch at Firebase Console → App Hosting → `genesis-lms`.

---

## If something goes wrong on prod

The fastest rollback is reverting the commit and pushing:
```powershell
git revert HEAD --no-edit
git push origin main
```

Do not force-push main.

---

## Checklist before pushing to main

- [ ] Staging build passed (no TypeScript errors, no build errors)
- [ ] Feature tested on staging URL
- [ ] `firestore.rules` deployed if any new collections were added
- [ ] New secrets granted access to both backends (see `/add-secret`)
- [ ] No hardcoded secrets, blob URLs, or `console.log` left in committed code
