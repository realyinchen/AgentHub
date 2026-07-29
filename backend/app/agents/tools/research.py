"""Research state tools for Deep Search / Deep Research."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.infra.database import get_database
from app.services.recommendation_constraints import (
    build_personalized_recommendation_constraints,
)
from app.services.research import (
    ResearchEvidence,
    ResearchObservation,
    analyze_research_data as analyze_research_data_result,
    build_research_observation_batch,
    build_research_report as build_research_report_result,
    collect_research_sources as collect_research_sources_result,
    extract_research_source_records as extract_research_source_records_result,
    fetch_research_source_document as fetch_research_source_document_result,
    finalize_research_answer as finalize_research_answer_result,
    get_research_orchestrator,
    run_research_runtime as run_research_runtime_result,
    search_research_scholar_documents as search_research_scholar_documents_result,
    search_research_source_documents as search_research_source_documents_result,
)
from app.services.recommendation_research_report import (
    build_recommendation_research_report as build_recommendation_research_report_result,
)
from app.services.recommendation_research_runner import (
    RECOMMENDATION_RESEARCH_RUNNER_CONTRACT_VERSION,
    run_recommendation_research_workflow as run_recommendation_research_workflow_result,
)
from app.services.recommendation_research_workflow import (
    RECOMMENDATION_RESEARCH_WORKFLOW_CONTRACT_VERSION,
    plan_recommendation_research_workflow as plan_recommendation_research_workflow_result,
)
from app.services.tool_admission import (
    ToolAdmissionResult,
    ToolPolicyDeclaration,
    get_tool_admission_gate,
)


START_RESEARCH_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="start_research",
    required_policy_flags=["can_start_research"],
    side_effect_scope="research_state",
    writes_research_state=True,
    blocked_status="tool_blocked",
)
RESEARCH_STATE_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="research_state_tool",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="research_state",
    writes_research_state=True,
    blocked_status="tool_blocked",
)
BUILD_RESEARCH_REPORT_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="build_research_report",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="none",
    blocked_status="tool_blocked",
)
FINALIZE_RESEARCH_ANSWER_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="finalize_research_answer",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="none",
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-final-answer-v1"},
)
BUILD_RECOMMENDATION_RESEARCH_REPORT_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="build_recommendation_research_report",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="none",
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": "recommendation-research-report-v1"},
)
PLAN_RECOMMENDATION_RESEARCH_WORKFLOW_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="plan_recommendation_research_workflow",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="none",
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": RECOMMENDATION_RESEARCH_WORKFLOW_CONTRACT_VERSION},
)
RUN_RECOMMENDATION_RESEARCH_WORKFLOW_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="run_recommendation_research_workflow",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="research_state",
    writes_research_state=True,
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": RECOMMENDATION_RESEARCH_RUNNER_CONTRACT_VERSION},
)
BUILD_RESEARCH_OBSERVATIONS_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="build_research_observations",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="none",
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-observation-batch-v1"},
)
ANALYZE_RESEARCH_DATA_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="analyze_research_data",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="none",
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-python-analysis-v1"},
)
EXTRACT_RESEARCH_SOURCE_RECORDS_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="extract_research_source_records",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="none",
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-source-extraction-v1"},
)
SEARCH_RESEARCH_SOURCES_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="search_research_sources",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="external_call",
    external_call=True,
    max_calls_per_turn=3,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-source-search-v1"},
)
SEARCH_RESEARCH_SCHOLAR_SOURCES_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="search_research_scholar_sources",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="external_call",
    external_call=True,
    max_calls_per_turn=3,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-scholar-search-v1"},
)
FETCH_RESEARCH_SOURCE_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="fetch_research_source",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="external_call",
    external_call=True,
    max_calls_per_turn=5,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-source-visit-v1"},
)
COLLECT_RESEARCH_SOURCES_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="collect_research_sources",
    required_policy_flags=["can_use_research_tools"],
    side_effect_scope="research_state",
    writes_research_state=True,
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"contract_version": "research-source-collection-v1"},
)
RUN_RESEARCH_HARNESS_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="run_research_harness",
    required_policy_flags=["can_start_research", "can_use_research_tools"],
    side_effect_scope="research_state",
    writes_research_state=True,
    external_call=False,
    blocked_status="tool_blocked",
    metadata={"provider_mode": "source_observations"},
)


class StartResearchInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    objective: str = Field(description="Concrete research objective.")
    thread_id: UUID | None = Field(
        default=None,
        description="Current conversation thread ID for traceability.",
    )
    mode: str = Field(default="deep_search", description="deep_search or deep_research.")
    subquestions: list[str] = Field(
        default_factory=list,
        description="Initial subquestions the research must answer.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Known unknowns at the start of the research run.",
    )
    next_actions: list[str] = Field(
        default_factory=list,
        description="Planned next actions for the first research steps.",
    )
    budget: dict[str, Any] = Field(
        default_factory=dict,
        description="Research budget, e.g. max_steps, max_sources, max_minutes.",
    )
    stop_criteria: list[str] = Field(
        default_factory=list,
        description="Explicit conditions for stopping the research run.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class InspectResearchStateInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    limit_steps: int = Field(default=20, ge=1, le=100)
    limit_evidence: int = Field(default=20, ge=1, le=100)


class SearchResearchInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    query: str = Field(description="Search query attempted for this research run.")
    status: str = Field(
        default="completed",
        description="planned, running, completed, empty_result, timeout, failed, or skipped.",
    )
    rationale: str = Field(default="", description="Why this query was attempted.")
    results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional structured search result summaries; not long-term memory.",
    )
    next_actions: list[str] = Field(
        default_factory=list,
        description="Updated next actions after this search attempt.",
    )
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = None


class VisitSourceInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    url: str = Field(description="Source URL visited.")
    title: str = Field(default="", description="Source title, if known.")
    status: str = Field(default="completed")
    summary: str = Field(
        default="",
        description="Short source summary. Detailed claims should use add_evidence.",
    )
    rationale: str = Field(default="", description="Why this source was visited.")
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = None


class AddEvidenceInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    source_type: str = Field(default="web", description="web, book, paper, user, manual, or other.")
    source_title: str = Field(default="")
    source_url: str = Field(default="")
    claim: str = Field(description="Atomic claim supported by the source.")
    excerpt: str = Field(
        default="",
        description="Brief supporting excerpt or paraphrase. Required for evidence admission.",
    )
    quality: str = Field(default="unknown", description="high, medium, low, or unknown.")
    relevance: int = Field(default=3, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)
    known_facts: list[str] = Field(
        default_factory=list,
        description="Known facts to add to research state; defaults to the claim.",
    )
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class UpdateResearchStateInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    subquestions: list[str] | None = None
    known_facts: list[str] | None = None
    gaps: list[str] | None = None
    conflicts: list[str] | None = None
    exhausted_queries: list[str] | None = None
    next_actions: list[str] | None = None
    budget: dict[str, Any] | None = None
    stop_criteria: list[str] | None = None
    metadata: dict[str, Any] | None = None
    replace: bool = Field(
        default=False,
        description="False appends/merges unique items. True replaces provided fields.",
    )


class FinishResearchInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    conclusion: str = Field(description="Concise final answer or stopping rationale.")
    status: str = Field(default="completed", description="completed, cancelled, or failed.")
    known_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BuildResearchReportInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    limit_steps: int = Field(default=100, ge=1, le=100)
    limit_evidence: int = Field(default=100, ge=1, le=100)


class FinalizeResearchAnswerInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Research run ID.")
    limit_steps: int = Field(default=100, ge=1, le=100)
    limit_evidence: int = Field(default=100, ge=1, le=100)


class BuildRecommendationResearchReportInput(BaseModel):
    query: str = Field(default="", description="Original recommendation/research query.")
    candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Book candidates, normally from search_books.books. This tool does "
            "not perform book search."
        ),
    )
    research_report: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Existing research-report-v1 payload. Only verified_claims may "
            "support recommendation candidates."
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanRecommendationResearchWorkflowInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    query: str = Field(default="", description="Original researched recommendation query.")
    candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Existing fresh book candidates, normally from search_books.books.",
    )
    research_report: dict[str, Any] = Field(
        default_factory=dict,
        description="Existing research-report-v1 payload, if already available.",
    )
    research_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Existing ResearchStateResult payload, if available.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunRecommendationResearchWorkflowInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    query: str = Field(default="", description="Original researched recommendation query.")
    candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Existing fresh book candidates, normally from search_books.books. "
            "This tool does not perform book search."
        ),
    )
    research_report: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Existing research-report-v1 payload. If valid and verified, the "
            "tool can fuse without running the local harness."
        ),
    )
    observations: list[ResearchObservation] = Field(
        default_factory=list,
        description=(
            "App-owned source-backed observations. If a verified report is not "
            "ready, the tool can run the local harness over these observations."
        ),
    )
    thread_id: UUID | None = Field(default=None)
    mode: str = Field(default="deep_research", description="deep_search or deep_research.")
    subquestions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    allow_runtime: bool = Field(
        default=True,
        description="False disables local harness execution and only performs planning/fusion.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    limit_steps: int = Field(default=100, ge=1, le=100)
    limit_evidence: int = Field(default=100, ge=1, le=100)


class BuildResearchObservationsInput(BaseModel):
    query: str = Field(default="", description="Search or source query.")
    subquestion: str = Field(default="", description="Research subquestion.")
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Source records to normalize. Each accepted source needs a claim, "
            "excerpt, and source_title or source_url."
        ),
    )
    provider_source: str = Field(
        default="source_acquisition",
        description="Name of the approved source/search tool that produced records.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalyzeResearchDataInput(BaseModel):
    query: str = Field(description="Research question for the supplied data.")
    subquestion: str = Field(default="", description="Research subquestion.")
    records: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Caller-supplied structured records to analyze. This tool does not "
            "accept or execute Python code, read files, or access the network."
        ),
    )
    dataset_title: str = Field(
        default="",
        description="Source title for the supplied records.",
    )
    source_url: str = Field(default="", description="Optional source URL.")
    source_type: str = Field(
        default="manual",
        description="web, book, paper, user, manual, or other.",
    )
    focus_fields: list[str] = Field(
        default_factory=list,
        description="Optional fields to prioritize for numeric/categorical analysis.",
    )
    max_findings: int = Field(default=6, ge=1, le=10)
    include_observation_batch: bool = Field(
        default=True,
        description="Whether to return nested research-observation-batch-v1.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractResearchSourceRecordsInput(BaseModel):
    query: str = Field(default="", description="Search/source query.")
    subquestion: str = Field(default="", description="Research subquestion.")
    documents: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Approved search/visit result documents. The tool extracts source "
            "sentences as claim/excerpt pairs without external calls."
        ),
    )
    provider_source: str = Field(
        default="source_extraction",
        description="Name of the approved search/visit tool that produced documents.",
    )
    max_records_per_document: int = Field(default=1, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResearchSourcesInput(BaseModel):
    query: str = Field(description="Research source search query.")
    subquestion: str = Field(default="", description="Research subquestion.")
    limit: int = Field(default=5, ge=1, le=10)
    provider_query: str = Field(
        default="",
        description="Optional provider-native query override.",
    )
    provider_source: str = Field(
        default="external_search",
        description="External search gateway; provider selection is automatic.",
    )
    include_extraction: bool = Field(
        default=True,
        description="Whether to return nested research-source-extraction-v1.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResearchScholarSourcesInput(BaseModel):
    query: str = Field(description="Research scholarly/paper source search query.")
    subquestion: str = Field(default="", description="Research subquestion.")
    limit: int = Field(default=5, ge=1, le=10)
    provider_query: str = Field(
        default="",
        description="Optional provider-native query override.",
    )
    provider_source: str = Field(
        default="crossref",
        description="Approved scholarly source provider. Currently crossref.",
    )
    include_extraction: bool = Field(
        default=True,
        description="Whether to return nested research-source-extraction-v1.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class FetchResearchSourceInput(BaseModel):
    url: str = Field(description="Approved http/https source URL to fetch.")
    query: str = Field(default="", description="Research query for extraction scoring.")
    subquestion: str = Field(default="", description="Research subquestion.")
    provider_source: str = Field(default="source_visit")
    include_extraction: bool = Field(
        default=True,
        description="Whether to return nested research-source-extraction-v1.",
    )
    timeout_seconds: int = Field(default=12, ge=1, le=30)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectResearchSourcesInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    run_id: UUID = Field(description="Existing research run ID.")
    query: str = Field(description="Search/source query represented by these records.")
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Source records from an approved search/visit tool. Accepted "
            "records require claim, excerpt, and source_title or source_url."
        ),
    )
    subquestion: str = Field(default="")
    provider_source: str = Field(default="source_collection")
    status: str = Field(default="completed")
    rationale: str = Field(default="")
    next_actions: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunResearchHarnessInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    objective: str = Field(description="Concrete research objective.")
    thread_id: UUID | None = Field(
        default=None,
        description="Current conversation thread ID for traceability.",
    )
    mode: str = Field(default="deep_research", description="deep_search or deep_research.")
    subquestions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    observations: list[ResearchObservation] = Field(
        default_factory=list,
        description=(
            "App-owned normalized observations collected by an approved "
            "research/source tool. The local harness does not call live "
            "mem0 or gbrain transports."
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    limit_steps: int = Field(default=100, ge=1, le=100)
    limit_evidence: int = Field(default=100, ge=1, le=100)


def _dump_result(result) -> str:
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


def _tool_blocked_payload(
    admission: ToolAdmissionResult,
    *,
    writes_research_state: bool,
) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "tool_name": admission.tool_name,
            "run": None,
            "state": None,
            "steps": [],
            "evidence": [],
            "provider_sources": [],
            "tool_admission": admission.model_dump(mode="json"),
            "writes_research_state": writes_research_state,
        },
        ensure_ascii=False,
    )


def _runtime_needs_observations_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": "needs_observations",
            "result_mode": "research_runtime",
            "contract_version": "research-runtime-v1",
            "run_id": None,
            "report": None,
            "harness": None,
            "metadata": {
                "reason": "at_least_one_research_observation_is_required",
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
                "provider_mode": "source_observations",
            },
        },
        ensure_ascii=False,
    )


def _observation_batch_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_observation_batch",
            "contract_version": "research-observation-batch-v1",
            "query": "",
            "subquestion": "",
            "observations": [],
            "rejected_sources": [],
            "source_count": 0,
            "observation_count": 0,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _python_analysis_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_python_analysis",
            "contract_version": "research-python-analysis-v1",
            "query": "",
            "subquestion": "",
            "analysis_type": "structured_records",
            "source_title": "",
            "source_url": "",
            "record_count": 0,
            "analyzed_record_count": 0,
            "rejected_record_count": 0,
            "findings": [],
            "observation_batch": None,
            "finding_count": 0,
            "error": None,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
                "executes_user_code": False,
                "reads_files": False,
                "network_access": False,
            },
        },
        ensure_ascii=False,
    )


def _source_extraction_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_source_extraction",
            "contract_version": "research-source-extraction-v1",
            "query": "",
            "subquestion": "",
            "source_records": [],
            "observation_batch": None,
            "rejected_documents": [],
            "document_count": 0,
            "extracted_count": 0,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _source_search_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_source_search",
            "contract_version": "research-source-search-v1",
            "query": "",
            "subquestion": "",
            "provider_name": "",
            "provider_query": "",
            "source_documents": [],
            "extraction": None,
            "document_count": 0,
            "extracted_count": 0,
            "error": None,
            "duration_ms": 0,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _scholar_search_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_scholar_search",
            "contract_version": "research-scholar-search-v1",
            "query": "",
            "subquestion": "",
            "provider_name": "",
            "provider_query": "",
            "source_documents": [],
            "extraction": None,
            "document_count": 0,
            "extracted_count": 0,
            "error": None,
            "duration_ms": 0,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _source_visit_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_source_visit",
            "contract_version": "research-source-visit-v1",
            "url": "",
            "final_url": "",
            "query": "",
            "subquestion": "",
            "source_document": None,
            "extraction": None,
            "extracted_count": 0,
            "error": None,
            "duration_ms": 0,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _final_answer_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_final_answer",
            "contract_version": "research-final-answer-v1",
            "run_id": None,
            "objective": "",
            "report_status": "",
            "answer_status": "tool_blocked",
            "answer": "",
            "verified_claims": [],
            "omitted_uncertain_claims": [],
            "omitted_rejected_claims": [],
            "limitations": [],
            "sources": [],
            "ready_for_final_answer": False,
            "can_finalize_with_uncertainty": False,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _recommendation_research_report_blocked_payload(
    admission: ToolAdmissionResult,
) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "recommendation_research_report",
            "contract_version": "recommendation-research-report-v1",
            "query": "",
            "research_run_id": "",
            "research_report_status": "",
            "research_report_contract_version": "",
            "candidates": [],
            "recommended_candidates": [],
            "suppressed_candidates": [],
            "unsupported_candidates": [],
            "candidate_count": 0,
            "supported_count": 0,
            "suppressed_count": 0,
            "verified_claim_count": 0,
            "limitations": [],
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
                "uses_verified_claims_only": True,
            },
        },
        ensure_ascii=False,
    )


def _recommendation_research_workflow_blocked_payload(
    admission: ToolAdmissionResult,
) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "recommendation_research_workflow",
            "contract_version": RECOMMENDATION_RESEARCH_WORKFLOW_CONTRACT_VERSION,
            "query": "",
            "ready_to_fuse": False,
            "candidate_count": 0,
            "fresh_candidate_count": 0,
            "suppressed_candidate_count": 0,
            "research_run_id": "",
            "research_report_status": "",
            "research_report_contract_version": "",
            "verified_claim_count": 0,
            "missing_inputs": [],
            "recommended_next_tools": [],
            "next_action_hint": "",
            "workflow_steps": [],
            "personalization_constraints": None,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _recommendation_research_runner_blocked_payload(
    admission: ToolAdmissionResult,
) -> str:
    workflow_payload = {
        "status": "tool_blocked",
        "result_mode": "recommendation_research_workflow",
        "contract_version": RECOMMENDATION_RESEARCH_WORKFLOW_CONTRACT_VERSION,
        "query": "",
        "ready_to_fuse": False,
        "candidate_count": 0,
        "fresh_candidate_count": 0,
        "suppressed_candidate_count": 0,
        "research_run_id": "",
        "research_report_status": "",
        "research_report_contract_version": "",
        "verified_claim_count": 0,
        "missing_inputs": [],
        "recommended_next_tools": [],
        "next_action_hint": "",
        "workflow_steps": [],
        "personalization_constraints": None,
        "metadata": {},
    }
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "recommendation_research_runner",
            "contract_version": RECOMMENDATION_RESEARCH_RUNNER_CONTRACT_VERSION,
            "query": "",
            "workflow_before": workflow_payload,
            "workflow_after": workflow_payload,
            "runtime": None,
            "research_report": None,
            "recommendation_report": None,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_evidence": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _source_collection_blocked_payload(admission: ToolAdmissionResult) -> str:
    return json.dumps(
        {
            "status": admission.blocked_status or "tool_blocked",
            "result_mode": "research_source_collection",
            "contract_version": "research-source-collection-v1",
            "run_id": None,
            "query": "",
            "observation_batch": None,
            "research_state": None,
            "metadata": {
                "tool_admission": admission.model_dump(mode="json"),
                "writes_research_state": False,
                "writes_long_term_memory": False,
                "writes_recommendation_events": False,
                "writes_evidence": False,
                "external_call": False,
            },
        },
        ensure_ascii=False,
    )


def _admit_research_state_tool(tool_name: str) -> ToolAdmissionResult:
    return get_tool_admission_gate().admit_current_turn(
        RESEARCH_STATE_TOOL_POLICY.model_copy(update={"tool_name": tool_name})
    )


async def _personalization_constraints_for_tool(
    *,
    user_id: UUID,
    query: str,
    metadata: dict[str, Any],
):
    try:
        async with get_database().session() as session:
            return await build_personalized_recommendation_constraints(
                session,
                user_id=user_id,
                query=query,
            )
    except Exception as exc:
        metadata["personalization_constraints_error"] = (
            str(exc) or exc.__class__.__name__
        )
        return None


@tool(args_schema=StartResearchInput)
async def start_research(
    user_id: UUID,
    objective: str,
    thread_id: UUID | None = None,
    mode: str = "deep_search",
    subquestions: list[str] | None = None,
    gaps: list[str] | None = None,
    next_actions: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    stop_criteria: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Start a structured Deep Search / Deep Research run."""
    admission = get_tool_admission_gate().admit_current_turn(START_RESEARCH_TOOL_POLICY)
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=True)

    result = await get_research_orchestrator().start_research(
        user_id=user_id,
        objective=objective,
        thread_id=thread_id,
        mode=mode,
        subquestions=subquestions,
        gaps=gaps,
        next_actions=next_actions,
        budget=budget,
        stop_criteria=stop_criteria,
        metadata=metadata,
    )
    return _dump_result(result)


