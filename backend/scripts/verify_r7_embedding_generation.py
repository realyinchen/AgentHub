"""Offline R7 verifier for calibrated embedding generation boundaries."""

# ruff: noqa: E402

from __future__ import annotations

import ast
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.config import Settings
from app.infra.embedding_spaces.calibration import (
    calibrate_embedding_generation,
)
from app.infra.embedding_spaces.calibration_contracts import (
    EmbeddingCalibrationScore,
    GenerationValidationEvidence,
)
from app.infra.embedding_spaces.calibration_dataset import (
    load_default_calibration_dataset,
)
from app.services.routing.contracts import RoutingQuery
from app.services.routing.funnel import RoutingFunnel
from scripts.init_database import _get_sorted_sql_files


class _ForbiddenSemantic:
    def __init__(self) -> None:
        self.calls = 0

    async def recall_with_batches(self, query):
        self.calls += 1
        raise AssertionError(f"Layer 0 invoked semantic recall: {query}")


async def _verify() -> None:
    artifact = load_default_calibration_dataset()
    assert len(artifact.dataset.samples) == 20
    assert sum(sample.relevant for sample in artifact.dataset.samples) == 10
    assert len(artifact.sha256) == 64

    result = calibrate_embedding_generation(
        artifact=artifact,
        scores=[
            EmbeddingCalibrationScore(
                sample_id=sample.sample_id,
                score=0.9 if sample.relevant else 0.1,
            )
            for sample in artifact.dataset.samples
        ],
        evidence=GenerationValidationEvidence(
            purpose="documents",
            expected_dimensions=2048,
            observed_dimensions=2048,
            source_count=10,
            embedded_count=10,
            stored_count=10,
            active_fact_filter="not_applicable",
            tenant_isolation="not_applicable",
            single_generation_query="passed",
        ),
    )
    assert result.status == "passed"
    assert result.threshold == 0.9
    assert result.dataset_sha256 == artifact.sha256

    semantic = _ForbiddenSemantic()
    decision = await RoutingFunnel(
        semantic_provider=semantic,  # type: ignore[arg-type]
    ).decide(RoutingQuery(text="我是谁？"))
    assert decision.metadata["layers_used"] == ["layer0_rule"]
    assert semantic.calls == 0

    migration = (
        BACKEND_ROOT / "scripts" / "sql" / "change_026_embedding_generation_gates.sql"
    ).read_text(encoding="utf-8")
    for token in (
        "embedding_calibration_reports",
        "embedding_space_activations",
        "ON DELETE RESTRICT",
        "BEFORE UPDATE OR DELETE",
        "idempotency_key",
        "source_watermark",
        "uq_embedding_calibration_space_dataset",
    ):
        assert token in migration

    migration_names = [Path(path).name for path in _get_sorted_sql_files()]
    assert migration_names.index(
        "change_025_agent_certification_v4_release_identity.sql"
    ) < migration_names.index("change_026_embedding_generation_gates.sql")

    activator_source = (
        BACKEND_ROOT / "app" / "infra" / "embedding_spaces" / "activator.py"
    ).read_text(encoding="utf-8")
    activator_tree = ast.parse(activator_source)
    assert any(isinstance(node, ast.AsyncWith) for node in ast.walk(activator_tree))
    for token in (
        "pg_advisory_xact_lock",
        "embedding_space_bindings",
        "embedding_space_activations",
        "embedding_calibration_failed",
        "embedding_calibration_dataset_mismatch",
        "append_in_session",
    ):
        assert token in activator_source

    runtime_source = (
        BACKEND_ROOT / "app" / "infra" / "embedding_spaces" / "runtime.py"
    ).read_text(encoding="utf-8")
    assert "EMBEDDING_GENERATION_GATES_V1" in runtime_source
    assert "self._activator.activate(" in runtime_source
    assert "bind_calibration_report(" in runtime_source
    assert "self._registry.activate(" not in runtime_source

    legacy_bridge_source = (
        BACKEND_ROOT / "app" / "infra" / "embedding_spaces" / "legacy_activation.py"
    ).read_text(encoding="utf-8")
    assert "self._registry.activate(" in legacy_bridge_source

    vector_source = (
        BACKEND_ROOT / "app" / "services" / "routing" / "vector_recall.py"
    ).read_text(encoding="utf-8")
    assert "best_score < generation.threshold" in vector_source
    assert "best_score < VECTOR_CANDIDATE_THRESHOLD" not in vector_source
    assert "_previous_generation" in vector_source

    assert Settings.model_fields["EMBEDDING_GENERATION_GATES_V1"].default is False
    print(
        "R7 embedding generation verification passed "
        f"(dataset_sha256={artifact.sha256})"
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(_verify())
