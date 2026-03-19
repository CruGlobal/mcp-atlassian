# CRU mcp-atlassian Cloud Run Deployment

Remote MCP server for Jira Data Center (jira.cru.org) with per-user OAuth.

## Architecture

- Cloud Run service in `us-east4` with Direct VPC Egress through the shared VPC
- OAuth proxy (FastMCP) handles per-user OAuth against Jira DC
- Firestore stores OAuth tokens so they survive instance restarts
- `/etc/hosts` injection fakes DNS for `jira.cru.org` (resolves to AWS internal IPs)
- `egress-internal` network tag required for shared VPC firewall to allow 10.0.0.0/8 egress

## Setup from scratch

### 1. Terraform (cru-terraform repo)

Apply `google/projects/mattdrees-sandbox/service-accounts.tf` to create:
- `mcp-atlassian` service account
- `compute.networkUser` on the `stage-1` subnet for both the SA and Cloud Run service agent

### 2. Register OAuth app in Jira DC

Administration → Applications → Application Links → Create Link → External Application → Incoming:
- Redirect URL: `https://mcp-atlassian-178891842216.us-east4.run.app/callback`
- Scopes: WRITE
- Copy Client ID and Client Secret

### 3. GCP resources

```bash
bash cru/setup-gcp.sh
```

Creates Firestore database, Artifact Registry repo, Secret Manager secret, and IAM bindings.

### 4. Build and push

```bash
docker build --platform linux/amd64 -f cru/Dockerfile \
  -t us-central1-docker.pkg.dev/cru-mattdrees-sandbox-poc/mcp-atlassian/mcp-atlassian:latest .

gcloud auth configure-docker us-central1-docker.pkg.dev
docker push us-central1-docker.pkg.dev/cru-mattdrees-sandbox-poc/mcp-atlassian/mcp-atlassian:latest
```

### 5. Deploy

```bash
bash cru/deploy.sh
```

### 6. Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "jira": {
      "url": "https://mcp-atlassian-178891842216.us-east4.run.app/mcp"
    }
  }
}
```

First connection triggers OAuth — you'll be redirected to Jira to authorize.

## Redeploying after code changes

```bash
docker build --platform linux/amd64 -f cru/Dockerfile \
  -t us-central1-docker.pkg.dev/cru-mattdrees-sandbox-poc/mcp-atlassian/mcp-atlassian:latest .
docker push us-central1-docker.pkg.dev/cru-mattdrees-sandbox-poc/mcp-atlassian/mcp-atlassian:latest
bash cru/deploy.sh
```

## Key details

| Item | Value |
|---|---|
| GCP project | `cru-mattdrees-sandbox-poc` (project number: 178891842216) |
| Region | us-east4 |
| Shared VPC host | `cru-shared-vpc-host-prod-2` |
| Subnet | `stage-1` (10.37.128.0/24, us-east4) |
| Jira DC | jira.cru.org → 10.16.0.74 (AWS internal) |
| Jira DC version | v10.7.4 |
| Service URL | https://mcp-atlassian-178891842216.us-east4.run.app |
| Firestore | native mode, us-east1 |
| Service account | mcp-atlassian@cru-mattdrees-sandbox-poc.iam.gserviceaccount.com |

## Gotchas

- **`/healthz` returns Google 404**: Cloud Run's GFE intercepts this path. Use `/mcp` (returns 401 with OAuth challenge) to verify the app is running.
- **`egress-internal` network tag**: Required on the Cloud Run service for the shared VPC firewall to allow egress to Jira (10.16.x.x). Without it, token exchange times out silently.
- **DNS not available**: Cloud Run in the shared VPC can't resolve `jira.cru.org` (AWS internal DNS). The `RESOLVE_HOST_ENTRY` env var injects `/etc/hosts` entries via the entrypoint script.
- **`--platform linux/amd64`**: Required when building on Apple Silicon. Without it, Cloud Run fails with `exec format error`.
- **VPC egress must be `private-ranges-only`**: `all-traffic` routes Google API calls (Firestore gRPC) through the VPC which lacks Private Google Access. `private-ranges-only` routes only Jira traffic (10.x.x.x) through the VPC while Google APIs go direct.
- **`google-cloud-firestore` must be installed into the venv**: The base image uses `/app/.venv`. System-level `pip install` won't be visible. Use `uv pip install --python=/app/.venv/bin/python` in the Dockerfile.
