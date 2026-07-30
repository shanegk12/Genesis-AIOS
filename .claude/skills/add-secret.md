# /add-secret

Add a new environment secret to the GK12 Platform App Hosting backends. Gets burned repeatedly if done wrong — follow exactly.

## Required information

- Secret name (e.g. `OPENAI_API_KEY`)
- Secret value
- Is it needed at build time (NEXT_PUBLIC_ vars) or runtime only?
- Which backends: prod (`genesis-lms`), staging (`genesis-lms-staging`), or both?

---

## Steps

### 1. Create the secret in Secret Manager

```powershell
# Write value to a temp file — NEVER pipe strings in PowerShell (causes BOM/encoding issues).
# Create the secret with gcloud --data-file (fully non-interactive, no `<` redirection).
# MUST use UTF8Encoding($false) — [System.Text.Encoding]::UTF8 writes a BOM in PS 5.1,
# which gets stored in the secret and throws "ByteString ... value 65279" at runtime.
[System.IO.File]::WriteAllText("C:\Users\Shane\AppData\Local\Temp\secret.txt", "SECRET_VALUE_HERE", (New-Object System.Text.UTF8Encoding $false))
gcloud secrets create SECRET_NAME --project genesis-modularity --data-file="C:\Users\Shane\AppData\Local\Temp\secret.txt"
# If it already exists, add a new version instead:
#   gcloud secrets versions add SECRET_NAME --project genesis-modularity --data-file="C:\Users\Shane\AppData\Local\Temp\secret.txt"
Remove-Item "C:\Users\Shane\AppData\Local\Temp\secret.txt"
```

> ⚠️ Pitfalls that have burned this before:
> - There is **no `firebase secrets:set`** command — the App Hosting variant is `firebase apphosting:secrets:set` (interactive). Using `gcloud secrets create --data-file` above sidesteps it entirely.
> - PowerShell has **no `<` input redirection** (`<` is reserved → "The '<' operator is reserved for future use"). `--data-file` avoids needing it.
> - Run from anywhere, but **pass `--project genesis-modularity`** — Firebase/gcloud have no active project unless you're in the repo dir.

### 2. Grant access to App Hosting service accounts

Run for **each backend** the secret is needed on:
```powershell
firebase apphosting:secrets:grantaccess SECRET_NAME --backend genesis-lms
firebase apphosting:secrets:grantaccess SECRET_NAME --backend genesis-lms-staging
```

Do NOT use manual IAM binding (`gcloud secrets add-iam-policy-binding`) — App Hosting uses its own SA and manual binding targets the wrong one, causing PermissionDenied build failures.

### 3. Add to `apphosting.yaml`

```yaml
- variable: SECRET_NAME
  secret: SECRET_NAME
  availability:
    - RUNTIME   # or BUILD and RUNTIME for NEXT_PUBLIC_ vars
```

### 4. Use in code with a lazy getter

Never call SDK constructors at module level using runtime secrets — they're `undefined` during `next build`.

```ts
// Good — lazy getter
let _client: SomeClient | null = null;
export function getClient() {
  if (!_client) _client = new SomeClient(process.env.SECRET_NAME!);
  return _client;
}

// Bad — module level
const client = new SomeClient(process.env.SECRET_NAME!); // undefined at build time
```

### 5. Deploy

```powershell
git add apphosting.yaml && git commit -m "feat: add SECRET_NAME to apphosting.yaml"
git push origin staging   # validate build first
# after staging passes:
git push origin main
```

---

## Gotchas

- NEXT_PUBLIC_ secrets need `availability: [BUILD, RUNTIME]`; everything else is `RUNTIME` only
- `firebase secrets:set --force` overwrites existing versions — always confirm the value before running
- If build fails with PermissionDenied, re-run `grantaccess` — it targets the correct SA automatically
- DNS is in Squarespace Domains (not GCP) — unrelated to secrets but commonly confused
