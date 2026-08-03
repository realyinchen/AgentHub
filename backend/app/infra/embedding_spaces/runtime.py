"""Runtime coordination for versioned persistent embedding spaces."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime

from langchain_core.embeddings import Embeddings
from sqlalchemy import text

from app.infra.database.database import PostgresDatabase
from app.infra.database.vectorstore import PGVectorVectorstore, _DEFAULT_TABLE
from app.infra.embedding_spaces.activator import EmbeddingGenerationActivator
from app.infra.embedding_spaces.calibration_contracts import (
    CalibrationDatasetArtifact,
    EmbeddingActivationCommand,
    EmbeddingActivationReceipt,
    EmbeddingCalibrationMeasurement,
    EmbeddingCalibrationReportRecord,
    GenerationValidationEvidence,
    bind_calibration_report,
)
from app.infra.embedding_spaces.calibration_dataset import (
    load_default_calibration_dataset,
)
from app.infra.embedding_spaces.calibration import (
    calibrate_embedding_generation,
)
from app.infra.embedding_spaces.calibration_repository import (
    EmbeddingCalibrationRepository,
)
from app.infra.embedding_spaces.calibration_runner import (
    EmbeddingCalibrationRunner,
)
from app.infra.embedding_spaces.contracts import (
    EmbeddingPurpose,
    EmbeddingSpaceRecord,
    build_embedding_space_spec,
)
from app.infra.embedding_spaces.rebuild import VectorRebuildJob
from app.infra.embedding_spaces.registry import EmbeddingSpaceRegistry
from app.infra.embedding_spaces.legacy_activation import (
    LegacyEmbeddingActivationBridge,
)
from app.infra.embedding_spaces.schema import VectorSchemaManager
from app.infra.embedding_spaces.locks import generation_write_lock
from app.infra.config import get_settings
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
        self._legacy_activation = LegacyEmbeddingActivationBridge(self._registry)
        self._schema = VectorSchemaManager(database)
        self._rebuild = VectorRebuildJob(database)
        self._calibration = EmbeddingCalibrationRunner()
        self._calibration_reports = EmbeddingCalibrationRepository(database)
        self._activator = EmbeddingGenerationActivator(database)
        self._active_stores: dict[EmbeddingPurpose, PGVectorVectorstore] = {}
        self._active_records: dict[EmbeddingPurpose, EmbeddingSpaceRecord] = {}
        self._last_calibration_reports: dict[
            EmbeddingPurpose,
            EmbeddingCalibrationReportRecord,
        ] = {}
        self._last_activation_receipts: dict[
            EmbeddingPurpose,
            EmbeddingActivationReceipt,
        ] = {}
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
            raise RuntimeError(f"No active {purpose!r} embedding generation is ready")
        return store

    def get_active_record(
        self,
        purpose: EmbeddingPurpose = "documents",
    ) -> EmbeddingSpaceRecord | None:
        return self._active_records.get(purpose)

    def get_last_calibration_report(
        self,
        purpose: EmbeddingPurpose = "documents",
    ) -> EmbeddingCalibrationReportRecord | None:
        return self._last_calibration_reports.get(purpose)

    def get_last_activation_receipt(
        self,
        purpose: EmbeddingPurpose = "documents",
    ) -> EmbeddingActivationReceipt | None:
        return self._last_activation_receipts.get(purpose)

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

        stores = list(
            {id(store): store for store in self._active_stores.values()}.values()
        )
        self._active_stores.clear()
        self._active_records.clear()
        self._last_calibration_reports.clear()
        self._last_activation_receipts.clear()
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

        cutover_complete = False
        try:
            source_watermark = await self._rebuild.source_watermark()
            _result, store = await self._rebuild.run(
                target=target,
                embeddings=embeddings,
            )
            calibration_artifact: CalibrationDatasetArtifact | None = None
            calibration_measurement: EmbeddingCalibrationMeasurement | None = None
            if get_settings().EMBEDDING_GENERATION_GATES_V1:
                calibration_artifact = load_default_calibration_dataset()
                calibration_measurement = await self._calibration.measure(
                    embeddings=embeddings,
                    artifact=calibration_artifact,
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
                ready = await self._registry.mark_ready(
                    target.id,
                    document_count=document_count,
                )
                if get_settings().EMBEDDING_GENERATION_GATES_V1:
                    activated = await self._activate_calibrated_generation(
                        target=ready,
                        source_count=await self._rebuild.source_count(
                            target.source_table_name
                        ),
                        stored_count=document_count,
                        artifact=calibration_artifact,
                        measurement=calibration_measurement,
                        source_watermark=source_watermark,
                    )
                else:
                    # Temporary R7 migration bridge. R8 removes Registry.activate
                    # after calibrated cutover is certified in live mode.
                    activated = await self._legacy_activation.activate(target.id)
                cutover_complete = True
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
            if not cutover_complete:
                await self._registry.mark_failed(target.id, str(exc))
            logger.exception(
                "Embedding generation build failed: purpose=%s space=%s",
                purpose,
                spec.fingerprint[:12],
            )
            raise

    async def _activate_calibrated_generation(
        self,
        *,
        target: EmbeddingSpaceRecord,
        source_count: int,
        stored_count: int,
        artifact: CalibrationDatasetArtifact | None,
        measurement: EmbeddingCalibrationMeasurement | None,
        source_watermark: datetime,
    ) -> EmbeddingSpaceRecord:
        if artifact is None or measurement is None:
            raise RuntimeError("embedding_calibration_measurement_missing")
        single_generation_query = "passed"
        try:
            await self._schema.validate_single_generation_query(target)
        except Exception:
            single_generation_query = "failed"
        validation = GenerationValidationEvidence(
            purpose=target.spec.purpose,
            expected_dimensions=target.spec.dimensions,
            observed_dimensions=measurement.observed_dimensions,
            source_count=source_count,
            # Every stored row has a NOT NULL vector in the generation table.
            embedded_count=stored_count,
            stored_count=stored_count,
            active_fact_filter=(
                "failed" if target.spec.purpose == "memory" else "not_applicable"
            ),
            tenant_isolation=(
                "failed" if target.spec.purpose == "memory" else "not_applicable"
            ),
            single_generation_query=single_generation_query,
        )
        calibration = calibrate_embedding_generation(
            artifact=artifact,
            scores=measurement.scores,
            evidence=validation,
        )
        report_draft = bind_calibration_report(
            space_id=target.id,
            source_watermark=source_watermark,
            result=calibration,
        )
        if calibration.status != "passed":
            failed_report = await self._calibration_reports.append(report_draft)
            self._last_calibration_reports[target.spec.purpose] = failed_report
            raise RuntimeError(
                "embedding_calibration_rejected:" + ",".join(calibration.failure_codes)
            )
        settings = get_settings()
        idempotency_key = _activation_idempotency_key(
            purpose=target.spec.purpose,
            space_id=str(target.id),
            report_fingerprint=report_draft.report_fingerprint,
        )
        activation = await self._activator.activate(
            EmbeddingActivationCommand(
                purpose=target.spec.purpose,
                to_space_id=target.id,
                report=report_draft,
                expected_dataset_sha256=artifact.sha256,
                idempotency_key=idempotency_key,
                source_commit_sha=settings.AGENT_RELEASE_COMMIT_SHA or "",
                reason="r7_calibrated_generation_cutover",
            )
        )
        self._last_calibration_reports[target.spec.purpose] = activation.report
        self._last_activation_receipts[target.spec.purpose] = activation.receipt
        return target.model_copy(
            update={
                "status": "active",
                "activated_at": (activation.receipt.created_at or target.activated_at),
            }
        )

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


def _activation_idempotency_key(
    *,
    purpose: str,
    space_id: str,
    report_fingerprint: str,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "action": "activate",
                "purpose": purpose,
                "space_id": space_id,
                "report_fingerprint": report_fingerprint,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = ["EmbeddingSpaceRuntime"]
