from __future__ import annotations

from typing import Any, Protocol

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
)
from app.services.external_capabilities.contracts import (
    ExternalEvidenceSource,
    ResearchReportEvidence,
    ResearchStartInput,
)
from app.services.external_search.contracts import SearchRequest, SearchResult


class ResearchSearchGateway(Protocol):
    async def search(self, request: SearchRequest) -> SearchResult:
        ...


class ResearchPrepareAdapter:
    operation = "research_prepare_v1"

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        del context, previous
        request = ResearchStartInput.model_validate(arguments)
        queries = (
            request.subquestions[: request.max_rounds]
            if request.subquestions
            else [request.objective]
        )
        return {
            "status": "ok",
            "result_mode": "research_plan",
            "objective": request.objective,
            "mode": request.mode,
            "queries": queries,
            "constraints": request.constraints,
            "max_sources": request.max_sources,
            "time_range": request.time_range,
            "language": request.language,
        }


class ResearchSearchAdapter:
    operation = "research_search_v1"

    def __init__(
        self,
        *,
        search_gateway: ResearchSearchGateway | None = None,
    ) -> None:
        if search_gateway is None:
            from app.services.external_search import get_search_gateway

            search_gateway = get_search_gateway()
        self._search_gateway = search_gateway

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        del arguments, context
        plan = _require_output(previous, "research_prepare_v1")
        max_sources = max(3, min(int(plan.get("max_sources") or 8), 20))
        queries = [
            str(item).strip()
            for item in plan.get("queries", [])
            if str(item).strip()
        ]
        candidates: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for query in queries:
            result = await self._search_gateway.search(
                SearchRequest(
                    query=query,
                    max_results=max_sources,
                    detail=(
                        "deep"
                        if plan.get("mode") == "deep_research"
                        else "standard"
                    ),
                    time_range=plan.get("time_range"),
                    language=str(plan.get("language") or ""),
                    zone=(
                        "cn"
                        if str(plan.get("language") or "")
                        .lower()
                        .startswith("zh")
                        else None
                    ),
                )
            )
            for hit in result.hits:
                url = _bounded(hit.url, 2_000)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                candidates.append(
                    {
                        "title": _bounded(hit.title, 300),
                        "url": url,
                        "snippet": _bounded(hit.snippet, 1_000),
                        "published_date": _bounded(
                            hit.published_date,
                            64,
                        ),
                    }
                )
                if len(candidates) >= max_sources:
                    break
            if len(candidates) >= max_sources:
                break
        return {
            "status": "ok" if candidates else "empty_result",
            "result_mode": "research_source_candidates",
            "objective": str(plan.get("objective") or ""),
            "sources": candidates,
        }


class ResearchEvidenceAdmissionAdapter:
    operation = "research_admit_evidence_v1"

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        del context
        candidates = _require_output(previous, "research_search_v1")
        limit = max(3, min(int(arguments.get("max_sources") or 8), 20))
        admitted: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for payload in candidates.get("sources", []):
            if not isinstance(payload, dict):
                continue
            url = str(payload.get("url") or "").strip()
            snippet = str(payload.get("snippet") or "").strip()
            if (
                not url.lower().startswith(("https://", "http://"))
                or not snippet
                or url in seen_urls
            ):
                continue
            try:
                source = ExternalEvidenceSource.model_validate(payload)
            except Exception:
                continue
            seen_urls.add(url)
            admitted.append(source.model_dump(mode="json"))
            if len(admitted) >= limit:
                break
        return {
            "status": "ok" if admitted else "empty_result",
            "result_mode": "research_admitted_evidence",
            "objective": str(candidates.get("objective") or ""),
            "sources": admitted,
            "admission_policy": "http_attributable_nonempty_v1",
        }


class ResearchReportAdapter:
    operation = "research_report_v1"

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        del arguments, context
        evidence = _require_output(
            previous,
            "research_admit_evidence_v1",
        )
        sources = [
            ExternalEvidenceSource.model_validate(item)
            for item in evidence.get("sources", [])
            if isinstance(item, dict)
        ]
        report = ResearchReportEvidence(
            status="ok" if sources else "empty_result",
            objective=str(evidence.get("objective") or ""),
            findings=[
                source.snippet
                for source in sources
                if source.snippet
            ],
            sources=sources,
            limitations=(
                []
                if sources
                else ["没有通过证据准入的可引用公开来源。"]
            ),
            error="" if sources else "research_evidence_unavailable",
        )
        return report.model_dump(mode="json")


def _require_output(
    previous: list[ActionReceipt],
    operation: str,
) -> dict[str, Any]:
    for receipt in reversed(previous):
        if (
            receipt.operation == operation
            and receipt.status == "completed"
            and isinstance(receipt.output, dict)
        ):
            return receipt.output
    raise ValueError(f"required research receipt missing: {operation}")


def _bounded(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


__all__ = [
    "ResearchEvidenceAdmissionAdapter",
    "ResearchPrepareAdapter",
    "ResearchReportAdapter",
    "ResearchSearchAdapter",
    "ResearchSearchGateway",
]

