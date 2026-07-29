"""Runtime coordination for versioned persistent embedding spaces."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from langchain_core.embeddings import Embeddings
from sqlalchemy import text

from app.infra.database.database import PostgresDatabase
from app.infra.database.vectorstore import PGVectorVectorstore, _DEFAULT_TABLE
from app.infra.embedding_spaces.contracts import (
    EmbeddingPurpose,
    EmbeddingSpaceRecord,
    build_embedding_space_spec,
)
from app.infra.embedding_spaces.rebuild import VectorRebuildJob
from app.infra.embedding_spaces.registry import EmbeddingSpaceRegistry
from app.infra.embedding_spaces.schema import VectorSchemaManager
from app.infra.embedding_spaces.locks import generation_write_lock
from app.infra.llm.embedding import (
    EmbeddingObservation,
    get_observed_embedding_dimension,
    subscribe_embedding_observations,
)
from app.infra.llm.embedding_config import ResolvedEmbeddingConfig

logger = logging.getLogger(__name__)


class EmbeddingSpaceRuntime:
    """Turn observed model output into background-built active generations."""

    def __init__(
        self,
        database: PostgresDatabase,
        *,
        purposes: tuple[EmbeddingPurpose, ...] = ("documents",),
    ) -> None:
        self._database = database
        self._purposes = purposes
        self._registry = EmbeddingSpaceRegistry(database)
        self._schema = VectorSchemaManager(database)
        self._rebuild = VectorRebuildJob(database)
        self._active_stores: dict[EmbeddingPurpose, PGVectorVectorstore] = {}
        self._active_records: dict[EmbeddingPurpose, EmbeddingSpaceRecord] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._unsubscribe: Callable[[], None] | None = None
        self._closed = False

    def start(
        self,
        *,
        config: ResolvedEmbeddingConfig | None,
        embeddings: Embeddings | None,
    ) -> None:
        if self._unsubscribe is None:
            self._unsubscribe = subscribe_embedding_observations(
                self._on_embedding_observed
            )
        if config is None or embeddings is None:
            return
        dimensions = get_observed_embedding_dimension(config)
        if dimensions is not None:
            self.schedule_reconcile(
                config=config,
                embeddings=embeddings,
                dimensions=dimensions,
            )

    def get_active_store(
        self,
        purpose: EmbeddingPurpose = "documents",
    ) -> PGVectorVectorstore:
        store = self._active_stores.get(purpose)
        if store is None:
            raise RuntimeError(
                f"No active {purpose!r} embedding generation is ready"
            )
        return store

    def get_active_record(
        self,
        purpose: EmbeddingPurpose = "documents",
    ) -> EmbeddingSpaceRecord | None:
        return self._active_records.get(purpose)

    def schedule_reconcile(
        self,
        *,
        config: ResolvedEmbeddingConfig,
        embeddings: Embeddings,
        dimensions: int,
    ) -> None:
        if self._closed:
            return
        for purpose in self._purposes:
            spec = build_embedding_space_spec(
                purpose=purpose,
                config=config,
                dimensions=dimensions,
            )
            task_key = f"{purpose}:{spec.fingerprint}"
            existing = self._tasks.get(task_key)
            if existing is not None and not existing.done():
                continue
            task = asyncio.create_task(
                self._reconcile(
                    purpose=purpose,
                    config=config,
                    embeddings=embeddings,
                    dimensions=dimensions,
                ),
                name=f"embedding-space-{purpose}-{spec.fingerprint[:10]}",
            )
            self._tasks[task_key] = task
            task.add_done_callback(
                lambda completed, key=task_key: self._finish_task(key, completed)
            )

    async def dispose(self) -> None:
        self._closed = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

        stores = list({id(store): store for store in self._active_stores.values()}.values())
        self._active_stores.clear()
        self._active_records.clear()
        for store in stores:
            await store.dispose()

    def _on_embedding_observed(self, observation: EmbeddingObservation) -> None:
        self.schedule_reconcile(
            config=observation.config,
            embeddings=observation.embeddings,
            dimensions=observation.dimensions,
        )

    async def _reconcile(
        self,
        *,
        purpose: EmbeddingPurpose,
        config: ResolvedEmbeddingConfig,
        embeddings: Embeddings,
        dimensions: int,
    ) -> None:
        for attempt in range(1, 4):
            try:
                await self._reconcile_once(
                    purpose=purpose,
                    config=config,
                    embeddings=embeddings,
                    dimensions=dimensions,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt >= 3:
                    raise
                delay_seconds = float(2 * attempt - 1)
                logger.warning(
                    "Embedding generation reconciliation will retry: "
                    "purpose=%s attempt=%d delay_seconds=%.1f",
                    purpose,
                    attempt,
                    delay_seconds,
                    exc_info=True,
                )
                await asyncio.sleep(delay_seconds)

    async def _reconcile_once(
        self,
        *,
        purpose: EmbeddingPurpose,
        config: ResolvedEmbeddingConfig,
        embeddings: Embeddings,
        dimensions: int,
    ) -> None:
        spec = build_embedding_space_spec(
            purpose=purpose,
            config=config,
            dimensions=dimensions,
        )
        lock_key = f"embedding-space-build:{purpose}:{spec.fingerprint}"
        async with self._database.engine.connect() as lock_connection:
            acquired = bool(
                (
                    await lock_connection.execute(
                        text("SELECT pg_try_advisory_lock(hashtext(:lock_key))"),
                        {"lock_key": lock_key},
                    )
                ).scalar_one()
            )
            if not acquired:
                logger.info(
                    "Embedding generation is being built by another worker: "
                    "purpose=%s space=%s",
                    purpose,
                    spec.fingerprint[:12],
                )
                return
            try:
                await self._reconcile_locked(
                    purpose=purpose,
                    spec_fingerprint=spec.fingerprint,
                    config=config,
                    embeddings=embeddings,
                    dimensions=dimensions,
                )
            finally:
                await lock_connection.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                    {"lock_key": lock_key},
                )

    async def _reconcile_locked(
        self,
        *,
        purpose: EmbeddingPurpose,
        spec_fingerprint: str,
        config: ResolvedEmbeddingConfig,
        embeddings: Embeddings,
        dimensions: int,
    ) -> None:
        spec = build_embedding_space_spec(
            purpose=purpose,
            config=config,
            dimensions=dimensions,
        )
        if spec.fingerprint != spec_fingerprint:
            raise RuntimeError("Embedding space identity changed during reconciliation")

        active = await self._registry.get_active(purpose)
        if active is not None and active.spec.fingerprint == spec.fingerprint:
            store = await self._open_store(active, embeddings)
            self._swap_active(purpose, active, store)
            return

        target = await self._registry.ensure_building(
            spec,
            source=active,
            legacy_source_table=_DEFAULT_TABLE if active is None else None,
        )
        if target.status == "active":
            store = await self._open_store(target, embeddings)
            self._swap_active(purpose, target, store)
            return
        if target.status == "ready":
            logger.info(
                "Revalidating an unbound ready generation before activation: "
                "purpose=%s generation=%d",
                purpose,
                target.generation,
            )
        if target.status == "failed":
            target = await self._registry.retry_build(target.id)

        try:
            source_watermark = await self._rebuild.source_watermark()
            result, store = await self._rebuild.run(
                target=target,
                embeddings=embeddings,
            )
            async with generation_write_lock(
                self._database,
                purpose=purpose,
                exclusive=True,
            ):
                await self._rebuild.catch_up(
                    target=target,
                    embeddings=embeddings,
                    vectorstore=store,
                    updated_since=source_watermark,
                )
                document_count = await self._schema.count_rows(target)
                await self._registry.mark_ready(
                    target.id,
                    document_count=document_count,
                )
                activated = await self._registry.activate(target.id)
                store.promote_to_active()
                self._swap_active(purpose, activated, store)
            logger.info(
                "Embedding generation activated: purpose=%s generation=%d "
                "space=%s dimensions=%d documents=%d index_kind=%s",
                purpose,
                activated.generation,
                activated.spec.fingerprint[:12],
                activated.spec.dimensions,
                activated.document_count,
                activated.spec.index_kind,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._registry.mark_failed(target.id, str(exc))
            logger.exception(
                "Embedding generation build failed: purpose=%s space=%s",
                purpose,
                spec.fingerprint[:12],
            )
            raise

    async def _open_store(
        self,
        space: EmbeddingSpaceRecord,
        embeddings: Embeddings,
    ) -> PGVectorVectorstore:
        await self._schema.validate_table(space)
        store = PGVectorVectorstore(
            table_name=space.table_name,
            database=self._database,
            dimensions=space.spec.dimensions,
            index_kind=space.spec.index_kind,
            space_fingerprint=space.spec.fingerprint,
            purpose=space.spec.purpose,
            enforce_active_write=True,
        )
        store.set_embed_fn(embeddings=embeddings)
        await store.initialize()
        return store

    def _swap_active(
        self,
        purpose: EmbeddingPurpose,
        record: EmbeddingSpaceRecord,
        store: PGVectorVectorstore,
    ) -> None:
        previous = self._active_stores.get(purpose)
        self._active_records[purpose] = record
        self._active_stores[purpose] = store
        if previous is not None and previous is not store:
            asyncio.create_task(previous.dispose())

    def _finish_task(self, key: str, task: asyncio.Task[None]) -> None:
        self._tasks.pop(key, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.exception(
                "Embedding-space reconciliation task crashed",
                exc_info=(type(error), error, error.__traceback__),
            )


__all__ = ["EmbeddingSpaceRuntime"]
