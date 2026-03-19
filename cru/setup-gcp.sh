#!/usr/bin/env bash
set -euo pipefail

PROJECT=cru-mattdrees-sandbox-poc
REGION=us-east4
SA_EMAIL="mcp-atlassian@${PROJECT}.iam.gserviceaccount.com"

echo "=== Enable APIs ==="
gcloud services enable \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  --project="$PROJECT"

echo "=== Create Firestore database (native mode) ==="
# us-east1 is the closest Firestore location to us-east4 Cloud Run
gcloud firestore databases create \
  --location=us-east1 \
  --project="$PROJECT" \
  2>/dev/null || echo "Firestore database already exists, skipping"

echo "=== Create Artifact Registry repo ==="
gcloud artifacts repositories create mcp-atlassian \
  --repository-format=docker \
  --location=us-central1 \
  --project="$PROJECT" \
  2>/dev/null || echo "Artifact Registry repo already exists, skipping"

echo "=== Grant SA roles ==="
# Firestore access
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/datastore.user" \
  --condition=None \
  --quiet

echo "=== Store OAuth client secret ==="
echo "Enter the Jira OAuth client secret (will be stored in Secret Manager):"
read -rs JIRA_SECRET
echo "$JIRA_SECRET" | gcloud secrets create jira-oauth-client-secret \
  --data-file=- \
  --project="$PROJECT" \
  2>/dev/null || {
    echo "Secret already exists, creating new version"
    echo "$JIRA_SECRET" | gcloud secrets versions add jira-oauth-client-secret \
      --data-file=- \
      --project="$PROJECT"
  }

gcloud secrets add-iam-policy-binding jira-oauth-client-secret \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="$PROJECT" \
  --quiet

echo ""
echo "=== Done ==="
echo "Artifact Registry path: us-central1-docker.pkg.dev/${PROJECT}/mcp-atlassian/mcp-atlassian:latest"
echo "Service account: ${SA_EMAIL}"
echo "Next: build + push Docker image, then deploy Cloud Run"
