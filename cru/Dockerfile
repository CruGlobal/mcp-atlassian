# Extends the upstream mcp-atlassian image with a Firestore-backed
# AsyncKeyValue store for OAuth token persistence on Cloud Run.
#
# Build from repo root:
#   docker build -f cru/Dockerfile -t mcp-atlassian-cru .
#
# Or targeting Artifact Registry:
#   docker build -f cru/Dockerfile \
#     -t us-central1-docker.pkg.dev/cru-mattdrees-sandbox-poc/mcp-atlassian/mcp-atlassian:latest .

FROM ghcr.io/sooperset/mcp-atlassian:latest

USER root

RUN pip install --no-cache-dir google-cloud-firestore

# Copy the Firestore store module so it's importable as `firestore_store`
COPY cru/firestore_store /app/firestore_store

ENV PYTHONPATH=/app

# Entrypoint wrapper runs as root so it can write to /etc/hosts, then execs
# mcp-atlassian as the app user via su-exec.
RUN apk add --no-cache su-exec
COPY cru/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Note: stays as root so entrypoint.sh can modify /etc/hosts;
# the script drops to app via su-exec before exec'ing mcp-atlassian.
ENTRYPOINT ["/entrypoint.sh"]
