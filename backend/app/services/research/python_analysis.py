from __future__ import annotations

import math
from collections import Counter
from statistics import fmean
from typing import Any

from pydantic import BaseModel, Field

from app.services.research.contracts import (
    EVIDENCE_SOURCE_TYPES,
    normalize_research_token,
    normalize_text,
)
from app.services.research.source_acquisition import (
    ResearchObservationBatch,
    ResearchSourceRecord,
    build_research_observation_batch,
)


RESEARCH_PYTHON_ANALYSIS_CONTRACT_VERSION = "research-python-analysis-v1"
MAX_ANALYSIS_RECORDS = 200
MAX_ANALYSIS_FIELDS = 20
MAX_FINDINGS = 10
MAX_CELL_TEXT = 240


class RejectedResearchPythonRecord(BaseModel):
    index: int
    reason_codes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchPythonAnalysisResult(BaseModel):
    result_mode: str = "research_python_analysis"
    contract_version: str = RESEARCH_PYTHON_ANALYSIS_CONTRACT_VERSION
    status: str
    query: str
    subquestion: str = ""
    analysis_type: str = "structured_records"
    source_title: str = ""
    source_url: str = ""
    record_count: int = 0
    analyzed_record_count: int = 0
    rejected_record_count: int = 0
    findings: list[ResearchSourceRecord] = Field(default_factory=list)
    observation_batch: ResearchObservationBatch
    finding_count: int = 0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def analyze_research_data(
    *,
    query: str,
    subquestion: str = "",
    records: list[dict[str, Any]] | None = None,
    dataset_title: str = "",
    source_url: str = "",
    source_type: str = "manual",
    focus_fields: list[str] | None = None,
    max_findings: int = 6,
    include_observation_batch: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ResearchPythonAnalysisResult:
    """Analyze caller-supplied structured records with deterministic Python.

    This adapter is intentionally not a Python code runner. It does not execute
    user-provided code, read files, access the network, write app state, or call
    provider transports. It only derives bounded numeric/categorical findings
    from records already supplied by an approved research step.
    """

    normalized_query = normalize_text(query)
    normalized_subquestion = normalize_text(subquestion)
    normalized_title = normalize_text(dataset_title) or "Supplied research data"
    normalized_url = normalize_text(source_url)
    normalized_source_type = _source_type(source_type)
    normalized_focus_fields = _clean_fields(focus_fields)
    source_items = list(records or [])
    limited_items = source_items[:MAX_ANALYSIS_RECORDS]

    analyzed_records: list[dict[str, Any]] = []
    rejected_records: list[RejectedResearchPythonRecord] = []
    for index, item in enumerate(limited_items):
        if not isinstance(item, dict):
            rejected_records.append(
                RejectedResearchPythonRecord(
                    index=index,
                    reason_codes=["record_not_object"],
                    metadata={"provider_raw": {"record_type": type(item).__name__}},
                )
            )
            continue
        cleaned = _clean_record(item)
        if not cleaned:
            rejected_records.append(
                RejectedResearchPythonRecord(
                    index=index,
                    reason_codes=["empty_record"],
                    metadata={"provider_raw": item},
                )
            )
            continue
        analyzed_records.append(cleaned)

    findings = _build_findings(
        query=normalized_query,
        subquestion=normalized_subquestion,
        records=analyzed_records,
        source_title=normalized_title,
        source_url=normalized_url,
        source_type=normalized_source_type,
        focus_fields=normalized_focus_fields,
        max_findings=max(1, min(int(max_findings or 6), MAX_FINDINGS)),
    )
    observation_batch = build_research_observation_batch(
        query=normalized_query,
        subquestion=normalized_subquestion,
        sources=[finding.model_dump(mode="json") for finding in findings],
        provider_source="python_analysis",
        metadata={
            **(metadata or {}),
            "python_analysis": {
                "contract_version": RESEARCH_PYTHON_ANALYSIS_CONTRACT_VERSION,
                "dataset_title": normalized_title,
                "source_url": normalized_url,
            },
        },
    )
    if not include_observation_batch:
        observation_batch = observation_batch.model_copy(
            update={
                "observations": [],
                "observation_count": 0,
            }
        )

    truncated_count = max(0, len(source_items) - len(limited_items))
    return ResearchPythonAnalysisResult(
        status=_result_status(analyzed_records, findings),
        query=normalized_query,
        subquestion=normalized_subquestion,
        source_title=normalized_title,
        source_url=normalized_url,
        record_count=len(source_items),
        analyzed_record_count=len(analyzed_records),
        rejected_record_count=len(rejected_records),
        findings=findings,
        observation_batch=observation_batch,
        finding_count=len(findings),
        metadata={
            **(metadata or {}),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "provider_source": "python_analysis",
            "analysis_engine": "local_python_deterministic",
            "executes_user_code": False,
            "reads_files": False,
            "network_access": False,
            "max_analysis_records": MAX_ANALYSIS_RECORDS,
            "truncated_record_count": truncated_count,
            "rejected_records": [
                rejected.model_dump(mode="json") for rejected in rejected_records
            ],
        },
    )


def _build_findings(
    *,
    query: str,
    subquestion: str,
    records: list[dict[str, Any]],
    source_title: str,
    source_url: str,
    source_type: str,
    focus_fields: list[str],
    max_findings: int,
) -> list[ResearchSourceRecord]:
    if not records:
        return []

    findings: list[ResearchSourceRecord] = []
    seen_keys: set[tuple[str, str]] = set()
    field_names = _field_order(records, focus_fields)
    focus_set = {field.lower() for field in focus_fields}

    for analysis_kind in ("numeric_summary", "categorical_top_value"):
        for field in field_names:
            key = (analysis_kind, field.lower())
            if key in seen_keys:
                continue
            if analysis_kind == "numeric_summary":
                finding = _numeric_finding(
                    field=field,
                    records=records,
                    source_title=source_title,
                    source_url=source_url,
                    source_type=source_type,
                    query=query,
                    subquestion=subquestion,
                    focused=field.lower() in focus_set,
                )
            else:
                finding = _categorical_finding(
                    field=field,
                    records=records,
                    source_title=source_title,
                    source_url=source_url,
                    source_type=source_type,
                    query=query,
                    subquestion=subquestion,
                    focused=field.lower() in focus_set,
                )
            if finding is None:
                continue
            findings.append(finding)
            seen_keys.add(key)
            if len(findings) >= max_findings:
                return findings
    return findings


def _numeric_finding(
    *,
    field: str,
    records: list[dict[str, Any]],
    source_title: str,
    source_url: str,
    source_type: str,
    query: str,
    subquestion: str,
    focused: bool,
) -> ResearchSourceRecord | None:
    values = _numeric_values(records, field)
    if not values:
        return None
    count = len(values)
    minimum = min(values)
    maximum = max(values)
    mean = fmean(values)
    field_label = _display_field(field)
    claim = (
        f"In {source_title}, field '{field_label}' has {count} numeric values "
        f"with mean {_format_number(mean)}, minimum {_format_number(minimum)}, "
        f"and maximum {_format_number(maximum)}."
    )
    excerpt = (
        f"Derived from {count} supplied records: field={field_label}; "
        f"mean={_format_number(mean)}; min={_format_number(minimum)}; "
        f"max={_format_number(maximum)}."
    )
    return ResearchSourceRecord(
        source_type=source_type,
        source_title=source_title,
        source_url=source_url,
        claim=claim,
        excerpt=excerpt,
        quality=_quality_for_count(count),
        relevance=_relevance_for_finding(query, subquestion, field, claim, focused),
        metadata={
            "provider_source": "python_analysis",
            "provider_raw": {
                "analysis_kind": "numeric_summary",
                "field": field,
                "count": count,
                "mean": mean,
                "min": minimum,
                "max": maximum,
            },
            "python_analysis": {
                "contract_version": RESEARCH_PYTHON_ANALYSIS_CONTRACT_VERSION,
                "analysis_kind": "numeric_summary",
            },
        },
    )


def _categorical_finding(
    *,
    field: str,
    records: list[dict[str, Any]],
    source_title: str,
    source_url: str,
    source_type: str,
    query: str,
    subquestion: str,
    focused: bool,
) -> ResearchSourceRecord | None:
    values = _categorical_values(records, field)
    if not values:
        return None
    counts = Counter(values)
    top_value, top_count = counts.most_common(1)[0]
    total = sum(counts.values())
    field_label = _display_field(field)
    claim = (
        f"In {source_title}, the most common value for '{field_label}' is "
        f"'{top_value}' ({top_count} of {total} records)."
    )
    count_excerpt = "; ".join(
        f"{value}={count}" for value, count in counts.most_common(5)
    )
    excerpt = (
        f"Derived counts for field '{field_label}' from {total} supplied "
        f"records: {count_excerpt}."
    )
    return ResearchSourceRecord(
        source_type=source_type,
        source_title=source_title,
        source_url=source_url,
        claim=claim,
        excerpt=excerpt,
        quality=_quality_for_count(total),
        relevance=_relevance_for_finding(query, subquestion, field, claim, focused),
        metadata={
            "provider_source": "python_analysis",
            "provider_raw": {
                "analysis_kind": "categorical_top_value",
                "field": field,
                "total": total,
                "top_value": top_value,
                "top_count": top_count,
                "counts": dict(counts.most_common(10)),
            },
            "python_analysis": {
                "contract_version": RESEARCH_PYTHON_ANALYSIS_CONTRACT_VERSION,
                "analysis_kind": "categorical_top_value",
            },
        },
    )


def _field_order(records: list[dict[str, Any]], focus_fields: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for field in focus_fields:
        key = field.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(field)
    for record in records:
        for field in record:
            clean = normalize_text(field)
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                ordered.append(clean)
            if len(ordered) >= MAX_ANALYSIS_FIELDS:
                return ordered
    return ordered[:MAX_ANALYSIS_FIELDS]


def _clean_fields(values: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = normalize_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned[:MAX_ANALYSIS_FIELDS]


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in record.items():
        field = normalize_text(key)
        if not field:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        text = normalize_text(value)
        if len(text) > MAX_CELL_TEXT:
            text = text[:MAX_CELL_TEXT]
        if text:
            cleaned[field] = value if isinstance(value, (int, float)) else text
    return cleaned


def _numeric_values(records: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for record in records:
        if field not in record:
            continue
        value = record.get(field)
        if isinstance(value, bool):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            values.append(numeric)
    return values


def _categorical_values(records: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    for record in records:
        if field not in record:
            continue
        value = record.get(field)
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, (int, float)):
            continue
        else:
            text = normalize_text(value)
        if text:
            values.append(text[:MAX_CELL_TEXT])
    return values


def _quality_for_count(count: int) -> str:
    if count >= 3:
        return "medium"
    if count >= 1:
        return "unknown"
    return "unknown"


def _relevance_for_finding(
    query: str,
    subquestion: str,
    field: str,
    claim: str,
    focused: bool,
) -> int:
    if focused:
        return 5
    terms = {
        term
        for term in f"{query} {subquestion}".lower().replace("/", " ").split()
        if len(term) >= 3
    }
    if not terms:
        return 3
    haystack = f"{field} {claim}".lower()
    matches = sum(1 for term in terms if term in haystack)
    if matches <= 0:
        return 3
    if matches >= 3:
        return 5
    return 3 + min(matches, 2)


def _result_status(
    analyzed_records: list[dict[str, Any]],
    findings: list[ResearchSourceRecord],
) -> str:
    if findings:
        return "ok"
    if analyzed_records:
        return "empty_result"
    return "empty_result"


def _source_type(value: Any) -> str:
    token = normalize_research_token(value or "manual")
    return token if token in EVIDENCE_SOURCE_TYPES else "other"


def _display_field(field: str) -> str:
    return normalize_text(field).replace("_", " ")


def _format_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")
