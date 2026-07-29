from __future__ import annotations

from typing import Any

from app.services.research.contracts import normalize_text
from app.services.research.evidence_quality import classify_source, source_quality
from app.services.research.loop.contracts import (
    ResearchRoundSources,
    ResearchSearchTask,
)
from app.services.research.source_extraction import (
    extract_research_source_records,
)


def project_research_search_output(
    *,
    task: ResearchSearchTask | dict[str, Any],
    provider_output: dict[str, Any],
) -> ResearchRoundSources:
    """Normalize one provider response without state writes or external calls."""

    search_task = ResearchSearchTask.model_validate(task)
    if not search_task.should_search:
        return ResearchRoundSources(
            round_index=search_task.round_index,
            executed=False,
            task=search_task,
            provider_status="not_requested",
            metadata={"execution_disposition": "no_op"},
        )

    output = dict(provider_output or {})
    execution_status = str(
        output.get("execution_status") or output.get("status") or ""
    ).strip().lower()
    provider_status = str(
        output.get("outcome") or output.get("status") or ""
    ).strip().lower()
    if execution_status not in {"ok", "completed", "success"}:
        return ResearchRoundSources(
            status="failed",
            round_index=search_task.round_index,
            task=search_task,
            provider=str(output.get("provider") or ""),
            provider_status=provider_status or "failed",
            provider_error_type=str(output.get("error_type") or ""),
            error=str(output.get("error") or "research source provider failed"),
            metadata={"provider_metadata": output.get("metadata") or {}},
        )
    if provider_status == "unavailable":
        return ResearchRoundSources(
            round_index=search_task.round_index,
            task=search_task,
            provider=str(output.get("provider") or ""),
            provider_status="unavailable",
            provider_error_type=_last_attempt_error_type(output),
            error=str(output.get("error") or "external search is unavailable"),
            source_count=0,
            publishable_source_count=0,
            metadata={
                "provider_metadata": output.get("metadata") or {},
                "attempts": output.get("attempts") or [],
                "execution_disposition": "executed_without_result",
            },
        )

    documents = _source_documents(output)
    extraction = extract_research_source_records(
        query=search_task.query,
        subquestion=search_task.objective,
        documents=documents,
        provider_source=str(output.get("provider") or "web_search"),
        max_records_per_document=1,
        metadata={
            "research_round": search_task.round_index,
            "target_gaps": search_task.target_gaps,
        },
    )
    reason_codes = list(
        dict.fromkeys(
            reason
            for document in extraction.rejected_documents
            for reason in document.reason_codes
        )
    )
    return ResearchRoundSources(
        round_index=search_task.round_index,
        task=search_task,
        provider=str(output.get("provider") or "web_search"),
        provider_status=provider_status,
        source_records=extraction.source_records,
        rejected_documents=extraction.rejected_documents,
        source_count=extraction.document_count,
        publishable_source_count=extraction.extracted_count,
        rejection_reason_codes=reason_codes,
        metadata={
            "provider_metadata": output.get("metadata") or {},
            "attempts": output.get("attempts") or [],
            "extraction_status": extraction.status,
            "execution_disposition": "executed",
        },
    )


def _source_documents(output: dict[str, Any]) -> list[dict[str, Any]]:
    existing = _nested(output, ("extraction", "source_records"))
    if not isinstance(existing, list):
        existing = output.get("source_records")
    if isinstance(existing, list) and existing:
        return [
            item
            for item in existing
            if isinstance(item, dict)
        ]

    result = output.get("result")
    hits = result.get("results") if isinstance(result, dict) else None
    if not isinstance(hits, list):
        hits = output.get("hits")
    if not isinstance(hits, list):
        hits = output.get("source_documents")
    documents: list[dict[str, Any]] = []
    for item in hits if isinstance(hits, list) else []:
        if not isinstance(item, dict):
            continue
        content = normalize_text(
            item.get("content")
            or item.get("snippet")
            or item.get("excerpt")
            or item.get("raw_content")
            or ""
        )
        title = normalize_text(item.get("title") or item.get("source_title"))
        url = normalize_text(item.get("url") or item.get("source_url"))
        if not content or not (title or url):
            continue
        score = item.get("score")
        relevance = 3
        if isinstance(score, (int, float)):
            relevance = max(1, min(5, round(float(score) * 5)))
        published_date = normalize_text(
            item.get("published_date")
            or item.get("published_at")
            or item.get("date")
        )
        source_class = classify_source(url)
        documents.append(
            {
                "source_type": "web",
                "source_title": title,
                "source_url": url,
                "content": content[:4000],
                "quality": source_quality(source_class),
                "relevance": relevance,
                "published_date": published_date,
                "metadata": {
                    "provider_source": str(
                        output.get("provider") or "web_search"
                    ),
                    "search_query": str(output.get("query") or ""),
                    "source_class": source_class,
                    "published_date": published_date,
                },
            }
        )
    return documents


def _last_attempt_error_type(output: dict[str, Any]) -> str:
    attempts = output.get("attempts")
    if not isinstance(attempts, list):
        return str(output.get("error_type") or "")
    for attempt in reversed(attempts):
        if isinstance(attempt, dict) and attempt.get("error_type"):
            return str(attempt["error_type"])
    return str(output.get("error_type") or "")


def _nested(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
