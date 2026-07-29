"""Generation-bound PostgreSQL vector repository.

The public class keeps the historical application API, but no longer assumes
one global table or dimension.  Every instance is bound to an embedding-space
generation whose physical schema has already been created and validated.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from sqlalchemy import text

from app.infra.database.database import PostgresDatabase
from app.infra.embedding_spaces.contracts import EmbeddingPurpose, VectorIndexKind
from app.infra.embedding_spaces.locks import generation_write_lock
from app.infra.embedding_spaces.schema import quoted_generation_table
from app.infra.errors import VectorStoreError

logger = logging.getLogger(__name__)

_DEFAULT_TABLE = "langchain_pg_embedding"
_VECTOR_TYPE = re.compile(r"^vector\((\d+)\)$")


def build_ttl_filter(
    expires_at_field: str = "expires_at",
) -> dict[str, Any]:
    """Build a metadata filter that excludes expired documents."""

    now = datetime.now(timezone.utc).isoformat()
    return {
        "$or": [
            {expires_at_field: {"$exists": False}},
            {expires_at_field: {"$gt": now}},
        ]
    }


def build_expires_at_metadata(
    ttl_days: Optional[int] = None,
    ttl_hours: Optional[int] = None,
    expires_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build optional expiration metadata."""

    if expires_at is not None:
        return {"expires_at": expires_at.isoformat()}
    if ttl_days is not None:
        return {
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(days=ttl_days)
            ).isoformat()
        }
    if ttl_hours is not None:
        return {
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            ).isoformat()
        }
    return {}


