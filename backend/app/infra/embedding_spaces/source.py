"""Read dimension-free documents from an earlier vector generation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from app.infra.database.database import PostgresDatabase
from app.infra.embedding_spaces.contracts import VectorSourceDocument
from app.infra.embedding_spaces.schema import quoted_generation_table


class VectorSourceReader:
    """Expose source rows without knowing how they will be embedded."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def table_exists(self, table_name: str | None) -> bool:
        if not table_name:
            return False
        quoted_generation_table(table_name)
        result = await self._database.execute_query(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                )
                """
            ),
            {"table_name": table_name},
        )
        return bool(result.scalar_one())

    async def count(self, table_name: str | None) -> int:
        if not await self.table_exists(table_name):
            return 0
        assert table_name is not None
        table = quoted_generation_table(table_name)
        result = await self._database.execute_query(
            text(f"SELECT COUNT(1) FROM public.{table}")
        )
        return int(result.scalar_one())

    async def read_batch(
        self,
        table_name: str | None,
        *,
        offset: int,
        limit: int,
    ) -> list[VectorSourceDocument]:
        if not await self.table_exists(table_name):
            return []
        assert table_name is not None
        table = quoted_generation_table(table_name)
        has_collection = await self._has_column(table_name, "collection_name")
        collection_sql = (
            "collection_name"
            if has_collection
            else "'documents'::text AS collection_name"
        )
        result = await self._database.execute_query(
            text(
                f"""
                SELECT
                    langchain_id::text AS langchain_id,
                    {collection_sql},
                    content,
                    langchain_metadata
                FROM public.{table}
                ORDER BY langchain_id::text
                OFFSET :offset
                LIMIT :limit
                """
            ),
            {
                "offset": offset,
                "limit": limit,
            },
        )
        return [
            VectorSourceDocument(
                id=str(row["langchain_id"]),
                collection_name=str(row["collection_name"] or "documents"),
                content=str(row["content"] or ""),
                metadata=dict(row["langchain_metadata"] or {}),
            )
            for row in result.mappings().all()
        ]

    async def read_updated_batch(
        self,
        table_name: str | None,
        *,
        updated_since: datetime,
        offset: int,
        limit: int,
    ) -> list[VectorSourceDocument]:
        if not await self.table_exists(table_name):
            return []
        assert table_name is not None
        if not await self._has_column(table_name, "updated_at"):
            return []
        table = quoted_generation_table(table_name)
        has_collection = await self._has_column(table_name, "collection_name")
        collection_sql = (
            "collection_name"
            if has_collection
            else "'documents'::text AS collection_name"
        )
        result = await self._database.execute_query(
            text(
                f"""
                SELECT
                    langchain_id::text AS langchain_id,
                    {collection_sql},
                    content,
                    langchain_metadata
                FROM public.{table}
                WHERE updated_at >= :updated_since
                ORDER BY updated_at, langchain_id::text
                OFFSET :offset
                LIMIT :limit
                """
            ),
            {
                "updated_since": updated_since,
                "offset": offset,
                "limit": limit,
            },
        )
        return [
            VectorSourceDocument(
                id=str(row["langchain_id"]),
                collection_name=str(row["collection_name"] or "documents"),
                content=str(row["content"] or ""),
                metadata=dict(row["langchain_metadata"] or {}),
            )
            for row in result.mappings().all()
        ]

    async def watermark(self) -> datetime:
        result = await self._database.execute_query(
            text("SELECT clock_timestamp()")
        )
        return result.scalar_one()

    async def _has_column(self, table_name: str, column_name: str) -> bool:
        result = await self._database.execute_query(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                      AND column_name = :column_name
                )
                """
            ),
            {
                "table_name": table_name,
                "column_name": column_name,
            },
        )
        return bool(result.scalar_one())


__all__ = ["VectorSourceReader"]
