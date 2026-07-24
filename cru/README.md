# CRU mcp-atlassian Cloud Run Deployment

Remote MCP server for Jira Data Center (jira.cru.org) with per-user OAuth.

## Architecture

- Cloud Run service in `us-east4` with Direct VPC Egress through the shared VPC
- OAuth proxy (FastMCP) handles per-user OAuth against Jira DC
- Firestore stores OAuth tokens so they survive instance restarts
- Jira is reached via its public hostname `jira.cru.org` (public ALB since 2026-07). The
  VPC attachment (`egress-internal` tag, shared VPC subnet) is a leftover from when Jira
  was internal-only and could now be removed.

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
| Jira DC | jira.cru.org (public ALB; was AWS-internal until 2026-07) |
| Jira DC version | v10.7.4 |
| Service URL | https://mcp-atlassian-178891842216.us-east4.run.app |
| Firestore | native mode, us-east1 |
| Service account | mcp-atlassian@cru-mattdrees-sandbox-poc.iam.gserviceaccount.com |

## Gotchas

- **`/healthz` returns Google 404**: Cloud Run's GFE intercepts this path. Use `/mcp` (returns 401 with OAuth challenge) to verify the app is running.
- **Jira went public (2026-07)**: `jira.cru.org` now resolves to public ALB IPs, and the
  `jira.aws.cru.org` private-zone records were deleted. `JIRA_URL` must be
  `https://jira.cru.org`. The old workarounds (`RESOLVE_HOST_ENTRY` /etc/hosts injection,
  `egress-internal` tag for 10.16.x.x egress, `jira.aws.cru.org` private DNS) are obsolete.
- **`--platform linux/amd64`**: Required when building on Apple Silicon. Without it, Cloud Run fails with `exec format error`.
- **VPC egress must be `private-ranges-only`**: `all-traffic` routes Google API calls (Firestore gRPC) and now Jira's public IPs through the VPC, which lacks Private Google Access / internet NAT. `private-ranges-only` sends public destinations (Google APIs, jira.cru.org) direct.
- **`google-cloud-firestore` must be installed into the venv**: The base image uses `/app/.venv`. System-level `pip install` won't be visible. Use `uv pip install --python=/app/.venv/bin/python` in the Dockerfile.
