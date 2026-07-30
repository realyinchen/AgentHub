from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_core.shadow_gate_contracts import (
    ShadowGateDataset,
    ShadowGateReport,
)
from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.shadow_gate_dataset_builder import (
    ShadowGateDatasetBuilder,
)
from app.services.agent_core.shadow_gate_evaluator import (
    ShadowGateEvaluator,
)
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateReadRequest,
)
from app.services.agent_core.shadow_gate_repository import (
    ShadowGateRepository,
)
from app.services.agent_core.shadow_review_artifact import (
    ShadowReviewArtifactLoader,
)


class ShadowGateResult(AgentCoreModel):
    dataset: ShadowGateDataset
    report: ShadowGateReport


class ShadowGateService:
    """Orchestrate read, review binding, pure build, and pure evaluation."""

    def __init__(
        self,
        *,
        repository: ShadowGateRepository | None = None,
        builder: ShadowGateDatasetBuilder | None = None,
        evaluator: ShadowGateEvaluator | None = None,
        review_loader: ShadowReviewArtifactLoader | None = None,
    ) -> None:
        self._repository = repository or ShadowGateRepository()
        self._builder = builder or ShadowGateDatasetBuilder()
        self._evaluator = evaluator or ShadowGateEvaluator()
        self._review_loader = (
            review_loader or ShadowReviewArtifactLoader()
        )

    async def evaluate(
        self,
        db: AsyncSession,
        request: ShadowGateReadRequest,
        *,
        review_artifact_path: str | Path | None = None,
    ) -> ShadowGateResult:
        raw = await self._repository.read(db, request)
        reviews = (
            self._review_loader.load(
                review_artifact_path,
                request=request,
            )
            if review_artifact_path is not None
            else None
        )
        dataset = self._builder.build(raw, reviews=reviews)
        return ShadowGateResult(
            dataset=dataset,
            report=self._evaluator.evaluate(dataset),
        )


__all__ = [
    "ShadowGateResult",
    "ShadowGateService",
]