@tool(args_schema=InspectResearchStateInput)
async def inspect_research_state(
    user_id: UUID,
    run_id: UUID,
    limit_steps: int = 20,
    limit_evidence: int = 20,
) -> str:
    """Inspect the current structured state for a research run."""
    admission = _admit_research_state_tool("inspect_research_state")
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=False)

    result = await get_research_orchestrator().inspect_research_state(
        user_id=user_id,
        run_id=run_id,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    return _dump_result(result)


@tool(args_schema=SearchResearchInput)
async def search_research(
    user_id: UUID,
    run_id: UUID,
    query: str,
    status: str = "completed",
    rationale: str = "",
    results: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
    duration_ms: int = 0,
    error: str | None = None,
) -> str:
    """Record one research search attempt and update structured state."""
    admission = _admit_research_state_tool("search_research")
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=True)

    result = await get_research_orchestrator().search_research(
        user_id=user_id,
        run_id=run_id,
        query=query,
        status=status,
        rationale=rationale,
        results=results,
        next_actions=next_actions,
        duration_ms=duration_ms,
        error=error,
    )
    return _dump_result(result)


@tool(args_schema=VisitSourceInput)
async def visit_source(
    user_id: UUID,
    run_id: UUID,
    url: str,
    title: str = "",
    status: str = "completed",
    summary: str = "",
    rationale: str = "",
    duration_ms: int = 0,
    error: str | None = None,
) -> str:
    """Record a source visit inside a research run."""
    admission = _admit_research_state_tool("visit_source")
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=True)

    result = await get_research_orchestrator().visit_source(
        user_id=user_id,
        run_id=run_id,
        url=url,
        title=title,
        status=status,
        summary=summary,
        rationale=rationale,
        duration_ms=duration_ms,
        error=error,
    )
    return _dump_result(result)


