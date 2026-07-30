from __future__ import annotations

from collections.abc import Sequence

from app.services.agent_core.contracts import (
    ControllerOutput,
    PublishedAnswer,
)
from app.services.agent_core.publication.contracts import (
    ReceiptEvidenceBundle,
)
from app.services.agent_core.publication.deterministic import (
    DeterministicReceiptRenderer,
)
from app.services.agent_core.publication.policy import (
    validate_direct_text,
    validate_synthesis,
)
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt


class TrustedPublisher:
    """Select exactly one publication mode and return one typed answer."""

    def __init__(self, *, deterministic=None) -> None:
        self._deterministic = (
            deterministic or DeterministicReceiptRenderer()
        )

    def publish_direct(self, output: ControllerOutput) -> PublishedAnswer:
        if output.mode not in {"direct_answer", "request_clarification"}:
            raise ValueError("direct publication requires a text controller mode")
        content = validate_direct_text(output.text)
        return PublishedAnswer(
            status=(
                "clarification_required"
                if output.mode == "request_clarification"
                else "completed"
            ),
            content=content,
            receipt_backed=False,
            publication_mode="direct",
        )

    def publish_deterministic(
        self,
        plan: ActionPlan,
        receipt: PlanReceipt,
    ) -> PublishedAnswer:
        if plan.response_mode not in {"deterministic", "receipt"}:
            raise ValueError(
                "deterministic publication requires a receipt response mode"
            )
        return self._deterministic.render(plan, receipt)

    def publish_synthesis(
        self,
        output: ControllerOutput,
        *,
        evidence: Sequence[ReceiptEvidenceBundle],
    ) -> PublishedAnswer:
        if output.mode != "direct_answer":
            raise ValueError(
                "model synthesis requires a direct-answer model draft"
            )
        content = validate_synthesis(output.text, evidence=evidence)
        refs = [
            action.action_id
            for bundle in evidence
            for action in bundle.receipt.actions
            if action.status == "completed"
        ]
        if not refs:
            raise ValueError(
                "model synthesis requires completed receipt evidence"
            )
        return PublishedAnswer(
            status="completed",
            content=content,
            receipt_backed=True,
            receipt_refs=list(dict.fromkeys(refs)),
            publication_mode="model_synthesis",
        )


__all__ = ["TrustedPublisher"]
