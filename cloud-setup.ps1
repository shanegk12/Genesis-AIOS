# One-time GCP setup for the GK12 lesson pipeline on Cloud Run.
# Run from D:\AIOS with gcloud authenticated as owner of genesis-aios.
# Work through each section manually — do not run the whole file at once.

$PROJECT  = "genesis-aios"
$REGION   = "us-central1"
$SA_NAME  = "pipeline-runner"
$SA_EMAIL = "$SA_NAME@$PROJECT.iam.gserviceaccount.com"
$IMAGE    = "$REGION-docker.pkg.dev/$PROJECT/gk12-pipeline/pipeline:latest"
$JOB      = "gk12-lesson-pipeline"

# ── 1. Enable required APIs ──────────────────────────────────────────────────
gcloud services enable `
  run.googleapis.com `
  artifactregistry.googleapis.com `
  cloudscheduler.googleapis.com `
  secretmanager.googleapis.com `
  cloudbuild.googleapis.com `
  --project=$PROJECT

# ── 2. Create service account ────────────────────────────────────────────────
gcloud iam service-accounts create $SA_NAME `
  --display-name="GK12 Pipeline Runner" `
  --project=$PROJECT

gcloud projects add-iam-policy-binding $PROJECT `
  --member="serviceAccount:$SA_EMAIL" `
  --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding $PROJECT `
  --member="serviceAccount:$SA_EMAIL" `
  --role="roles/run.invoker"

# ── 3. Store secrets in Secret Manager ───────────────────────────────────────
# Run each block one at a time and paste the value when prompted.

$val = Read-Host "GEMINI_API_KEY"
gcloud secrets create GEMINI_API_KEY --project=$PROJECT
$val | gcloud secrets versions add GEMINI_API_KEY --data-file=- --project=$PROJECT

$val = Read-Host "GITHUB_TOKEN (needs repo read+write scope)"
gcloud secrets create GITHUB_TOKEN --project=$PROJECT
$val | gcloud secrets versions add GITHUB_TOKEN --data-file=- --project=$PROJECT

$val = Read-Host "NTFY_TOKEN (press Enter to skip)"
gcloud secrets create NTFY_TOKEN --project=$PROJECT
$val | gcloud secrets versions add NTFY_TOKEN --data-file=- --project=$PROJECT

$val = Read-Host "GOOGLE_DRIVE_MS_CURRICULUM_ID"
gcloud secrets create GOOGLE_DRIVE_MS_CURRICULUM_ID --project=$PROJECT
$val | gcloud secrets versions add GOOGLE_DRIVE_MS_CURRICULUM_ID --data-file=- --project=$PROJECT

# ── 4. Create Artifact Registry repository ───────────────────────────────────
gcloud artifacts repositories create gk12-pipeline `
  --repository-format=docker `
  --location=$REGION `
  --project=$PROJECT

# ── 5. Build and push container image ────────────────────────────────────────
# Must be run from D:\AIOS (repo root) so Docker has the build context.
gcloud builds submit --tag $IMAGE --project=$PROJECT

# ── 6. Create Cloud Run Job ──────────────────────────────────────────────────
gcloud run jobs create $JOB `
  --image=$IMAGE `
  --region=$REGION `
  --service-account=$SA_EMAIL `
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest,GITHUB_TOKEN=GITHUB_TOKEN:latest,NTFY_TOKEN=NTFY_TOKEN:latest,GOOGLE_DRIVE_MS_CURRICULUM_ID=GOOGLE_DRIVE_MS_CURRICULUM_ID:latest" `
  --memory=512Mi `
  --task-timeout=3600 `
  --project=$PROJECT

# ── 7. Create Cloud Scheduler trigger (daily 8:05 AM Central) ────────────────
$PROJECT_NUMBER = gcloud projects describe $PROJECT --format="value(projectNumber)"

gcloud scheduler jobs create http gk12-daily-8am `
  --location=$REGION `
  --schedule="5 8 * * *" `
  --time-zone="America/Chicago" `
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_NUMBER/jobs/$JOB`:run" `
  --message-body="{}" `
  --oauth-service-account-email=$SA_EMAIL `
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" `
  --project=$PROJECT

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Service account to share with Google Docs/Drive: $SA_EMAIL"
Write-Host ""
Write-Host "MANUAL STEP REQUIRED:" -ForegroundColor Yellow
Write-Host "  1. Open each Google Doc and share with $SA_EMAIL as Editor"
Write-Host "  2. Share the MS Curriculum Drive folder with $SA_EMAIL as Editor"
Write-Host ""
Write-Host "Test run: gcloud run jobs execute $JOB --region=$REGION --project=$PROJECT"
