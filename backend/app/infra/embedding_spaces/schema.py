"""Physical pgvector table and ANN-index management."""

from __future__ import annotations

import re

from sqlalchemy import text

from app.infra.database.database import PostgresDatabase
from app.infra.embedding_spaces.contracts import EmbeddingSpaceRecord

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class VectorSchemaManager:
    """Create and validate one physical table/index for a registered space."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def ensure_table(self, space: EmbeddingSpaceRecord) -> None:
        table = _quoted_identifier(space.table_name)
        dimensions = space.spec.dimensions
        ddl = f"""
            CREATE TABLE IF NOT EXISTS public.{table} (
                langchain_id TEXT PRIMARY KEY,
                collection_name TEXT NOT NULL DEFAULT 'documents',
                content TEXT NOT NULL,
                embedding vector({dimensions}) NOT NULL,
                langchain_metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """
        collection_index = _quoted_identifier(
            _index_name(space.table_name, "collection")
        )
        metadata_index = _quoted_identifier(
            _index_name(space.table_name, "metadata")
        )
        async with self._database.engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.execute(text(ddl))
            await connection.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS {collection_index}
                    ON public.{table} (collection_name)
                    """
                )
            )
            await connection.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS {metadata_index}
                    ON public.{table}
                    USING gin (langchain_metadata jsonb_path_ops)
                    """
                )
            )
        await self.validate_table(space)

    async def validate_table(self, space: EmbeddingSpaceRecord) -> None:
        result = await self._database.execute_query(
            text(
                """
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
            {"table_name": space.table_name},
        )
        actual_type = result.scalar_one_or_none()
        expected_type = f"vector({space.spec.dimensions})"
        if actual_type != expected_type:
            raise RuntimeError(
                "Embedding generation table has an incompatible vector type "
                f"(table={space.table_name}, expected={expected_type}, "
                f"actual={actual_type or 'missing'})"
            )

    async def ensure_search_index(self, space: EmbeddingSpaceRecord) -> bool:
        if space.spec.index_kind == "exact":
            return False

        table = _quoted_identifier(space.table_name)
        index_name = _quoted_identifier(_index_name(space.table_name, "ann"))
        dimensions = space.spec.dimensions
        if space.spec.index_kind == "hnsw_halfvec":
            target = f"((embedding::halfvec({dimensions})) halfvec_cosine_ops)"
        else:
            target = "(embedding vector_cosine_ops)"

        async with self._database.engine.begin() as connection:
            await connection.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS {index_name}
                    ON public.{table}
                    USING hnsw {target}
                    """
                )
            )
        return True

    async def count_rows(self, space: EmbeddingSpaceRecord) -> int:
        table = _quoted_identifier(space.table_name)
        result = await self._database.execute_query(
            text(f"SELECT COUNT(1) FROM public.{table}")
        )
        return int(result.scalar_one())

    async def validate_single_generation_query(
        self,
        space: EmbeddingSpaceRecord,
    ) -> None:
        """Probe only the candidate table; never compose generations."""

        table = _quoted_identifier(space.table_name)
        await self._database.execute_query(
            text(
                f"""
                SELECT embedding <=> embedding AS self_distance
                FROM public.{table}
                LIMIT 1
                """
            )
        )

    async def clear_rows(self, space: EmbeddingSpaceRecord) -> None:
        """Clear only a non-active build target before a retry."""

        if space.status == "active":
            raise RuntimeError("Active embedding generations cannot be cleared")
        table = _quoted_identifier(space.table_name)
        async with self._database.engine.begin() as connection:
            await connection.execute(text(f"DELETE FROM public.{table}"))


def quoted_generation_table(table_name: str) -> str:
    """Validate a registry-issued table name before interpolating SQL."""

    return _quoted_identifier(table_name)


def _quoted_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe PostgreSQL identifier: {value!r}")
    return f'"{value}"'


def _index_name(table_name: str, suffix: str) -> str:
    return f"{table_name}_{suffix}_idx"[:63]


__all__ = ["VectorSchemaManager", "quoted_generation_table"]
