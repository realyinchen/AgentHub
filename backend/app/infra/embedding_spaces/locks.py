"""Advisory locks that serialize generation cutover against document writes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy import text

from app.infra.database.database import PostgresDatabase
from app.infra.embedding_spaces.contracts import EmbeddingPurpose


@asynccontextmanager
async def generation_write_lock(
    database: PostgresDatabase,
    *,
    purpose: EmbeddingPurpose,
    exclusive: bool,
) -> AsyncIterator[None]:
    """Hold a session advisory lock for a write or atomic cutover window."""

    lock_key = f"embedding-space-cutover:{purpose}"
    acquire = (
        "SELECT pg_advisory_lock(hashtext(:lock_key))"
        if exclusive
        else "SELECT pg_advisory_lock_shared(hashtext(:lock_key))"
    )
    release = (
        "SELECT pg_advisory_unlock(hashtext(:lock_key))"
        if exclusive
        else "SELECT pg_advisory_unlock_shared(hashtext(:lock_key))"
    )
    async with database.engine.connect() as connection:
        await connection.execute(text(acquire), {"lock_key": lock_key})
        try:
            yield
        finally:
            await connection.execute(text(release), {"lock_key": lock_key})


__all__ = ["generation_write_lock"]
