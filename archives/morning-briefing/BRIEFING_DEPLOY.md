# Deploy the morning briefing (Cloud Run Job + Cloud Scheduler)

`scripts/morning_briefing.py` reads the PM board (Firestore `pm_issues` via REST),
buckets each person's open tasks, has Claude voice a DM, and sends per-person Slack
DMs (Cade = QC, Shane = project, Ethan = business). It runs once at 8 AM ET and exits.

Project `genesis-modularity`, region `us-central1`. Reuses the existing `bez` Artifact
Registry repo and the `bez-slack-bot` / `bez-anthropic` secrets (same token + key).

## One-time prerequisites
```bash
gcloud config set project genesis-modularity
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com artifactregistry.googleapis.com

# Runtime service account for the job — reads Firestore.
gcloud iam service-accounts create morning-briefing \
  --display-name "Morning briefing job"
gcloud projects add-iam-policy-binding genesis-modularity \
  --member "serviceAccount:morning-briefing@genesis-modularity.iam.gserviceaccount.com" \
  --role roles/datastore.viewer
# Let it read the two existing secrets.
for S in bez-slack-bot bez-anthropic; do
  gcloud secrets add-iam-policy-binding $S \
    --member "serviceAccount:morning-briefing@genesis-modularity.iam.gserviceaccount.com" \
    --role roles/secretmanager.secretAccessor
done
```

## Build + create the job
```bash
# from D:/AIOS
gcloud builds submit --config cloud/briefing.cloudbuild.yaml

gcloud run jobs create morning-briefing \
  --image us-central1-docker.pkg.dev/genesis-modularity/bez/morning-briefing:latest \
  --region us-central1 \
  --service-account morning-briefing@genesis-modularity.iam.gserviceaccount.com \
  --set-secrets SLACK_BOT_TOKEN=bez-slack-bot:latest,ANTHROPIC_API_KEY=bez-anthropic:latest \
  --max-retries 1 --task-timeout 300s
# (use `gcloud run jobs update morning-briefing ...` to change it later)
```

## Test before scheduling
```bash
# Dry-run first (no DMs): override the command.
gcloud run jobs execute morning-briefing --region us-central1 \
  --args "python,scripts/morning_briefing.py"          # no --send
gcloud run jobs executions logs read --region us-central1 \
  $(gcloud run jobs executions list --job morning-briefing --region us-central1 --limit 1 --format 'value(name)')

# When happy, a real run sends DMs:
gcloud run jobs execute morning-briefing --region us-central1
```

## Schedule it (8 AM ET, DST-aware)
```bash
gcloud scheduler jobs create http morning-briefing-8am \
  --location us-central1 \
  --schedule "0 8 * * *" \
  --time-zone "America/New_York" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/genesis-modularity/jobs/morning-briefing:run" \
  --http-method POST \
  --oauth-service-account-email morning-briefing@genesis-modularity.iam.gserviceaccount.com
# The scheduler SA also needs run.invoker on the job:
gcloud run jobs add-iam-policy-binding morning-briefing --region us-central1 \
  --member "serviceAccount:morning-briefing@genesis-modularity.iam.gserviceaccount.com" \
  --role roles/run.invoker
```

## Pause / change
- Pause: `gcloud scheduler jobs pause morning-briefing-8am --location us-central1`
- Change time: `gcloud scheduler jobs update http morning-briefing-8am --location us-central1 --schedule "..."`
- Rebuild after code change: re-run `gcloud builds submit ...` then `gcloud run jobs update morning-briefing --image ...latest` (or it picks up `:latest` on next execution).

## Notes
- If the Slack bot token ever rotates, update the `bez-slack-bot` secret (a new version) — both Bez and this job read `:latest`.
- The job has no `.env`; `SLACK_BOT_TOKEN` + `ANTHROPIC_API_KEY` come from secrets, Firestore auth from the runtime SA.