@tool(args_schema=AddEvidenceInput)
async def add_evidence(
    user_id: UUID,
    run_id: UUID,
    claim: str,
    source_type: str = "web",
    source_title: str = "",
    source_url: str = "",
    excerpt: str = "",
    quality: str = "unknown",
    relevance: int = 3,
    metadata: dict[str, Any] | None = None,
    known_facts: list[str] | None = None,
    gaps: list[str] | None = None,
    conflicts: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> str:
    """Submit evidence to research state through Evidence Admission."""
    admission = _admit_research_state_tool("add_evidence")
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=True)

    evidence = ResearchEvidence(
        run_id=run_id,
        source_type=source_type,
        source_title=source_title,
        source_url=source_url,
        claim=claim,
        excerpt=excerpt,
        quality=quality,
        relevance=relevance,
        metadata=metadata or {},
    )
    result = await get_research_orchestrator().add_evidence(
        user_id=user_id,
        run_id=run_id,
        evidence=evidence,
        known_facts=known_facts,
        gaps=gaps,
        conflicts=conflicts,
        next_actions=next_actions,
    )
    return _dump_result(result)


@tool(args_schema=UpdateResearchStateInput)
async def update_research_state(
    user_id: UUID,
    run_id: UUID,
    subquestions: list[str] | None = None,
    known_facts: list[str] | None = None,
    gaps: list[str] | None = None,
    conflicts: list[str] | None = None,
    exhausted_queries: list[str] | None = None,
    next_actions: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    stop_criteria: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    replace: bool = False,
) -> str:
    """Update structured research state without writing long-term memory."""
    admission = _admit_research_state_tool("update_research_state")
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=True)

    result = await get_research_orchestrator().update_research_state(
        user_id=user_id,
        run_id=run_id,
        subquestions=subquestions,
        known_facts=known_facts,
        gaps=gaps,
        conflicts=conflicts,
        exhausted_queries=exhausted_queries,
        next_actions=next_actions,
        budget=budget,
        stop_criteria=stop_criteria,
        metadata=metadata,
        replace=replace,
    )
    return _dump_result(result)


