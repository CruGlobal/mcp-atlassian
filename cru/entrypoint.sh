#!/bin/sh
set -eu

# Equivalent of curl --resolve: inject a hosts entry before starting the server.
# Set RESOLVE_HOST_ENTRY="10.16.0.74 jira.cru.org jira.aws.cru.org" to use it.
if [ -n "${RESOLVE_HOST_ENTRY:-}" ]; then
    echo "$RESOLVE_HOST_ENTRY" >> /etc/hosts
fi

exec su-exec app mcp-atlassian "$@"
