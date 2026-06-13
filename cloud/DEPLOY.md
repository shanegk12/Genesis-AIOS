# Deploy 24/7 Bez to Cloud Run

Bez = a Slack Socket-Mode agent (`scripts/bez_socket.py` + `bez_agent.py`) that reads #aios and does real work (bash, git, deploy) with guardrails. Cloud Run keeps it always-on so it runs even when your PC is off.

## Prerequisites (one-time, from Shane)
1. **gcloud login** (it expires): `gcloud auth login` then `gcloud config set project genesis-modularity`.
2. **A GitHub token** so Bez can clone + push both repos from the cloud — a fine-grained PAT (or classic with `repo` scope) covering `Genesis-AIOS` + `genesis-education-solutions`. Create at github.com → Settings → Developer settings → Personal access tokens.
3. Enable APIs: `gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com`
4. Artifact Registry repo: `gcloud artifacts repositories create bez --repository-format=docker --location=us-central1` (once).

## Secrets (Secret Manager)
Create these from the values in `D:/AIOS/.env` + the GitHub token:
```
printf '%s' "<SLACK_BOT_TOKEN>"   | gcloud secrets create bez-slack-bot   --data-file=-
printf '%s' "<SLACK_APP_TOKEN>"   | gcloud secrets create bez-slack-app   --data-file=-
printf '%s' "<ANTHROPIC_API_KEY>" | gcloud secrets create bez-anthropic   --data-file=-
printf '%s' "<GITHUB_TOKEN>"      | gcloud secrets create bez-github       --data-file=-
```
(Use `gcloud secrets versions add <name> --data-file=-` to rotate later.)

## Build + deploy
```
# from D:/AIOS
gcloud builds submit --config cloud/cloudbuild.yaml

gcloud run deploy bez-24-7 \
  --image us-central1-docker.pkg.dev/genesis-modularity/bez/bez:latest \
  --region us-central1 \
  --min-instances 1 --max-instances 1 \
  --no-cpu-throttling \
  --no-allow-unauthenticated \
  --memory 2Gi \
  --set-secrets SLACK_BOT_TOKEN=bez-slack-bot:latest,SLACK_APP_TOKEN=bez-slack-app:latest,ANTHROPIC_API_KEY=bez-anthropic:latest,GITHUB_TOKEN=bez-github:latest
```
- `--min-instances 1 --no-cpu-throttling` keeps the container warm so the WebSocket persists (Socket Mode needs a long-lived process). `--max-instances 1` ensures exactly ONE socket connection (Slack load-balances across connections — multiple instances would split/drop events).
- The container's health server answers Cloud Run on `$PORT`; the socket runs alongside.

## Verify
After deploy, message **#aios** → Bez replies (now from the cloud). `gcloud run services logs read bez-24-7 --region us-central1` to watch.

## Notes / next
- **App Hosting deploys** happen via git push (Bez pushes → App Hosting auto-builds), so the GitHub token covers prod deploys. **Firestore rules** deploy (`firebase deploy --only firestore:rules`) needs Firebase auth in the container — add a service-account key secret + `GOOGLE_APPLICATION_CREDENTIALS` when you want Bez to deploy rules too.
- Guardrails (Shane/Ethan-only, CONFIRM DEPLOY gate, audit-to-thread, BEZ STOP) are in `bez_agent.py` and apply in the cloud too.
- Stop it: `gcloud run services update bez-24-7 --region us-central1 --min-instances 0` (or delete the service).
