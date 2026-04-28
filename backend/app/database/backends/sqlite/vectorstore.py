"""
SQLite + sqlite-vec Vectorstore Backend

Implements VectorstoreInterface using aiosqlite with the sqlite-vec extension
for vector similarity search. Each collection maps to two tables:
  - {collection_name}_vectors: vec0 virtual table for vector storage
  - {collection_name}_metadata: regular table for JSON payloads

Score semantics: cosine distance from sqlite-vec is converted to
cosine similarity (score = 1.0 - distance) for consistency with Qdrant.
"""

import json
import logging
import struct
from pathlib import Path
from typing import Optional

import aiosqlite

from app.core.config import settings
from app.database.interfaces import VectorstoreInterface

logger = logging.getLogger(__name__)


class SqliteVecVectorstore(VectorstoreInterface):
    """SQLite + sqlite-vec vector store backend."""

    def __init__(self) -> None:
        self._db: Optional[aiosqlite.Connection] = None
        self._initialized_collections: set[str] = set()

    @property
    def db(self) -> aiosqlite.Connection:
        """Get the database connection, raising if not initialized."""
        if self._db is None:
            raise RuntimeError("Vectorstore not initialized. Call initialize() first.")
        return self._db

    async def initialize(self) -> None:
        """Initialize the SQLite connection and load sqlite-vec extension."""
        if self._db is not None:
            logger.warning("sqlite-vec vectorstore already initialized, skipping")
            return

        # Ensure data directory exists
        db_path = Path(settings.SQLITE_VEC_DATABASE_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Load sqlite-vec extension
        try:
            import sqlite_vec

            loadable_path = sqlite_vec.loadable_path()
        except ImportError:
            raise ImportError(
                "sqlite-vec package is required for sqlite_vec vectorstore backend. "
                "Install it with: pip install sqlite-vec"
            )

        # Open connection and load extension
        self._db = await aiosqlite.connect(str(db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.enable_load_extension(True)
        await self._db.load_extension(loadable_path)
        await self._db.enable_load_extension(False)

        # Enable WAL mode for better concurrency
        await self._db.execute("PRAGMA journal_mode=WAL")

        logger.info(f"sqlite-vec vectorstore initialized (db: {db_path})")

    async def _ensure_collection(self, collection_name: str, vector_size: int) -> None:
        """Create vec0 virtual table and metadata table if they don't exist."""
        if collection_name in self._initialized_collections:
            return

        # Sanitize collection name for table names
        safe_name = "".join(
            c if c.isalnum() or c == "_" else "_" for c in collection_name
        )
        vec_table = f"{safe_name}_vectors"
        meta_table = f"{safe_name}_metadata"

        # Check if virtual table already exists
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (vec_table,),
        )
        vec_exists = await cursor.fetchone()

        if not vec_exists:
            await self.db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {vec_table} "
                f"USING vec0(embedding float[{vector_size}])"
            )
            logger.info(f"Created sqlite-vec virtual table: {vec_table}")

        # Check if metadata table exists
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (meta_table,),
        )
        meta_exists = await cursor.fetchone()

        if not meta_exists:
            await self.db.execute(
                f"CREATE TABLE IF NOT EXISTS {meta_table} ("
                f"id INTEGER PRIMARY KEY AUTOINCREMENT, "
                f"payload TEXT NOT NULL"
                f")"
            )
            logger.info(f"Created metadata table: {meta_table}")

        await self.db.commit()
        self._initialized_collections.add(collection_name)

    @staticmethod
    def _serialize_vector(vector: list[float]) -> bytes:
        """Serialize a float vector to bytes for sqlite-vec storage."""
        return struct.pack(f"{len(vector)}f", *vector)

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict]:
        """
        Search the vector store by pre-computed embedding vector.

        Returns results with cosine similarity score (1.0 = identical).
        """
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
            logger.error(f"sqlite-vec search error: {e}")
            return []

        results = []
        for row in rows:
            rowid = row[0]
            distance = row[1]
            payload_str = row[2]

            # Convert cosine distance to cosine similarity
            score = 1.0 - distance

            try:
                payload = json.loads(payload_str) if payload_str else {}
            except json.JSONDecodeError:
                payload = {"raw": payload_str}

            results.append(
                {
                    "id": str(rowid),
                    "score": score,
                    "payload": payload,
                }
            )

        return results

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict],
        embeddings: list[list[float]],
    ) -> list[str]:
        """Add documents with pre-computed embeddings to sqlite-vec."""
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
                # Insert metadata first
                payload_str = json.dumps(doc, ensure_ascii=False)
                cursor = await self.db.execute(
                    f"INSERT INTO {meta_table} (payload) VALUES (?)",
                    (payload_str,),
                )
                row_id = cursor.lastrowid

                # Insert vector with matching rowid
                serialized = self._serialize_vector(emb)
                await self.db.execute(
                    f"INSERT INTO {vec_table} (rowid, embedding) VALUES (?, ?)",
                    (row_id, serialized),
                )

                ids.append(str(row_id))

            await self.db.commit()
            logger.info(
                f"Added {len(ids)} documents to sqlite-vec collection '{collection_name}'"
            )
            return ids
        except Exception:
            await self.db.rollback()
            raise

    async def dispose(self) -> None:
        """Close the SQLite connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            self._initialized_collections.clear()
            logger.info("sqlite-vec vectorstore disposed")
