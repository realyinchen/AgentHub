"""Persistence gateway for embedding-space lifecycle metadata."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.database import PostgresDatabase
from app.infra.embedding_spaces.contracts import (
    EmbeddingSpaceRecord,
    EmbeddingSpaceSpec,
)


class EmbeddingSpaceRegistry:
    """Read and transition embedding generations; never creates vector tables."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def get_by_fingerprint(
        self,
        spec: EmbeddingSpaceSpec,
    ) -> EmbeddingSpaceRecord | None:
        async with self._database.session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM public.embedding_spaces
                    WHERE purpose = :purpose
                      AND space_fingerprint = :fingerprint
                    """
                ),
                {
                    "purpose": spec.purpose,
                    "fingerprint": spec.fingerprint,
                },
            )
            row = result.mappings().first()
        return _record_from_row(row) if row is not None else None

    async def get_active(
        self,
        purpose: str,
    ) -> EmbeddingSpaceRecord | None:
        async with self._database.session() as session:
            result = await session.execute(
                text(
                    """
                    SELECT spaces.*
                    FROM public.embedding_space_bindings AS bindings
                    JOIN public.embedding_spaces AS spaces
                      ON spaces.id = bindings.active_space_id
                    WHERE bindings.purpose = :purpose
                    """
                ),
                {"purpose": purpose},
            )
            row = result.mappings().first()
        return _record_from_row(row) if row is not None else None

    async def ensure_building(
        self,
        spec: EmbeddingSpaceSpec,
        *,
        source: EmbeddingSpaceRecord | None,
        legacy_source_table: str | None = None,
    ) -> EmbeddingSpaceRecord:
        """Return an existing generation or atomically register a new one."""

        async with self._database.session() as session:
            await _lock_purpose(session, spec.purpose)
            existing = await _get_by_fingerprint(session, spec)
            if existing is not None:
                return existing

            generation_result = await session.execute(
                text(
                    """
                    SELECT COALESCE(MAX(generation), 0) + 1
                    FROM public.embedding_spaces
                    WHERE purpose = :purpose
                    """
                ),
                {"purpose": spec.purpose},
            )
            generation = int(generation_result.scalar_one())
            table_name = _generation_table_name(
                purpose=spec.purpose,
                generation=generation,
                fingerprint=spec.fingerprint,
            )
            result = await session.execute(
                text(
                    """
                    INSERT INTO public.embedding_spaces (
                        purpose,
                        generation,
                        space_fingerprint,
                        transport_fingerprint,
                        provider,
                        model,
                        model_revision,
                        model_origin,
                        dimensions,
                        distance_metric,
                        normalized,
                        index_kind,
                        table_name,
                        status,
                        source_space_id,
                        source_table_name
                    )
                    VALUES (
                        :purpose,
                        :generation,
                        :space_fingerprint,
                        :transport_fingerprint,
                        :provider,
                        :model,
                        :model_revision,
                        :model_origin,
                        :dimensions,
                        :distance_metric,
                        :normalized,
                        :index_kind,
                        :table_name,
                        'building',
                        :source_space_id,
                        :source_table_name
                    )
                    RETURNING *
                    """
                ),
                {
                    "purpose": spec.purpose,
                    "generation": generation,
                    "space_fingerprint": spec.fingerprint,
                    "transport_fingerprint": spec.transport_fingerprint,
                    "provider": spec.provider,
                    "model": spec.model,
                    "model_revision": spec.model_revision,
                    "model_origin": spec.model_origin,
                    "dimensions": spec.dimensions,
                    "distance_metric": spec.distance_metric,
                    "normalized": spec.normalized,
                    "index_kind": spec.index_kind,
                    "table_name": table_name,
                    "source_space_id": source.id if source is not None else None,
                    "source_table_name": (
                        source.table_name if source is not None else legacy_source_table
                    ),
                },
            )
            row = result.mappings().one()
        return _record_from_row(row)

    async def mark_ready(
        self,
        space_id: UUID,
        *,
        document_count: int,
    ) -> EmbeddingSpaceRecord:
        async with self._database.session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.embedding_spaces
                    SET status = 'ready',
                        document_count = :document_count,
                        error = '',
                        updated_at = NOW()
                    WHERE id = :space_id
                      AND status IN ('building', 'ready')
                    RETURNING *
                    """
                ),
                {
                    "space_id": space_id,
                    "document_count": document_count,
                },
            )
            row = result.mappings().one()
        return _record_from_row(row)

    async def retry_build(self, space_id: UUID) -> EmbeddingSpaceRecord:
        async with self._database.session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.embedding_spaces
                    SET status = 'building',
                        document_count = 0,
                        error = '',
                        updated_at = NOW()
                    WHERE id = :space_id
                      AND status = 'failed'
                    RETURNING *
                    """
                ),
                {"space_id": space_id},
            )
            row = result.mappings().one()
        return _record_from_row(row)

    async def activate(self, space_id: UUID) -> EmbeddingSpaceRecord:
        """Atomically switch one purpose to a fully built generation."""

        async with self._database.session() as session:
            candidate_result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM public.embedding_spaces
                    WHERE id = :space_id
                    FOR UPDATE
                    """
                ),
                {"space_id": space_id},
            )
            candidate_row = candidate_result.mappings().one()
            candidate = _record_from_row(candidate_row)
            if candidate.status not in {"ready", "active"}:
                raise RuntimeError(
                    "Only ready embedding spaces may be activated "
                    f"(space_id={space_id}, status={candidate.status})"
                )

            await _lock_purpose(session, candidate.spec.purpose)
            await session.execute(
                text(
                    """
                    UPDATE public.embedding_spaces
                    SET status = 'ready', updated_at = NOW()
                    WHERE purpose = :purpose
                      AND status = 'active'
                      AND id <> :space_id
                    """
                ),
                {
                    "purpose": candidate.spec.purpose,
                    "space_id": space_id,
                },
            )
            result = await session.execute(
                text(
                    """
                    UPDATE public.embedding_spaces
                    SET status = 'active',
                        activated_at = COALESCE(activated_at, NOW()),
                        updated_at = NOW()
                    WHERE id = :space_id
                    RETURNING *
                    """
                ),
                {"space_id": space_id},
            )
            activated_row = result.mappings().one()
            await session.execute(
                text(
                    """
                    INSERT INTO public.embedding_space_bindings (
                        purpose, active_space_id, updated_at
                    )
                    VALUES (:purpose, :space_id, NOW())
                    ON CONFLICT (purpose)
                    DO UPDATE SET
                        active_space_id = EXCLUDED.active_space_id,
                        updated_at = NOW()
                    """
                ),
                {
                    "purpose": candidate.spec.purpose,
                    "space_id": space_id,
                },
            )
        return _record_from_row(activated_row)

    async def mark_failed(
        self,
        space_id: UUID,
        error: str,
    ) -> EmbeddingSpaceRecord:
        async with self._database.session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE public.embedding_spaces
                    SET status = 'failed',
                        error = :error,
                        updated_at = NOW()
                    WHERE id = :space_id
                    RETURNING *
                    """
                ),
                {
                    "space_id": space_id,
                    "error": error[:1000],
                },
            )
            row = result.mappings().one()
        return _record_from_row(row)


async def _get_by_fingerprint(
    session: AsyncSession,
    spec: EmbeddingSpaceSpec,
) -> EmbeddingSpaceRecord | None:
    result = await session.execute(
        text(
            """
            SELECT *
            FROM public.embedding_spaces
            WHERE purpose = :purpose
              AND space_fingerprint = :fingerprint
            FOR UPDATE
            """
        ),
        {
            "purpose": spec.purpose,
            "fingerprint": spec.fingerprint,
        },
    )
    row = result.mappings().first()
    return _record_from_row(row) if row is not None else None


async def _lock_purpose(session: AsyncSession, purpose: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"embedding-space:{purpose}"},
    )


def _generation_table_name(
    *,
    purpose: str,
    generation: int,
    fingerprint: str,
) -> str:
    safe_purpose = "".join(
        character if character.isalnum() else "_"
        for character in purpose.lower()
    ).strip("_")
    return f"embedding_{safe_purpose}_g{generation}_{fingerprint[:10]}"[:63]


def _record_from_row(row: Any) -> EmbeddingSpaceRecord:
    spec = EmbeddingSpaceSpec(
        purpose=row["purpose"],
        provider=row["provider"],
        model=row["model"],
        model_revision=row["model_revision"] or "",
        model_origin=row["model_origin"] or "",
        dimensions=int(row["dimensions"]),
        distance_metric=row["distance_metric"],
        normalized=bool(row["normalized"]),
        fingerprint=row["space_fingerprint"],
        transport_fingerprint=row["transport_fingerprint"] or "",
        index_kind=row["index_kind"],
    )
    return EmbeddingSpaceRecord(
        id=row["id"],
        generation=int(row["generation"]),
        spec=spec,
        table_name=row["table_name"],
        status=row["status"],
        source_space_id=row["source_space_id"],
        source_table_name=row["source_table_name"],
        document_count=int(row["document_count"] or 0),
        error=row["error"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        activated_at=row["activated_at"],
    )


__all__ = ["EmbeddingSpaceRegistry"]
