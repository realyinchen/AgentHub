"""
SQLite vector store backend (sqlite-vec extension).

Provides local semantic search for development / testing using the sqlite-vec
SQLite extension. For dev mode only; production uses postgres/vectorstore.py.
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Optional,
    TYPE_CHECKING,
)

import aiosqlite

from app.infra.config import get_settings

if TYPE_CHECKING:
    from aiosqlite import Connection

logger = logging.getLogger(__name__)


class SqliteVecVectorstore:
    """SQLite vector store backend using sqlite-vec extension."""

    def __init__(self) -> None:
        self._db: Connection | None = None
        self._initialized_collections: set[str] = set()
        self._embed_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None

    def set_embed_fn(self, fn: Callable[[str], Awaitable[list[float]]]) -> None:
        self._embed_fn = fn

    @property
    def db(self) -> Connection:
        if self._db is None:
            raise RuntimeError("Vectorstore not initialized. Call initialize() first.")
        return self._db

    async def initialize(self) -> None:
        if self._db is not None:
            logger.warning("sqlite-vec vectorstore already initialized, skipping")
            return

        settings = get_settings()
        db_path = settings.SQLITE_DATABASE_PATH
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(db_path)
        await self._db.enable_load_extension(True)

        try:
            await self._db.execute("SELECT load_extension('vec0')")
        except aiosqlite.Error:
            logger.warning(
                "sqlite-vec extension could not be loaded. Vector search will be "
                "disabled. Install sqlite-vec or use PostgreSQL for production."
            )

        await self._db.enable_load_extension(False)
        logger.info("sqlite-vec vectorstore initialized (db: %s)", db_path)

    async def _ensure_collection(self, collection_name: str, vector_size: int) -> None:
        if collection_name in self._initialized_collections:
            return

        safe_name = "".join(
            c if c.isalnum() or c == "_" else "_" for c in collection_name
        )
        vec_table = f"{safe_name}_vectors"
        meta_table = f"{safe_name}_metadata"

        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (vec_table,),
        )
        if not await cursor.fetchone():
            await self.db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table} "
                f"USING vec0(embedding float[{vector_size}])"
            )
            logger.info("Created sqlite-vec virtual table: %s", vec_table)

        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (meta_table,),
        )
        if not await cursor.fetchone():
            await self.db.execute(
                f"CREATE TABLE IF NOT EXISTS {meta_table} ("
                f"id INTEGER PRIMARY KEY AUTOINCREMENT, "
                f"payload TEXT NOT NULL"
                f")"
            )
            logger.info("Created metadata table: %s", meta_table)

        await self.db.commit()
        self._initialized_collections.add(collection_name)

    @staticmethod
    def _serialize_vector(vector: list[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    async def search(
        self, collection_name: str, query_text: str, limit: int = 5
    ) -> list[dict]:
        """Search by text (uses injected embed_fn)."""
        if self._embed_fn is None:
            raise ValueError(
                "No embedding function configured. The vectorstore search requires "
                "an embedding model. Please configure at least one Embedding model."
            )
        embedding = await self._embed_fn(query_text)
        return await self.search_with_embedding(
            collection_name=collection_name, embedding=embedding, limit=limit
        )

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict]:
        await self._ensure_collection(collection_name, vector_size=len(embedding))

        safe_name = "".join(
            c if c.isalnum() or c == "_" else "_" for c in collection_name
        )
        vec_table = f"{safe_name}_vectors"
        meta_table = f"{safe_name}_metadata"
        query_embedding = self._serialize_vector(embedding)

        try:
            cursor = await self.db.execute(
                f"SELECT v.rowid, v.distance, m.payload "
                f"FROM {vec_table} v "
                f"LEFT JOIN {meta_table} m ON v.rowid = m.id "
                f"WHERE v.embedding MATCH ? "
                f"ORDER BY v.distance "
                f"LIMIT ?",
                (query_embedding, limit),
            )
            rows = await cursor.fetchall()
        except Exception as e:
            logger.error("sqlite-vec search error: %s", e)
            return []

        results = []
        for row in rows:
            rowid, distance, payload_str = row[0], row[1], row[2]
            score = 1.0 - distance
            try:
                payload = json.loads(payload_str) if payload_str else {}
            except json.JSONDecodeError:
                payload = {"raw": payload_str}
            results.append({"id": str(rowid), "score": score, "payload": payload})

        return results

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict],
        embeddings: list[list[float]],
    ) -> list[str]:
        if not documents or not embeddings:
            return []
        if len(documents) != len(embeddings):
            raise ValueError(
                f"Number of documents ({len(documents)}) does not match "
                f"number of embeddings ({len(embeddings)})"
            )

        await self._ensure_collection(collection_name, vector_size=len(embeddings[0]))
        safe_name = "".join(
            c if c.isalnum() or c == "_" else "_" for c in collection_name
        )
        vec_table = f"{safe_name}_vectors"
        meta_table = f"{safe_name}_metadata"

        ids = []
        try:
            for doc, emb in zip(documents, embeddings):
                payload_str = json.dumps(doc, ensure_ascii=False)
                cursor = await self.db.execute(
                    f"INSERT INTO {meta_table} (payload) VALUES (?)", (payload_str,)
                )
                row_id = cursor.lastrowid
                serialized = self._serialize_vector(emb)
                await self.db.execute(
                    f"INSERT INTO {vec_table} (rowid, embedding) VALUES (?, ?)",
                    (row_id, serialized),
                )
                ids.append(str(row_id))
            await self.db.commit()
            logger.info(
                "Added %d documents to sqlite-vec collection '%s'",
                len(ids),
                collection_name,
            )
            return ids
        except Exception:
            await self.db.rollback()
            raise

    async def dispose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
            self._initialized_collections.clear()
            logger.info("sqlite-vec vectorstore disposed")
