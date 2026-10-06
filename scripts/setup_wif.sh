#!/usr/bin/env bash
set -euo pipefail

# Configuration
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-agenticsetup-510220}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
GITHUB_REPO="${GITHUB_REPO:-phanisagiraju-byte/adk-healthcare-agent}"
POOL_NAME="github-actions-pool"
PROVIDER_NAME="github-oidc-provider"
SA_NAME="adk-healthcare-agent-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "🚀 Bootstrapping Workload Identity Federation (WIF) for ${GITHUB_REPO} in project ${PROJECT_ID}..."

# 1. Enable required Google Cloud APIs
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  aiplatform.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  firestore.googleapis.com \
  logging.googleapis.com \
  cloudtrace.googleapis.com \
  --project="${PROJECT_ID}"

# 2. Create Service Account if it doesn't exist
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="ADK Healthcare Scheduling Agent Service Account" \
    --project="${PROJECT_ID}"
fi

# 3. Grant required IAM roles to the Service Account
ROLES=(
  "roles/aiplatform.user"
  "roles/datastore.user"
  "roles/run.admin"
  "roles/artifactregistry.admin"
  "roles/cloudbuild.builds.editor"
  "roles/iam.serviceAccountUser"
  "roles/logging.logWriter"
  "roles/cloudtrace.agent"
  "roles/serviceusage.serviceUsageAdmin"
)

for ROLE in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${ROLE}" \
    --quiet >/dev/null
done

# 4. Create Workload Identity Pool if it doesn't exist
if ! gcloud iam workload-identity-pools describe "${POOL_NAME}" \
  --location="global" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${POOL_NAME}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --display-name="GitHub Actions Pool"
fi

POOL_ID=$(gcloud iam workload-identity-pools describe "${POOL_NAME}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --format='value(name)')

# 5. Create OIDC Workload Identity Provider for GitHub Actions if it doesn't exist
if ! gcloud iam workload-identity-pools providers describe "${PROVIDER_NAME}" \
  --workload-identity-pool="${POOL_NAME}" \
  --location="global" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_NAME}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${POOL_NAME}" \
    --display-name="GitHub OIDC Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'" \
    --issuer-uri="https://token.actions.githubusercontent.com"
fi

WIF_PROVIDER=$(gcloud iam workload-identity-pools providers describe "${PROVIDER_NAME}" \
  --project="${PROJECT_ID}" \
  --location="global" \
  --workload-identity-pool="${POOL_NAME}" \
  --format='value(name)')

# 6. Allow GitHub Actions from this repository to impersonate the Service Account
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${GITHUB_REPO}" \
  --quiet >/dev/null

echo ""
echo "✅ Workload Identity Federation configured!"
echo "=================================================================="
echo "Add these two secrets to your GitHub Repository Secrets:"
echo "  WIF_PROVIDER:        ${WIF_PROVIDER}"
echo "  WIF_SERVICE_ACCOUNT: ${SA_EMAIL}"
echo "=================================================================="
