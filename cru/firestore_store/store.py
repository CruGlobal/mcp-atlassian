"""Firestore-backed AsyncKeyValue store for mcp-atlassian OAuth token persistence.

Implements the AsyncKeyValue protocol from py_key_value_aio so it can be plugged
in via ATLASSIAN_OAUTH_CLIENT_STORAGE_MODE=factory.

Firestore document layout per entry:
    {collection_prefix}{collection}/{key}:
        value:      dict   — the payload (stored as a Firestore map)
        expires_at: Timestamp | null — used by Firestore TTL policy for background GC

TTL notes:
  - expires_at is set on write when a ttl (seconds) is provided.
  - Reads check expires_at locally and treat expired entries as missing.
  - The Firestore TTL policy (configured on the expires_at field) handles
    background deletion; it runs on a delay so local expiry checks are required.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, SupportsFloat

from google.cloud import firestore

logger = logging.getLogger(__name__)

_EXPIRES_AT_FIELD = "expires_at"
_VALUE_FIELD = "value"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _expires_at_from_ttl(ttl: SupportsFloat) -> datetime:
    return _now() + timedelta(seconds=float(ttl))


def _is_expired(doc_data: dict[str, Any]) -> bool:
    expires_at: datetime | None = doc_data.get(_EXPIRES_AT_FIELD)
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= _now()


def _remaining_ttl(doc_data: dict[str, Any]) -> float | None:
    expires_at: datetime | None = doc_data.get(_EXPIRES_AT_FIELD)
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return max(0.0, (expires_at - _now()).total_seconds())


class FirestoreStore:
    """AsyncKeyValue backed by Google Cloud Firestore.

    Each (collection, key) pair maps to a Firestore document at
    {collection_prefix}{collection}/{key}.  The document stores the payload
    dict under a "value" field and an optional "expires_at" timestamp.

    Args:
        project_id: GCP project containing the Firestore database.
        database: Firestore database ID (default: "(default)").
        collection_prefix: String prepended to every collection name, useful
            for namespacing multiple logical stores in one database.
    """

    def __init__(
        self,
        *,
        project_id: str,
        database: str = "(default)",
        collection_prefix: str = "mcp_atlassian_",
    ) -> None:
        self._project_id = project_id
        self._database = database
        self._collection_prefix = collection_prefix
        self._client: firestore.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> firestore.AsyncClient:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = firestore.AsyncClient(
                        project=self._project_id,
                        database=self._database,
                    )
        return self._client

    def _col_ref(
        self, client: firestore.AsyncClient, collection: str | None
    ) -> firestore.AsyncCollectionReference:
        col_name = f"{self._collection_prefix}{collection or 'default'}"
        return client.collection(col_name)

    # ------------------------------------------------------------------
    # Single-key operations
    # ------------------------------------------------------------------

    async def get(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> dict[str, Any] | None:
        client = await self._get_client()
        doc = await self._col_ref(client, collection).document(key).get()
        if not doc.exists:
            return None
        data: dict[str, Any] = doc.to_dict() or {}
        if _is_expired(data):
            return None
        return data.get(_VALUE_FIELD)

    async def put(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        client = await self._get_client()
        doc_data: dict[str, Any] = {_VALUE_FIELD: dict(value)}
        if ttl is not None:
            doc_data[_EXPIRES_AT_FIELD] = _expires_at_from_ttl(ttl)
        else:
            doc_data[_EXPIRES_AT_FIELD] = None
        await self._col_ref(client, collection).document(key).set(doc_data)

    async def delete(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> bool:
        client = await self._get_client()
        ref = self._col_ref(client, collection).document(key)
        doc = await ref.get()
        if not doc.exists:
            return False
        await ref.delete()
        return True

    async def ttl(
        self,
        key: str,
        *,
        collection: str | None = None,
    ) -> tuple[dict[str, Any] | None, float | None]:
        client = await self._get_client()
        doc = await self._col_ref(client, collection).document(key).get()
        if not doc.exists:
            return (None, None)
        data: dict[str, Any] = doc.to_dict() or {}
        if _is_expired(data):
            return (None, None)
        value: dict[str, Any] | None = data.get(_VALUE_FIELD)
        return (value, _remaining_ttl(data))

    # ------------------------------------------------------------------
    # Bulk operations (sequential fallbacks — sufficient for low traffic)
    # ------------------------------------------------------------------

    async def get_many(
        self,
        keys: Sequence[str],
        *,
        collection: str | None = None,
    ) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        client = await self._get_client()
        col = self._col_ref(client, collection)
        refs = [col.document(k) for k in keys]
        docs = await client.get_all(refs)
        # get_all returns docs in arbitrary order; build a lookup by doc id
        by_id: dict[str, dict[str, Any]] = {}
        async for doc in docs:
            if doc.exists:
                data: dict[str, Any] = doc.to_dict() or {}
                if not _is_expired(data):
                    by_id[doc.id] = data.get(_VALUE_FIELD) or {}
        return [by_id.get(k) for k in keys]

    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        if len(keys) != len(values):
            raise ValueError("put_many: keys and values must have equal length")
        client = await self._get_client()
        col = self._col_ref(client, collection)
        expires_at = _expires_at_from_ttl(ttl) if ttl is not None else None
        batch = client.batch()
        for key, value in zip(keys, values):
            doc_data: dict[str, Any] = {
                _VALUE_FIELD: dict(value),
                _EXPIRES_AT_FIELD: expires_at,
            }
            batch.set(col.document(key), doc_data)
        await batch.commit()

    async def delete_many(
        self,
        keys: Sequence[str],
        *,
        collection: str | None = None,
    ) -> int:
        if not keys:
            return 0
        client = await self._get_client()
        col = self._col_ref(client, collection)
        # Check existence first so we can return an accurate count
        refs = [col.document(k) for k in keys]
        docs = await client.get_all(refs)
        existing_ids: set[str] = set()
        async for doc in docs:
            if doc.exists:
                existing_ids.add(doc.id)
        if not existing_ids:
            return 0
        batch = client.batch()
        for key in keys:
            if key in existing_ids:
                batch.delete(col.document(key))
        await batch.commit()
        return len(existing_ids)

    async def ttl_many(
        self,
        keys: Sequence[str],
        *,
        collection: str | None = None,
    ) -> list[tuple[dict[str, Any] | None, float | None]]:
        if not keys:
            return []
        client = await self._get_client()
        col = self._col_ref(client, collection)
        refs = [col.document(k) for k in keys]
        docs = await client.get_all(refs)
        by_id: dict[str, tuple[dict[str, Any] | None, float | None]] = {}
        async for doc in docs:
            if doc.exists:
                data: dict[str, Any] = doc.to_dict() or {}
                if not _is_expired(data):
                    by_id[doc.id] = (data.get(_VALUE_FIELD), _remaining_ttl(data))
        return [by_id.get(k, (None, None)) for k in keys]


def create_store(config: dict[str, Any] | None = None) -> FirestoreStore:
    """Factory function for ATLASSIAN_OAUTH_CLIENT_STORAGE_FACTORY.

    Config keys (all optional except project_id):
        project_id:        GCP project ID (required)
        database:          Firestore database ID (default: "(default)")
        collection_prefix: Prefix for Firestore collection names
                           (default: "mcp_atlassian_")
    """
    cfg = config or {}
    project_id: str | None = cfg.get("project_id")
    if not project_id:
        raise ValueError(
            "FirestoreStore requires 'project_id' in "
            "ATLASSIAN_OAUTH_CLIENT_STORAGE_CONFIG_JSON"
        )
    return FirestoreStore(
        project_id=project_id,
        database=cfg.get("database", "(default)"),
        collection_prefix=cfg.get("collection_prefix", "mcp_atlassian_"),
    )
