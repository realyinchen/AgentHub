from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.infra.embedding_spaces.activator import EmbeddingGenerationActivator
from app.infra.embedding_spaces.calibration import (
    calibrate_embedding_generation,
)
from app.infra.embedding_spaces.calibration_contracts import (
    EmbeddingActivationCommand,
    EmbeddingActivationReceipt,
    EmbeddingCalibrationReportRecord,
    EmbeddingCalibrationScore,
    EmbeddingRollbackCommand,
    GenerationValidationEvidence,
    bind_calibration_report,
)
from app.infra.embedding_spaces.calibration_dataset import (
    load_default_calibration_dataset,
)
from app.services.routing.vector_recall import VectorPrototypeRecall
from scripts.init_database import _get_sorted_sql_files


def _evidence(
    *,
    observed_dimensions: int = 8,
) -> GenerationValidationEvidence:
    return GenerationValidationEvidence(
        purpose="documents",
        expected_dimensions=8,
        observed_dimensions=observed_dimensions,
        source_count=20,
        embedded_count=20,
        stored_count=20,
        active_fact_filter="not_applicable",
        tenant_isolation="not_applicable",
        single_generation_query="passed",
    )


def _separated_scores() -> list[EmbeddingCalibrationScore]:
    artifact = load_default_calibration_dataset()
    return [
        EmbeddingCalibrationScore(
            sample_id=sample.sample_id,
            score=0.9 if sample.relevant else 0.1,
        )
        for sample in artifact.dataset.samples
    ]


def _report_fixture(
    *,
    space_id,
    evidence: GenerationValidationEvidence | None = None,
    force_passed_with_failed_row_check: bool = False,
):
    artifact = load_default_calibration_dataset()
    result = calibrate_embedding_generation(
        artifact=artifact,
        scores=_separated_scores(),
        evidence=evidence or _evidence(),
    )
    if force_passed_with_failed_row_check:
        result = result.model_copy(
            update={
                "status": "passed",
                "failure_codes": (),
                "validation_checks": result.validation_checks.model_copy(
                    update={"row_count": "failed"}
                ),
            }
        )
    draft = bind_calibration_report(
        space_id=space_id,
        source_watermark=datetime.now(timezone.utc),
        result=result,
    )
    record = EmbeddingCalibrationReportRecord(
        id=uuid4(),
        **draft.model_dump(),
    )
    return artifact, draft, record


def _activation_command(*, key: str, report):
    return EmbeddingActivationCommand(
        purpose="documents",
        to_space_id=report.space_id,
        report=report,
        expected_dataset_sha256=report.result.dataset_sha256,
        idempotency_key=key * 64,
    )


