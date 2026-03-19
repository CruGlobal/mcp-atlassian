# syntax=docker/dockerfile:1
# Builds mcp-atlassian from source (to get client_storage factory support)
# with Firestore backend and /etc/hosts injection for Cloud Run.
#
# Build from repo root:
#   docker buildx build --platform linux/amd64 -f cru/Dockerfile -t mcp-atlassian-cru .

# --- Build stage ---
FROM ghcr.io/astral-sh/uv:python3.13-alpine AS uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install dependencies first (cached layer)
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --no-editable

# Copy source and install project
COPY . /app
RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Install Firestore into the venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python=/app/.venv/bin/python google-cloud-firestore

# Clean up bytecode
RUN find /app/.venv -name '__pycache__' -type d -exec rm -rf {} + && \
    find /app/.venv -name '*.pyc' -delete && \
    find /app/.venv -name '*.pyo' -delete

# --- Final stage ---
FROM python:3.13-alpine

RUN adduser -D -h /home/app -s /bin/sh app
RUN apk add --no-cache su-exec
WORKDIR /app

COPY --from=uv --chown=app:app /app/.venv /app/.venv

# Copy the Firestore store module
COPY cru/firestore_store /app/firestore_store

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

COPY cru/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
