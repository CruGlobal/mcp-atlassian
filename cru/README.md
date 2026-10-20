# CRU mcp-atlassian Cloud Run Deployment

Remote MCP server for Jira Data Center (jira.cru.org) with per-user OAuth.

## Architecture

- Cloud Run service in `us-east4`, no VPC attachment
- OAuth proxy (FastMCP) handles per-user OAuth against Jira DC
- Firestore stores OAuth tokens so they survive instance restarts
- Jira is reached via its public hostname `jira.cru.org` (public ALB since 2026-07). The
  shared VPC attachment from when Jira was internal-only was removed 2026-10-20.

## Setup from scratch

### 1. Terraform (cru-terraform repo)

Apply `google/projects/mattdrees-sandbox/service-accounts.tf` to create:
- `mcp-atlassian` service account
- (obsolete) `compute.networkUser` on the `stage-1` subnet for the SA and Cloud Run service
  agent; unused since the VPC attachment was removed

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

## Rotating OAuth credentials

Creds expire periodically (next: **2026-11-01**; recurring calendar reminder set).
There is no REST API for this — Jira DC has never shipped one
([JRASERVER-61753](https://jira.atlassian.com/browse/JRASERVER-61753), open since 2016),
so step 1 is manual.

1. **Jira admin**: regenerate the secret on the *existing* incoming application link
   rather than recreating the link — that keeps the client id stable. If the link is
   recreated, Jira reissues **both** values.
2. Add whichever values changed (`printf`, not `echo` — a trailing newline breaks it):
   ```bash
   printf '%s' NEW_ID     | gcloud secrets versions add jira-oauth-client-id     --data-file=- --project=cru-mattdrees-sandbox-poc
   printf '%s' NEW_SECRET | gcloud secrets versions add jira-oauth-client-secret --data-file=- --project=cru-mattdrees-sandbox-poc
   ```
3. `bash cru/deploy.sh` — both are wired to `:latest`, so this is a config change only.
4. Reconnect in claude.ai, then confirm `/callback` returns 302 (not 500):
   ```bash
   gcloud logging read 'resource.labels.service_name="mcp-atlassian" AND httpRequest.requestUrl:"/callback?code="' \
     --project=cru-mattdrees-sandbox-poc --limit=5 --format='value(timestamp,httpRequest.status)'
   ```

All users must re-authorize afterwards — stored upstream tokens are bound to the old
client id. A stale client id fails with the *same* `invalid_client` error as a stale
secret, so check both before assuming the secret is wrong.

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
- **No VPC**: if one is ever re-added, egress must be `private-ranges-only`. `all-traffic`
  routes Firestore gRPC and Jira's public IPs through the shared VPC, which lacks Private
  Google Access / internet NAT.
- **Firestore TTL policies**: `FirestoreStore` writes a Timestamp `expires_at` on every
  entry given a TTL, but Firestore only garbage-collects it if a TTL policy exists on the
  field. `setup-gcp.sh` now creates them for the six `mcp_atlassian_*` collection groups.
  Deletion is a background sweep — expect up to 24h, and reads already treat expired
  entries as missing, so lag is harmless.
- **DCR client registrations grow unbounded**: FastMCP's `_client_store.put()` passes no
  `ttl`, so `mcp_atlassian_mcp-oauth-proxy-clients` docs have `expires_at = null` and no
  TTL policy can collect them. Each client reconnect writes a new one. Prune manually if
  it gets large.
- **`google-cloud-firestore` must be installed into the venv**: The base image uses `/app/.venv`. System-level `pip install` won't be visible. Use `uv pip install --python=/app/.venv/bin/python` in the Dockerfile.
