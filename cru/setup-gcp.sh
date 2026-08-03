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

echo "=== Enable Firestore TTL policies ==="
# The FirestoreStore writes a Timestamp `expires_at` on every entry that has a
# TTL; these policies let Firestore garbage-collect them in the background.
# Without them, expired docs linger forever (reads still treat them as missing).
# Note: mcp-oauth-proxy-clients is included for completeness, but FastMCP stores
# DCR client registrations with no TTL, so its expires_at is always null and
# nothing there is ever collected.
for COLLECTION in \
  mcp_atlassian_mcp-upstream-tokens \
  mcp_atlassian_mcp-refresh-tokens \
  mcp_atlassian_mcp-jti-mappings \
  mcp_atlassian_mcp-authorization-codes \
  mcp_atlassian_mcp-oauth-transactions \
  mcp_atlassian_mcp-oauth-proxy-clients
do
  gcloud firestore fields ttls update expires_at \
    --collection-group="$COLLECTION" \
    --enable-ttl \
    --database='(default)' \
    --project="$PROJECT" \
    --quiet --async \
    >/dev/null 2>&1 && echo "  TTL enabled: $COLLECTION" \
    || echo "  TTL already set (or failed): $COLLECTION"
done

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
