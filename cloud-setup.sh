#!/bin/bash
# One-time GCP setup for the GK12 lesson pipeline on Cloud Run.
# Run each block manually — review before executing.
# Prerequisites: gcloud CLI authenticated as an owner of genesis-aios project.

PROJECT=genesis-aios
REGION=us-central1
SA_NAME=pipeline-runner
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
IMAGE="us-central1-docker.pkg.dev/${PROJECT}/gk12-pipeline/pipeline:latest"
JOB_NAME=gk12-lesson-pipeline

# ── 1. Enable required APIs ──────────────────────────────────────────────────
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  --project="${PROJECT}"

# ── 2. Create service account ────────────────────────────────────────────────
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="GK12 Pipeline Runner" \
  --project="${PROJECT}"

# Allow it to access secrets and invoke Cloud Run jobs
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"

# ── 3. Store secrets in Secret Manager ───────────────────────────────────────
# Run each line, paste the value when prompted, then Ctrl+D
echo "Paste GEMINI_API_KEY value:"
gcloud secrets create GEMINI_API_KEY --project="${PROJECT}"
read -r -s GEMINI_VAL && echo -n "${GEMINI_VAL}" | \
  gcloud secrets versions add GEMINI_API_KEY --data-file=- --project="${PROJECT}"

echo "Paste GITHUB_TOKEN value (needs repo read+write scope):"
gcloud secrets create GITHUB_TOKEN --project="${PROJECT}"
read -r -s GH_VAL && echo -n "${GH_VAL}" | \
  gcloud secrets versions add GITHUB_TOKEN --data-file=- --project="${PROJECT}"

echo "Paste NTFY_TOKEN value (or press Enter to skip):"
gcloud secrets create NTFY_TOKEN --project="${PROJECT}"
read -r -s NTFY_VAL && echo -n "${NTFY_VAL}" | \
  gcloud secrets versions add NTFY_TOKEN --data-file=- --project="${PROJECT}"

echo "Paste GOOGLE_DRIVE_MS_CURRICULUM_ID value:"
gcloud secrets create GOOGLE_DRIVE_MS_CURRICULUM_ID --project="${PROJECT}"
read -r -s DRIVE_VAL && echo -n "${DRIVE_VAL}" | \
  gcloud secrets versions add GOOGLE_DRIVE_MS_CURRICULUM_ID --data-file=- --project="${PROJECT}"

# ── 4. Create Artifact Registry repository ───────────────────────────────────
gcloud artifacts repositories create gk12-pipeline \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT}"

# ── 5. Build and push container image (run from repo root) ───────────────────
gcloud builds submit \
  --tag "${IMAGE}" \
  --project="${PROJECT}"

# ── 6. Create Cloud Run Job ──────────────────────────────────────────────────
gcloud run jobs create "${JOB_NAME}" \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest,NTFY_TOKEN=NTFY_TOKEN:latest,GOOGLE_DRIVE_MS_CURRICULUM_ID=GOOGLE_DRIVE_MS_CURRICULUM_ID:latest" \
  --memory=512Mi \
  --task-timeout=3600 \
  --project="${PROJECT}"

# ── 7. Create Cloud Scheduler trigger (daily 8:05 AM Central) ────────────────
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format="value(projectNumber)")

gcloud scheduler jobs create http gk12-daily-8am \
  --location="${REGION}" \
  --schedule="5 8 * * *" \
  --time-zone="America/Chicago" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/${JOB_NAME}:run" \
  --message-body="{}" \
  --oauth-service-account-email="${SA_EMAIL}" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --project="${PROJECT}"

echo ""
echo "Setup complete."
echo "Service account email to share with Google Docs/Drive: ${SA_EMAIL}"
echo ""
echo "MANUAL STEP REQUIRED:"
echo "  1. Open each Google Doc and share with: ${SA_EMAIL} (Editor)"
echo "  2. Share the MS Curriculum Drive folder with: ${SA_EMAIL} (Editor)"
echo ""
echo "Test with: gcloud run jobs execute ${JOB_NAME} --region=${REGION} --project=${PROJECT}"