class PGVectorVectorstore:
    """Search and write one explicit embedding generation."""

    def __init__(
        self,
        table_name: str = _DEFAULT_TABLE,
        *,
        database: PostgresDatabase | None = None,
        dimensions: int | None = None,
        index_kind: VectorIndexKind = "exact",
        space_fingerprint: str = "",
        purpose: EmbeddingPurpose = "documents",
        enforce_active_write: bool = False,
    ) -> None:
        self._table_name = table_name
        self._database = database
        self._dimensions = dimensions
        self._index_kind = index_kind
        self._space_fingerprint = space_fingerprint
        self._purpose = purpose
        self._enforce_active_write = enforce_active_write
        self._embeddings: Embeddings | None = None
        self._initialized = False

    def set_embed_fn(
        self,
        embed_fn=None,
        embed_batch_fn=None,
        embeddings: Embeddings | None = None,
    ) -> None:
        if embeddings is not None:
            self._embeddings = embeddings
        elif embed_fn is not None:
            self._embeddings = _FunctionEmbeddingsAdapter(
                embed_fn=embed_fn,
                embed_batch_fn=embed_batch_fn,
            )

    @property
    def store(self) -> "PGVectorVectorstore":
        """Compatibility view for callers that previously accessed LangChain."""

        if not self._initialized:
            raise RuntimeError("Vectorstore not initialized. Call initialize() first.")
        return self

    @property
    def table_name(self) -> str:
        return self._table_name

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            raise RuntimeError("Vectorstore dimensions are unknown")
        return self._dimensions

    @property
    def space_fingerprint(self) -> str:
        return self._space_fingerprint

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._embeddings is None:
            raise VectorStoreError(
                "No embedding function configured",
                operation="initialize",
            )
        if self._database is None:
            from app.infra.database.factory import get_database

            self._database = get_database()

        table = quoted_generation_table(self._table_name)
        result = await self._database.execute_query(
            text(
                f"""
                SELECT format_type(attribute.atttypid, attribute.atttypmod)
                FROM pg_attribute AS attribute
                JOIN pg_class AS relation
                  ON relation.oid = attribute.attrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relname = :table_name
                  AND attribute.attname = 'embedding'
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                """
            ),
            {"table_name": self._table_name},
        )
        actual_type = result.scalar_one_or_none()
        match = _VECTOR_TYPE.fullmatch(str(actual_type or ""))
        if match is None:
            raise VectorStoreError(
                f"Table {self._table_name!r} has no fixed vector column",
                operation="initialize",
            )
        actual_dimensions = int(match.group(1))
        if self._dimensions is not None and actual_dimensions != self._dimensions:
            raise VectorStoreError(
                "Vector table dimension does not match its embedding space "
                f"(expected={self._dimensions}, actual={actual_dimensions})",
                operation="initialize",
            )
        self._dimensions = actual_dimensions
        self._initialized = True
        logger.info(
            "Generation vectorstore initialized: table=%s dimensions=%d "
            "index_kind=%s space=%s",
            self._table_name,
            actual_dimensions,
            self._index_kind,
            self._space_fingerprint[:12] or "legacy",
        )

    async def search(
        self,
        collection_name: str,
        query_text: str,
        limit: int = 5,
        filter: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        self._require_ready("search")
        assert self._embeddings is not None
        try:
            embedding = await self._embeddings.aembed_query(query_text)
            return await self.search_with_embedding(
                collection_name=collection_name,
                embedding=embedding,
                limit=limit,
                filter=filter,
            )
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(
                f"Vector search failed: {exc}",
                collection_name=collection_name,
                operation="search",
            ) from exc

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
        filter: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        self._require_ready("search_with_embedding")
        vector = _validate_vector(embedding, self.dimensions)
        assert self._database is not None
        table = quoted_generation_table(self._table_name)
        distance_expression, query_cast = _distance_sql(
            index_kind=self._index_kind,
            dimensions=self.dimensions,
        )
        fetch_limit = max(limit, limit * 5 if filter else limit)
        try:
            result = await self._database.execute_query(
                text(
                    f"""
                    SELECT
                        langchain_id,
                        content,
                        langchain_metadata,
                        1 - ({distance_expression}) AS score
                    FROM public.{table}
                    WHERE collection_name = :collection_name
                    ORDER BY {distance_expression}
                    LIMIT :limit
                    """.replace(":query_vector_cast", query_cast)
                ),
                {
                    "collection_name": collection_name,
                    "query_vector": _vector_literal(vector),
                    "limit": fetch_limit,
                },
            )
            rows = result.mappings().all()
        except Exception as exc:
            raise VectorStoreError(
                f"Vector search by embedding failed: {exc}",
                collection_name=collection_name,
                operation="search_with_embedding",
            ) from exc

        formatted: list[dict[str, Any]] = []
        for row in rows:
            metadata = dict(row["langchain_metadata"] or {})
            if filter and not _matches_filter(metadata, filter):
                continue
            formatted.append(
                {
                    "id": str(row["langchain_id"]),
                    "score": float(row["score"]),
                    "payload": {
                        "content": row["content"],
                        **{
                            key: value
                            for key, value in metadata.items()
                            if key not in ("id", "vector_id")
                        },
                    },
                }
            )
            if len(formatted) >= limit:
                break
        return formatted

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        self._require_ready("add_documents")
        if self._enforce_active_write:
            async with generation_write_lock(
                self._database_or_raise(),
                purpose=self._purpose,
                exclusive=False,
            ):
                await self._assert_active_generation()
                return await self._add_documents(
                    collection_name=collection_name,
                    documents=documents,
                    embeddings=embeddings,
                )
        return await self._add_documents(
            collection_name=collection_name,
            documents=documents,
            embeddings=embeddings,
        )

    async def _add_documents(
        self,
        *,
        collection_name: str,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        if len(documents) != len(embeddings):
            raise VectorStoreError(
                "Documents and embeddings must have the same length",
                collection_name=collection_name,
                operation="add_documents",
            )
        assert self._database is not None
        table = quoted_generation_table(self._table_name)
        ids: list[str] = []
        statement = text(
            f"""
            INSERT INTO public.{table} (
                langchain_id,
                collection_name,
                content,
                embedding,
                langchain_metadata,
                updated_at
            )
            VALUES (
                :langchain_id,
                :collection_name,
                :content,
                CAST(:embedding AS vector({self.dimensions})),
                CAST(:metadata AS jsonb),
                NOW()
            )
            ON CONFLICT (langchain_id)
            DO UPDATE SET
                collection_name = EXCLUDED.collection_name,
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                langchain_metadata = EXCLUDED.langchain_metadata,
                updated_at = NOW()
            """
        )
        try:
            async with self._database.session() as session:
                for document, raw_vector in zip(
                    documents,
                    embeddings,
                    strict=True,
                ):
                    vector = _validate_vector(raw_vector, self.dimensions)
                    document_id = str(document.get("id") or uuid4())
                    metadata = {
                        key: value
                        for key, value in document.items()
                        if key not in ("content", "embedding", "id")
                    }
                    await session.execute(
                        statement,
                        {
                            "langchain_id": document_id,
                            "collection_name": collection_name,
                            "content": str(document.get("content", "")),
                            "embedding": _vector_literal(vector),
                            "metadata": json.dumps(
                                metadata,
                                ensure_ascii=False,
                                default=str,
                            ),
                        },
                    )
                    ids.append(document_id)
        except Exception as exc:
            raise VectorStoreError(
                f"Failed to add documents: {exc}",
                collection_name=collection_name,
                operation="add_documents",
            ) from exc
        return ids

    def promote_to_active(self) -> None:
        """Require future writes to prove this generation is still active."""

        self._enforce_active_write = True

    async def dispose(self) -> None:
        self._initialized = False
        self._database = None

    def _require_ready(self, operation: str) -> None:
        if not self._initialized or self._database is None:
            raise VectorStoreError(
                "Vectorstore not initialized",
                operation=operation,
            )

    def _database_or_raise(self) -> PostgresDatabase:
        if self._database is None:
            raise VectorStoreError(
                "Vectorstore not initialized",
                operation="database",
            )
        return self._database

    async def _assert_active_generation(self) -> None:
        assert self._database is not None
        result = await self._database.execute_query(
            text(
                """
                SELECT spaces.table_name
                FROM public.embedding_space_bindings AS bindings
                JOIN public.embedding_spaces AS spaces
                  ON spaces.id = bindings.active_space_id
                WHERE bindings.purpose = :purpose
                """
            ),
            {"purpose": self._purpose},
        )
        active_table = result.scalar_one_or_none()
        if active_table != self._table_name:
            raise VectorStoreError(
                "Vector write targeted a stale embedding generation; "
                "resolve the active vectorstore and retry",
                operation="add_documents",
            )


class _FunctionEmbeddingsAdapter(Embeddings):
    def __init__(self, embed_fn, embed_batch_fn=None) -> None:
        self._embed_fn = embed_fn
        self._embed_batch_fn = embed_batch_fn

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Use aembed_documents()")

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError("Use aembed_query()")

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._embed_batch_fn:
            return await self._embed_batch_fn(texts)
        return [await self._embed_fn(text) for text in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return await self._embed_fn(text)


def _distance_sql(
    *,
    index_kind: VectorIndexKind,
    dimensions: int,
) -> tuple[str, str]:
    if index_kind == "hnsw_halfvec":
        query_cast = f"CAST(:query_vector AS halfvec({dimensions}))"
        return (
            f"(embedding::halfvec({dimensions})) <=> :query_vector_cast",
            query_cast,
        )
    query_cast = f"CAST(:query_vector AS vector({dimensions}))"
    return "embedding <=> :query_vector_cast", query_cast


def _validate_vector(vector: list[float], dimensions: int) -> list[float]:
    values = [float(value) for value in vector]
    if len(values) != dimensions:
        raise VectorStoreError(
            "Embedding dimension does not match the active generation "
            f"(expected={dimensions}, actual={len(values)})",
            operation="validate_embedding",
        )
    if any(not math.isfinite(value) for value in values):
        raise VectorStoreError(
            "Embedding contains a non-finite value",
            operation="validate_embedding",
        )
    return values


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(format(value, ".17g") for value in vector) + "]"


def _matches_filter(metadata: dict[str, Any], condition: dict[str, Any]) -> bool:
    if "$or" in condition:
        options = condition.get("$or")
        return isinstance(options, list) and any(
            isinstance(option, dict) and _matches_filter(metadata, option)
            for option in options
        )
    if "$and" in condition:
        options = condition.get("$and")
        return isinstance(options, list) and all(
            isinstance(option, dict) and _matches_filter(metadata, option)
            for option in options
        )
    for field, expected in condition.items():
        actual = metadata.get(field)
        if isinstance(expected, dict):
            if "$exists" in expected and (field in metadata) is not bool(
                expected["$exists"]
            ):
                return False
            if "$gt" in expected and not (
                actual is not None and str(actual) > str(expected["$gt"])
            ):
                return False
            if "$eq" in expected and actual != expected["$eq"]:
                return False
        elif actual != expected:
            return False
    return True


__all__ = [
    "PGVectorVectorstore",
    "_DEFAULT_TABLE",
    "build_expires_at_metadata",
    "build_ttl_filter",
]
