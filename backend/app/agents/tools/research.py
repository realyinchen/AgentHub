"""Research state tools for Deep Search / Deep Research."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.services.research import ResearchEvidence, get_research_orchestrator
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
    excerpt: str = Field(default="", description="Brief supporting excerpt or paraphrase.")
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


def _admit_research_state_tool(tool_name: str) -> ToolAdmissionResult:
    return get_tool_admission_gate().admit_current_turn(
        RESEARCH_STATE_TOOL_POLICY.model_copy(update={"tool_name": tool_name})
    )


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
    """Add evidence to research state. This does not write long-term memory."""
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
