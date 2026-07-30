from __future__ import annotations

from app.services.agent_core.contracts import (
    ControllerOutput,
    PublishedAnswer,
)
from app.services.agent_core.publication.service import TrustedPublisher
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt


class ResponsePublisher:
    """Compatibility facade for the R5 single-mode publisher."""

    def __init__(self, *, publisher: TrustedPublisher | None = None) -> None:
        self._publisher = publisher or TrustedPublisher()

    def publish_direct(self, output: ControllerOutput) -> PublishedAnswer:
        return self._publisher.publish_direct(output)

    def publish_receipt(
        self,
        plan: ActionPlan,
        receipt: PlanReceipt,
        *,
        draft: str = "",
    ) -> PublishedAnswer:
        if draft.strip():
            raise ValueError(
                "receipt drafts must use the explicit model synthesis mode"
            )
        return self._publisher.publish_deterministic(plan, receipt)


__all__ = ["ResponsePublisher"]
