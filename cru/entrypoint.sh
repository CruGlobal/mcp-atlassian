#!/bin/sh
set -eu

# Equivalent of curl --resolve: inject a hosts entry before starting the server.
# e.g. RESOLVE_HOST_ENTRY="10.16.0.74 jira.cru.org". Obsolete since jira.cru.org
# went public (2026-07); kept as an escape hatch.
if [ -n "${RESOLVE_HOST_ENTRY:-}" ]; then
    echo "$RESOLVE_HOST_ENTRY" >> /etc/hosts
fi

exec su-exec app mcp-atlassian "$@"
