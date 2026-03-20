#!/usr/bin/env python3
"""Lightweight CLI for inspecting Firestore documents in the mcp-atlassian DB.

Uses the REST API with gcloud auth tokens, so no ADC setup is needed —
just a valid `gcloud auth print-access-token`.

Usage:
    python cru/fsquery.py collections
    python cru/fsquery.py docs <collection>
    python cru/fsquery.py doc <collection> <doc_id>
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

PROJECT = "cru-mattdrees-sandbox-poc"
DATABASE = "(default)"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/{DATABASE}/documents"


def _get_token() -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Failed to get gcloud token:", result.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _request(method: str, url: str, token: str, body: dict | None = None) -> Any:
    import urllib.request

    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _decode_value(v: dict) -> Any:
    """Convert a Firestore REST value to a Python value."""
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "booleanValue" in v:
        return v["booleanValue"]
    if "nullValue" in v:
        return None
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [_decode_value(item) for item in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return {
            k: _decode_value(fv)
            for k, fv in v["mapValue"].get("fields", {}).items()
        }
    return v


def _decode_fields(fields: dict) -> dict:
    return {k: _decode_value(v) for k, v in fields.items()}


def _format_ttl(expires_at_str: str | None) -> str:
    """Return a human-readable remaining TTL from an ISO timestamp string."""
    if not expires_at_str:
        return "no expiry"
    try:
        exp = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        remaining = exp - datetime.now(tz=timezone.utc)
        total_seconds = remaining.total_seconds()
        if total_seconds <= 0:
            return "EXPIRED"
        days = int(total_seconds // 86400)
        hours = int((total_seconds % 86400) // 3600)
        mins = int((total_seconds % 3600) // 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if mins:
            parts.append(f"{mins}m")
        return " ".join(parts) or "<1m"
    except (ValueError, TypeError):
        return str(expires_at_str)


def cmd_collections(token: str) -> None:
    data = _request("POST", f"{BASE}:listCollectionIds", token, {})
    for cid in data.get("collectionIds", []):
        print(cid)


def cmd_docs(token: str, collection: str) -> None:
    data = _request("GET", f"{BASE}/{collection}?pageSize=100", token)
    docs = data.get("documents", [])
    if not docs:
        print("(no documents)")
        return
    for doc in docs:
        doc_id = doc["name"].rsplit("/", 1)[-1]
        fields = _decode_fields(doc.get("fields", {}))
        expires_at = fields.get("expires_at")
        ttl_str = _format_ttl(expires_at)
        # Show a compact summary
        value = fields.get("value", {})
        summary_parts = [f"id={doc_id}"]
        summary_parts.append(f"ttl={ttl_str}")
        # Pull out useful identifiers from value
        for key in ("client_id", "client_name", "upstream_token_id", "jti"):
            if key in value:
                val = value[key]
                if isinstance(val, str) and len(val) > 16:
                    val = val[:12] + "..."
                summary_parts.append(f"{key}={val}")
        created = doc.get("createTime", "")[:19]
        if created:
            summary_parts.append(f"created={created}")
        print("  ".join(summary_parts))


def cmd_doc(token: str, collection: str, doc_id: str) -> None:
    url = f"{BASE}/{collection}/{doc_id}"
    data = _request("GET", url, token)
    fields = _decode_fields(data.get("fields", {}))
    # Annotate expires_at with remaining TTL
    expires_at = fields.get("expires_at")
    output = {
        "_meta": {
            "doc_id": doc_id,
            "created": data.get("createTime"),
            "updated": data.get("updateTime"),
            "ttl_remaining": _format_ttl(expires_at),
        },
        **fields,
    }
    print(json.dumps(output, indent=2, default=str))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    cmd = sys.argv[1]
    token = _get_token()

    if cmd == "collections":
        cmd_collections(token)
    elif cmd == "docs" and len(sys.argv) >= 3:
        cmd_docs(token, sys.argv[2])
    elif cmd == "doc" and len(sys.argv) >= 4:
        cmd_doc(token, sys.argv[2], sys.argv[3])
    else:
        print(__doc__.strip())
        sys.exit(1)


if __name__ == "__main__":
    main()
