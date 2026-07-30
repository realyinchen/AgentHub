from __future__ import annotations

from app.services.agent_core.prompt_contracts import TrustedReceiptContext
from app.services.agent_runtime.contracts import ActionReceipt, PlanReceipt


_SAFE_TEXT_FIELDS_BY_OPERATION: dict[str, tuple[str, ...]] = {
    "conversation_read": ("answer",),
}


class ReceiptContextProjector:
    """Create minimum allowlisted context for a later Controller round."""

    def project(
        self,
        receipt: PlanReceipt,
    ) -> list[TrustedReceiptContext]:
        projected = [
            TrustedReceiptContext(
                capability=action.capability,
                status=action.status,
                summary=_summary(action),
            )
            for action in receipt.actions
        ]
        return projected[-32:]


def _summary(action: ActionReceipt) -> str:
    parts = [
        f"operation={action.operation}",
        f"status={action.status}",
    ]
    output = action.output if isinstance(action.output, dict) else {}
    for field in _SAFE_TEXT_FIELDS_BY_OPERATION.get(action.operation, ()):
        value = _clean_text(output.get(field))
        if value:
            parts.append(f"{field}={value}")
    return "; ".join(parts)[:2_000]


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()[:1_600]


__all__ = ["ReceiptContextProjector"]
