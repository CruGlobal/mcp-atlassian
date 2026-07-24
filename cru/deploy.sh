#!/usr/bin/env bash
set -euo pipefail

# Deploy mcp-atlassian to Cloud Run in cru-mattdrees-sandbox-poc.
# Prerequisites: setup-gcp.sh has been run, image has been pushed.

PROJECT=cru-mattdrees-sandbox-poc
REGION=us-east4
SA_EMAIL="mcp-atlassian@${PROJECT}.iam.gserviceaccount.com"
IMAGE="us-central1-docker.pkg.dev/${PROJECT}/mcp-atlassian/mcp-atlassian:latest"
SERVICE_URL="https://mcp-atlassian-178891842216.us-east4.run.app"

SHARED_VPC_PROJECT=cru-shared-vpc-host-prod-2
NETWORK="projects/${SHARED_VPC_PROJECT}/global/networks/shared-vpc-prod"
SUBNET="projects/${SHARED_VPC_PROJECT}/regions/us-east4/subnetworks/stage-1"

# Jira DC OAuth client ID (registered in Jira Application Links)
JIRA_OAUTH_CLIENT_ID="a8fe4d1f5436d7138c94ecfa22afd187"

gcloud run deploy mcp-atlassian \
  --image="$IMAGE" \
  --region="$REGION" \
  --project="$PROJECT" \
  --service-account="$SA_EMAIL" \
  --network="$NETWORK" \
  --subnet="$SUBNET" \
  --network-tags=egress-internal \
  --vpc-egress=private-ranges-only \
  --allow-unauthenticated \
  --port=3000 \
  --set-env-vars="TRANSPORT=streamable-http" \
  --set-env-vars="JIRA_URL=https://jira.cru.org" \
  --set-env-vars="ATLASSIAN_OAUTH_PROXY_ENABLE=true" \
  --set-env-vars="ATLASSIAN_OAUTH_CLIENT_ID=${JIRA_OAUTH_CLIENT_ID}" \
  --set-env-vars="ATLASSIAN_OAUTH_REDIRECT_URI=${SERVICE_URL}/callback" \
  --set-env-vars="ATLASSIAN_OAUTH_SCOPE=WRITE" \
  --set-env-vars="PUBLIC_BASE_URL=${SERVICE_URL}" \
  --set-env-vars="ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE=factory" \
  --set-env-vars="ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY=firestore_store.store:create_store" \
  --set-env-vars="ATLASSIAN_OAUTH_CLIENT_STORAGE_CONFIG_JSON={\"project_id\":\"${PROJECT}\"}" \
  --set-secrets="ATLASSIAN_OAUTH_CLIENT_SECRET=jira-oauth-client-secret:latest"

echo ""
echo "Deployed: ${SERVICE_URL}"
echo "Health:   curl -s ${SERVICE_URL}/mcp"
echo "Claude Desktop config:"
echo '  {"mcpServers": {"jira": {"url": "'"${SERVICE_URL}/mcp"'"}}}'