@tool(args_schema=FinishResearchInput)
async def finish_research(
    user_id: UUID,
    run_id: UUID,
    conclusion: str,
    status: str = "completed",
    known_facts: list[str] | None = None,
    gaps: list[str] | None = None,
    conflicts: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Finish a research run with final state and stopping rationale."""
    admission = _admit_research_state_tool("finish_research")
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=True)

    result = await get_research_orchestrator().finish_research(
        user_id=user_id,
        run_id=run_id,
        conclusion=conclusion,
        status=status,
        known_facts=known_facts,
        gaps=gaps,
        conflicts=conflicts,
        metadata=metadata,
    )
    return _dump_result(result)


@tool(args_schema=BuildResearchReportInput)
async def build_research_report(
    user_id: UUID,
    run_id: UUID,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> str:
    """Build a read-only source-backed report from current research state."""
    admission = get_tool_admission_gate().admit_current_turn(
        BUILD_RESEARCH_REPORT_TOOL_POLICY
    )
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=False)

    result = await build_research_report_result(
        user_id=user_id,
        run_id=run_id,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=FinalizeResearchAnswerInput)
async def finalize_research_answer(
    user_id: UUID,
    run_id: UUID,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> str:
    """Build a final user-facing answer from verified research claims."""
    admission = get_tool_admission_gate().admit_current_turn(
        FINALIZE_RESEARCH_ANSWER_TOOL_POLICY
    )
    if not admission.allowed:
        return _final_answer_blocked_payload(admission)

    result = await finalize_research_answer_result(
        user_id=user_id,
        run_id=run_id,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=BuildRecommendationResearchReportInput)
async def build_recommendation_research_report(
    query: str = "",
    candidates: list[dict[str, Any]] | None = None,
    research_report: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Fuse recommendation candidates with verified research report claims."""
    admission = get_tool_admission_gate().admit_current_turn(
        BUILD_RECOMMENDATION_RESEARCH_REPORT_TOOL_POLICY
    )
    if not admission.allowed:
        return _recommendation_research_report_blocked_payload(admission)

    result = build_recommendation_research_report_result(
        query=query,
        candidates=candidates or [],
        research_report=research_report or {},
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=PlanRecommendationResearchWorkflowInput)
async def plan_recommendation_research_workflow(
    user_id: UUID,
    query: str = "",
    candidates: list[dict[str, Any]] | None = None,
    research_report: dict[str, Any] | None = None,
    research_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Plan the next read-only step for a researched recommendation workflow."""
    admission = get_tool_admission_gate().admit_current_turn(
        PLAN_RECOMMENDATION_RESEARCH_WORKFLOW_TOOL_POLICY
    )
    if not admission.allowed:
        return _recommendation_research_workflow_blocked_payload(admission)

    tool_metadata = dict(metadata or {})
    constraints = await _personalization_constraints_for_tool(
        user_id=user_id,
        query=query,
        metadata=tool_metadata,
    )

    result = plan_recommendation_research_workflow_result(
        user_id=user_id,
        query=query,
        candidates=candidates or [],
        research_report=research_report or {},
        research_state=research_state or {},
        personalization_constraints=constraints,
        metadata=tool_metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=RunRecommendationResearchWorkflowInput)
async def run_recommendation_research_workflow(
    user_id: UUID,
    query: str = "",
    candidates: list[dict[str, Any]] | None = None,
    research_report: dict[str, Any] | None = None,
    observations: list[ResearchObservation] | None = None,
    thread_id: UUID | None = None,
    mode: str = "deep_research",
    subquestions: list[str] | None = None,
    gaps: list[str] | None = None,
    next_actions: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    stop_criteria: list[str] | None = None,
    allow_runtime: bool = True,
    metadata: dict[str, Any] | None = None,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> str:
    """Run bounded local researched recommendation workflow over supplied inputs."""
    admission = get_tool_admission_gate().admit_current_turn(
        RUN_RECOMMENDATION_RESEARCH_WORKFLOW_TOOL_POLICY
    )
    if not admission.allowed:
        return _recommendation_research_runner_blocked_payload(admission)

    tool_metadata = dict(metadata or {})
    constraints = await _personalization_constraints_for_tool(
        user_id=user_id,
        query=query,
        metadata=tool_metadata,
    )
    result = await run_recommendation_research_workflow_result(
        user_id=user_id,
        query=query,
        candidates=candidates or [],
        research_report=research_report or {},
        observations=observations or [],
        thread_id=thread_id,
        mode=mode,
        subquestions=subquestions or [],
        gaps=gaps or [],
        next_actions=next_actions or [],
        budget=budget or {},
        stop_criteria=stop_criteria or [],
        personalization_constraints=constraints,
        allow_runtime=allow_runtime,
        metadata=tool_metadata,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=BuildResearchObservationsInput)
async def build_research_observations(
    query: str = "",
    subquestion: str = "",
    sources: list[dict[str, Any]] | None = None,
    provider_source: str = "source_acquisition",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Normalize approved source records into ResearchObservation objects."""
    admission = get_tool_admission_gate().admit_current_turn(
        BUILD_RESEARCH_OBSERVATIONS_TOOL_POLICY
    )
    if not admission.allowed:
        return _observation_batch_blocked_payload(admission)

    result = build_research_observation_batch(
        query=query,
        subquestion=subquestion,
        sources=sources or [],
        provider_source=provider_source,
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=AnalyzeResearchDataInput)
async def analyze_research_data(
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
) -> str:
    """Run bounded local Python analysis over supplied research records."""
    admission = get_tool_admission_gate().admit_current_turn(
        ANALYZE_RESEARCH_DATA_TOOL_POLICY
    )
    if not admission.allowed:
        return _python_analysis_blocked_payload(admission)

    result = analyze_research_data_result(
        query=query,
        subquestion=subquestion,
        records=records or [],
        dataset_title=dataset_title,
        source_url=source_url,
        source_type=source_type,
        focus_fields=focus_fields or [],
        max_findings=max_findings,
        include_observation_batch=include_observation_batch,
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=ExtractResearchSourceRecordsInput)
async def extract_research_source_records(
    query: str = "",
    subquestion: str = "",
    documents: list[dict[str, Any]] | None = None,
    provider_source: str = "source_extraction",
    max_records_per_document: int = 1,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Extract source-sentence research records from approved documents."""
    admission = get_tool_admission_gate().admit_current_turn(
        EXTRACT_RESEARCH_SOURCE_RECORDS_TOOL_POLICY
    )
    if not admission.allowed:
        return _source_extraction_blocked_payload(admission)

    result = extract_research_source_records_result(
        query=query,
        subquestion=subquestion,
        documents=documents or [],
        provider_source=provider_source,
        max_records_per_document=max_records_per_document,
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=SearchResearchSourcesInput)
async def search_research_sources(
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
    provider_source: str = "external_search",
    include_extraction: bool = True,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Search approved source documents for Deep Research without writing state."""
    admission = get_tool_admission_gate().admit_current_turn(
        SEARCH_RESEARCH_SOURCES_TOOL_POLICY
    )
    if not admission.allowed:
        return _source_search_blocked_payload(admission)

    result = await search_research_source_documents_result(
        query=query,
        subquestion=subquestion,
        limit=limit,
        provider_query=provider_query,
        provider_source=provider_source,
        include_extraction=include_extraction,
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=SearchResearchScholarSourcesInput)
async def search_research_scholar_sources(
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
    provider_source: str = "crossref",
    include_extraction: bool = True,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Search approved scholarly/paper source documents for Deep Research."""
    admission = get_tool_admission_gate().admit_current_turn(
        SEARCH_RESEARCH_SCHOLAR_SOURCES_TOOL_POLICY
    )
    if not admission.allowed:
        return _scholar_search_blocked_payload(admission)

    result = await search_research_scholar_documents_result(
        query=query,
        subquestion=subquestion,
        limit=limit,
        provider_query=provider_query,
        provider_source=provider_source,
        include_extraction=include_extraction,
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=FetchResearchSourceInput)
async def fetch_research_source(
    url: str,
    query: str = "",
    subquestion: str = "",
    provider_source: str = "source_visit",
    include_extraction: bool = True,
    timeout_seconds: int = 12,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Fetch one approved source URL for Deep Research without writing state."""
    admission = get_tool_admission_gate().admit_current_turn(
        FETCH_RESEARCH_SOURCE_TOOL_POLICY
    )
    if not admission.allowed:
        return _source_visit_blocked_payload(admission)

    result = await fetch_research_source_document_result(
        url=url,
        query=query,
        subquestion=subquestion,
        provider_source=provider_source,
        include_extraction=include_extraction,
        timeout_seconds=timeout_seconds,
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=CollectResearchSourcesInput)
async def collect_research_sources(
    user_id: UUID,
    run_id: UUID,
    query: str,
    sources: list[dict[str, Any]] | None = None,
    subquestion: str = "",
    provider_source: str = "source_collection",
    status: str = "completed",
    rationale: str = "",
    next_actions: list[str] | None = None,
    duration_ms: int = 0,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Normalize source records and log research search/visit state."""
    admission = get_tool_admission_gate().admit_current_turn(
        COLLECT_RESEARCH_SOURCES_TOOL_POLICY
    )
    if not admission.allowed:
        return _source_collection_blocked_payload(admission)

    result = await collect_research_sources_result(
        user_id=user_id,
        run_id=run_id,
        query=query,
        sources=sources or [],
        subquestion=subquestion,
        provider_source=provider_source,
        status=status,
        rationale=rationale,
        next_actions=next_actions,
        duration_ms=duration_ms,
        error=error,
        metadata=metadata,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)


@tool(args_schema=RunResearchHarnessInput)
async def run_research_harness(
    user_id: UUID,
    objective: str,
    thread_id: UUID | None = None,
    mode: str = "deep_research",
    subquestions: list[str] | None = None,
    gaps: list[str] | None = None,
    next_actions: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    stop_criteria: list[str] | None = None,
    observations: list[ResearchObservation] | None = None,
    metadata: dict[str, Any] | None = None,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> str:
    """Run one local Deep Research harness cycle and return its report."""
    admission = get_tool_admission_gate().admit_current_turn(
        RUN_RESEARCH_HARNESS_TOOL_POLICY
    )
    if not admission.allowed:
        return _tool_blocked_payload(admission, writes_research_state=True)
    if not observations:
        return _runtime_needs_observations_payload(admission)

    result = await run_research_runtime_result(
        user_id=user_id,
        objective=objective,
        thread_id=thread_id,
        mode=mode,
        subquestions=subquestions,
        gaps=gaps,
        next_actions=next_actions,
        budget=budget,
        stop_criteria=stop_criteria,
        observations=observations,
        metadata=metadata,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
