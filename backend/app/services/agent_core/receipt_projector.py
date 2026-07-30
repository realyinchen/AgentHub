from __future__ import annotations

from app.services.agent_core.prompt_contracts import TrustedReceiptContext
from app.services.agent_runtime.contracts import ActionReceipt, PlanReceipt
from app.services.external_capabilities.contracts import (
    BookEvidence,
    ResearchReportEvidence,
    WeatherEvidence,
    WebEvidence,
)


_SAFE_TEXT_FIELDS_BY_OPERATION: dict[str, tuple[str, ...]] = {
    "conversation_read": ("answer",),
}


class ReceiptContextProjector:
    """Create minimum allowlisted context for a later Controller round."""

    def project(
        self,
        receipt: PlanReceipt,
    ) -> list[TrustedReceiptContext]:
        projected = [_project_action(action) for action in receipt.actions]
        return projected[-32:]


def _project_action(action: ActionReceipt) -> TrustedReceiptContext:
    evidence = _typed_external_evidence(action)
    return TrustedReceiptContext(
        capability=action.capability,
        status=action.status,
        summary=_summary(action, evidence=evidence),
        result_mode=(
            str(evidence.get("result_mode") or "")
            if evidence is not None
            else ""
        ),
        facts=(
            list(evidence.get("facts") or [])
            if evidence is not None
            else []
        ),
        sources=(
            list(evidence.get("sources") or [])
            if evidence is not None
            else []
        ),
        limitations=(
            list(evidence.get("limitations") or [])
            if evidence is not None
            else []
        ),
    )


def _summary(
    action: ActionReceipt,
    *,
    evidence: dict | None,
) -> str:
    parts = [
        f"operation={action.operation}",
        f"status={action.status}",
    ]
    if evidence is not None:
        parts.extend(
            [
                f"result_mode={evidence.get('result_mode')}",
                f"evidence_sources={len(evidence.get('sources') or [])}",
            ]
        )
    output = action.output if isinstance(action.output, dict) else {}
    for field in _SAFE_TEXT_FIELDS_BY_OPERATION.get(action.operation, ()):
        value = _clean_text(output.get(field))
        if value:
            parts.append(f"{field}={value}")
    return "; ".join(parts)[:2_000]


def _typed_external_evidence(
    action: ActionReceipt,
) -> dict | None:
    output = action.output if isinstance(action.output, dict) else None
    if output is None:
        return None
    model_and_fields = {
        "weather_get_v1": (
            WeatherEvidence,
            {
                "result_mode",
                "status",
                "location",
                "date",
                "units",
                "sources",
                "error",
            },
        ),
        "web_search_v2": (
            WebEvidence,
            {
                "result_mode",
                "status",
                "query",
                "sources",
                "error",
            },
        ),
        "book_search_v1": (
            BookEvidence,
            {
                "result_mode",
                "status",
                "query",
                "sources",
                "error",
            },
        ),
        "research_report_v1": (
            ResearchReportEvidence,
            {
                "result_mode",
                "status",
                "objective",
                "findings",
                "sources",
                "limitations",
                "error",
            },
        ),
    }.get(action.operation)
    if model_and_fields is None:
        return None
    model, allowed_fields = model_and_fields
    try:
        validated = model.model_validate(
            {
                key: output[key]
                for key in allowed_fields
                if key in output
            }
        )
    except Exception:
        return None
    payload = validated.model_dump(mode="json")
    sources = payload.get("sources")
    safe_sources = sources if isinstance(sources, list) else []
    findings = payload.get("findings")
    facts = (
        [
            _clean_text(item)
            for item in findings
            if _clean_text(item)
        ]
        if isinstance(findings, list)
        else [
            _clean_text(item.get("snippet"))
            for item in safe_sources
            if isinstance(item, dict) and _clean_text(item.get("snippet"))
        ]
    )
    limitations = payload.get("limitations")
    return {
        "result_mode": str(payload.get("result_mode") or ""),
        "facts": facts[:20],
        "sources": safe_sources[:20],
        "limitations": (
            [
                _clean_text(item)
                for item in limitations
                if _clean_text(item)
            ][:10]
            if isinstance(limitations, list)
            else []
        ),
    }


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()[:1_600]


__all__ = ["ReceiptContextProjector"]
