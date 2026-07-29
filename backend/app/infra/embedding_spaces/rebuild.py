"""Background-safe rebuild of one embedding-space generation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from langchain_core.embeddings import Embeddings

from app.infra.database.database import PostgresDatabase
from app.infra.database.vectorstore import PGVectorVectorstore
from app.infra.embedding_spaces.contracts import (
    EmbeddingSpaceBuildResult,
    EmbeddingSpaceRecord,
)
from app.infra.embedding_spaces.schema import VectorSchemaManager
from app.infra.embedding_spaces.source import VectorSourceReader


class VectorRebuildJob:
    """Re-embed source documents into one already-registered target."""

    def __init__(
        self,
        database: PostgresDatabase,
        *,
        batch_size: int = 32,
    ) -> None:
        self._database = database
        self._batch_size = max(1, batch_size)
        self._source = VectorSourceReader(database)
        self._schema = VectorSchemaManager(database)

    async def run(
        self,
        *,
        target: EmbeddingSpaceRecord,
        embeddings: Embeddings,
    ) -> tuple[EmbeddingSpaceBuildResult, PGVectorVectorstore]:
        await self._schema.ensure_table(target)
        await self._schema.clear_rows(target)

        vectorstore = PGVectorVectorstore(
            table_name=target.table_name,
            database=self._database,
            dimensions=target.spec.dimensions,
            index_kind=target.spec.index_kind,
            space_fingerprint=target.spec.fingerprint,
        )
        vectorstore.set_embed_fn(embeddings=embeddings)
        await vectorstore.initialize()

        source_count = await self._source.count(target.source_table_name)
        embedded_count = 0
        offset = 0
        while offset < source_count:
            documents = await self._source.read_batch(
                target.source_table_name,
                offset=offset,
                limit=self._batch_size,
            )
            if not documents:
                break
            vectors = await embeddings.aembed_documents(
                [document.content for document in documents]
            )
            by_collection: dict[
                str,
                list[tuple[dict, list[float]]],
            ] = defaultdict(list)
            for document, vector in zip(documents, vectors, strict=True):
                by_collection[document.collection_name].append(
                    (
                        {
                            **document.metadata,
                            "id": document.id,
                            "content": document.content,
                        },
                        vector,
                    )
                )
            for collection_name, rows in by_collection.items():
                await vectorstore.add_documents(
                    collection_name=collection_name,
                    documents=[row[0] for row in rows],
                    embeddings=[row[1] for row in rows],
                )
            embedded_count += len(documents)
            offset += len(documents)

        actual_count = await self._schema.count_rows(target)
        if actual_count != embedded_count:
            raise RuntimeError(
                "Embedding rebuild row-count validation failed "
                f"(target={target.table_name}, embedded={embedded_count}, "
                f"stored={actual_count})"
            )
        indexed = await self._schema.ensure_search_index(target)
        return (
            EmbeddingSpaceBuildResult(
                space_id=target.id,
                status="ready",
                source_count=source_count,
                embedded_count=embedded_count,
                indexed=indexed,
            ),
            vectorstore,
        )

    async def source_watermark(self) -> datetime:
        return await self._source.watermark()

    async def catch_up(
        self,
        *,
        target: EmbeddingSpaceRecord,
        embeddings: Embeddings,
        vectorstore: PGVectorVectorstore,
        updated_since: datetime,
    ) -> int:
        """Upsert writes that occurred after the initial rebuild began."""

        offset = 0
        caught_up = 0
        while True:
            documents = await self._source.read_updated_batch(
                target.source_table_name,
                updated_since=updated_since,
                offset=offset,
                limit=self._batch_size,
            )
            if not documents:
                break
            vectors = await embeddings.aembed_documents(
                [document.content for document in documents]
            )
            by_collection: dict[
                str,
                list[tuple[dict, list[float]]],
            ] = defaultdict(list)
            for document, vector in zip(documents, vectors, strict=True):
                by_collection[document.collection_name].append(
                    (
                        {
                            **document.metadata,
                            "id": document.id,
                            "content": document.content,
                        },
                        vector,
                    )
                )
            for collection_name, rows in by_collection.items():
                await vectorstore.add_documents(
                    collection_name=collection_name,
                    documents=[row[0] for row in rows],
                    embeddings=[row[1] for row in rows],
                )
            caught_up += len(documents)
            offset += len(documents)
        return caught_up


__all__ = ["VectorRebuildJob"]