class CalibrationContractTests(unittest.TestCase):
    def test_dataset_hash_and_threshold_are_generation_inputs(self):
        artifact = load_default_calibration_dataset()
        result = calibrate_embedding_generation(
            artifact=artifact,
            scores=_separated_scores(),
            evidence=_evidence(),
        )

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.dataset_sha256, artifact.sha256)
        self.assertEqual(result.threshold, 0.9)
        self.assertEqual(result.precision_score, 1.0)
        self.assertEqual(result.recall_score, 1.0)
        self.assertEqual(result.positive_count, 10)
        self.assertEqual(result.negative_count, 10)

    def test_validation_failure_blocks_an_otherwise_good_threshold(self):
        artifact = load_default_calibration_dataset()
        result = calibrate_embedding_generation(
            artifact=artifact,
            scores=_separated_scores(),
            evidence=_evidence(observed_dimensions=7),
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("dimensions_failed", result.failure_codes)

    def test_score_coverage_mismatch_is_not_silently_calibrated(self):
        artifact = load_default_calibration_dataset()
        result = calibrate_embedding_generation(
            artifact=artifact,
            scores=_separated_scores()[:-1],
            evidence=_evidence(),
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("score_coverage_mismatch", result.failure_codes)

    def test_migration_is_append_only_and_idempotent(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "sql"
            / "change_026_embedding_generation_gates.sql"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "CREATE TABLE IF NOT EXISTS public.embedding_calibration_reports",
            migration,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS public.embedding_space_activations",
            migration,
        )
        self.assertEqual(migration.count("ON DELETE RESTRICT"), 4)
        self.assertIn("BEFORE UPDATE OR DELETE", migration)
        self.assertIn("source_watermark", migration)
        self.assertIn("uq_embedding_calibration_space_dataset", migration)

    def test_migration_runner_orders_only_by_change_prefix(self):
        names = [Path(path).name for path in _get_sorted_sql_files()]
        self.assertLess(
            names.index("change_025_agent_certification_v4_release_identity.sql"),
            names.index("change_026_embedding_generation_gates.sql"),
        )


class _NoopDatabase:
    def __init__(self) -> None:
        self.session_object = object()

    @asynccontextmanager
    async def session(self):
        yield self.session_object


class _ScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _MappingRows:
    def __init__(self, row) -> None:
        self.row = row

    def first(self):
        return self.row


class _MappingResult:
    def __init__(self, row) -> None:
        self.row = row

    def mappings(self):
        return _MappingRows(self.row)


class _QueuedSession:
    def __init__(self, results) -> None:
        self.results = list(results)

    async def execute(self, *_args, **_kwargs):
        return self.results.pop(0)


class _SessionDatabase:
    def __init__(self, session) -> None:
        self.session_object = session

    @asynccontextmanager
    async def session(self):
        yield self.session_object


class ActivationGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_report_cannot_reach_binding_switch(self):
        database = _NoopDatabase()
        activator = EmbeddingGenerationActivator(database)  # type: ignore[arg-type]
        _, draft, report = _report_fixture(
            space_id=uuid4(),
            evidence=_evidence(observed_dimensions=7),
        )
        command = _activation_command(key="b", report=draft)
        switch = AsyncMock()
        with (
            patch(
                "app.infra.embedding_spaces.activator._lock_purpose",
                new=AsyncMock(),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_receipt_by_key",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_space_for_update",
                new=AsyncMock(return_value={"status": "ready"}),
            ),
            patch.object(
                activator._reports,
                "append_in_session",
                new=AsyncMock(return_value=report),
            ),
            patch(
                "app.infra.embedding_spaces.activator._switch",
                new=switch,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "embedding_calibration_failed",
            ):
                await activator.activate(command)

        switch.assert_not_awaited()

    async def test_passed_label_with_failed_check_cannot_switch(self):
        database = _NoopDatabase()
        activator = EmbeddingGenerationActivator(database)  # type: ignore[arg-type]
        _, draft, report = _report_fixture(
            space_id=uuid4(),
            force_passed_with_failed_row_check=True,
        )
        command = _activation_command(key="d", report=draft)
        switch = AsyncMock()
        with (
            patch(
                "app.infra.embedding_spaces.activator._lock_purpose",
                new=AsyncMock(),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_receipt_by_key",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_space_for_update",
                new=AsyncMock(return_value={"status": "ready"}),
            ),
            patch.object(
                activator._reports,
                "append_in_session",
                new=AsyncMock(return_value=report),
            ),
            patch(
                "app.infra.embedding_spaces.activator._switch",
                new=switch,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "embedding_calibration_checks_failed",
            ):
                await activator.activate(command)

        switch.assert_not_awaited()

    async def test_passed_report_switches_inside_the_owned_session(self):
        database = _NoopDatabase()
        activator = EmbeddingGenerationActivator(database)  # type: ignore[arg-type]
        _, draft, report = _report_fixture(space_id=uuid4())
        command = _activation_command(key="b", report=draft)
        receipt = EmbeddingActivationReceipt(
            id=uuid4(),
            purpose="documents",
            action="activate",
            from_space_id=uuid4(),
            to_space_id=command.to_space_id,
            calibration_report_id=report.id,
            idempotency_key=command.idempotency_key,
        )
        switch = AsyncMock(return_value=receipt)
        append_report = AsyncMock(return_value=report)
        with (
            patch(
                "app.infra.embedding_spaces.activator._lock_purpose",
                new=AsyncMock(),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_receipt_by_key",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_space_for_update",
                new=AsyncMock(return_value={"status": "ready"}),
            ),
            patch.object(
                activator._reports,
                "append_in_session",
                new=append_report,
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_active_space_id",
                new=AsyncMock(return_value=receipt.from_space_id),
            ),
            patch(
                "app.infra.embedding_spaces.activator._switch",
                new=switch,
            ),
        ):
            actual = await activator.activate(command)

        self.assertEqual(actual.receipt, receipt)
        self.assertEqual(actual.report, report)
        self.assertIs(
            append_report.await_args.args[0],
            database.session_object,
        )
        self.assertIs(switch.await_args.args[0], database.session_object)

    async def test_already_active_generation_cannot_create_noop_receipt(self):
        database = _NoopDatabase()
        activator = EmbeddingGenerationActivator(database)  # type: ignore[arg-type]
        _, draft, report = _report_fixture(space_id=uuid4())
        command = _activation_command(key="e", report=draft)
        switch = AsyncMock()
        with (
            patch(
                "app.infra.embedding_spaces.activator._lock_purpose",
                new=AsyncMock(),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_receipt_by_key",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_space_for_update",
                new=AsyncMock(return_value={"status": "active"}),
            ),
            patch.object(
                activator._reports,
                "append_in_session",
                new=AsyncMock(return_value=report),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_active_space_id",
                new=AsyncMock(return_value=command.to_space_id),
            ),
            patch(
                "app.infra.embedding_spaces.activator._switch",
                new=switch,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "embedding_generation_already_active",
            ):
                await activator.activate(command)

        switch.assert_not_awaited()

    async def test_rollback_uses_prior_receipt_and_appends_a_new_switch(self):
        current_space_id = uuid4()
        previous_space_id = uuid4()
        report_id = uuid4()
        session = _QueuedSession(
            [
                _ScalarResult(previous_space_id),
                _MappingResult(
                    {
                        "id": report_id,
                        "space_id": previous_space_id,
                        "status": "passed",
                        "dataset_sha256": "a" * 64,
                        "validation_checks": {
                            "dimensions": "passed",
                            "row_count": "passed",
                            "single_generation_query": "passed",
                        },
                    }
                ),
            ]
        )
        database = _SessionDatabase(session)
        activator = EmbeddingGenerationActivator(database)  # type: ignore[arg-type]
        command = EmbeddingRollbackCommand(
            purpose="documents",
            expected_dataset_sha256="a" * 64,
            idempotency_key="c" * 64,
        )
        receipt = EmbeddingActivationReceipt(
            id=uuid4(),
            purpose="documents",
            action="rollback",
            from_space_id=current_space_id,
            to_space_id=previous_space_id,
            calibration_report_id=report_id,
            idempotency_key=command.idempotency_key,
        )
        switch = AsyncMock(return_value=receipt)
        with (
            patch(
                "app.infra.embedding_spaces.activator._lock_purpose",
                new=AsyncMock(),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_receipt_by_key",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_active_space_id",
                new=AsyncMock(return_value=current_space_id),
            ),
            patch(
                "app.infra.embedding_spaces.activator._get_space_for_update",
                new=AsyncMock(return_value={"status": "ready"}),
            ),
            patch(
                "app.infra.embedding_spaces.activator._switch",
                new=switch,
            ),
        ):
            actual = await activator.rollback(command)

        self.assertEqual(actual, receipt)
        self.assertEqual(switch.await_args.kwargs["action"], "rollback")
        self.assertEqual(
            switch.await_args.kwargs["from_space_id"],
            current_space_id,
        )
        self.assertEqual(
            switch.await_args.kwargs["to_space_id"],
            previous_space_id,
        )


class _SemanticEmbeddings:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.calls = 0

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        vectors = [_semantic_vector(text) for text in texts]
        if self.invalid and vectors:
            vectors[-1] = [1.0]
        return vectors


def _semantic_vector(text: str) -> list[float]:
    lowered = text.lower()
    categories = (
        (
            "conversation",
            (
                "just say",
                "earlier in this chat",
                "刚才",
                "上面的对话",
                "回忆",
            ),
        ),
        (
            "memory",
            (
                "remember about me",
                "personal",
                "saved",
                "以前告诉",
                "个人信息",
                "我之前",
                "平时",
            ),
        ),
        (
            "weather",
            ("rain", "temperature", "weather", "天气", "气温", "降雨"),
        ),
        (
            "books",
            ("book", "novel", "书", "口碑"),
        ),
        (
            "research",
            ("research", "evidence", "source", "研究", "搜索", "证据", "来源"),
        ),
    )
    for index, (_, terms) in enumerate(categories):
        if any(term in lowered for term in terms):
            vector = [0.0] * 8
            vector[index] = 1.0
            return vector
    vector = [0.0] * 8
    vector[5 + (sum(ord(character) for character in text) % 3)] = 1.0
    return vector


class RoutingGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_atomic_swap_retains_previous_and_failed_build_keeps_active(self):
        recall = VectorPrototypeRecall(calibration_required=True)
        first = _SemanticEmbeddings()
        second = _SemanticEmbeddings()
        broken = _SemanticEmbeddings(invalid=True)

        await recall.ensure_index(first, "model-a")
        first_generation = recall.active_generation
        self.assertIsNotNone(first_generation)
        self.assertTrue(first_generation.calibrated)  # type: ignore[union-attr]

        await recall.ensure_index(second, "model-b")
        second_generation = recall.active_generation
        self.assertIs(recall.previous_generation, first_generation)
        self.assertNotEqual(
            first_generation.generation_fingerprint,  # type: ignore[union-attr]
            second_generation.generation_fingerprint,  # type: ignore[union-attr]
        )

        with self.assertRaises(ValueError):
            await recall.ensure_index(broken, "model-c")

        self.assertIs(recall.active_generation, second_generation)
        self.assertIs(recall.previous_generation, first_generation)


if __name__ == "__main__":
    unittest.main()
