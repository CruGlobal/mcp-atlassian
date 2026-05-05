# syntax=docker/dockerfile:1
# Layers CRU-specific bits (Firestore store, /etc/hosts injection) on top of
# the upstream published image. Upstream now ships the OAuth proxy +
# client_storage code (since v0.21.1), so building from source is no longer
# required.
#
# Build from repo root:
#   docker buildx build --platform linux/amd64 -f cru/Dockerfile -t mcp-atlassian-cru .

FROM ghcr.io/astral-sh/uv:latest AS uv-bin

FROM ghcr.io/sooperset/mcp-atlassian:0.21.1

USER root

# Install su-exec for the entrypoint and google-cloud-firestore into the venv.
COPY --from=uv-bin /uv /usr/local/bin/uv
RUN apk add --no-cache su-exec && \
    uv pip install --python=/app/.venv/bin/python google-cloud-firestore && \
    rm /usr/local/bin/uv && \
    find /app/.venv -name '__pycache__' -type d -exec rm -rf {} + && \
    find /app/.venv -name '*.pyc' -delete

COPY cru/firestore_store /app/firestore_store
COPY cru/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app

ENTRYPOINT ["/entrypoint.sh"]
