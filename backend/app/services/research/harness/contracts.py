from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.research.contracts import (
    EVIDENCE_QUALITIES,
    RESEARCH_MODES,
    RESEARCH_STEP_STATUSES,
    ResearchStateResult,
    clean_string_list,
    normalize_text,
    validate_research_token,
)
from app.services.research.observation_providers.contracts import ResearchObservation


HARNESS_NODE_NAMES = frozenset(
    {
        "planner",
        "search_task_builder",
        "source_visitor",
        "aggregator",
        "gap_filler",
        "verifier",
        "finalizer",
    }
)
HARNESS_TERMINAL_NODE = "end"
HARNESS_CONFIRMABLE_NODES = HARNESS_NODE_NAMES | frozenset({HARNESS_TERMINAL_NODE})

NEXT_STEP_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "search_task_builder": (
        "run_id",
        "plan.objective",
        "plan.subquestions",
        "plan.next_actions",
    ),
    "source_visitor": (
        "run_id",
        "search_task.query",
        "search_task.subquestion",
        "search_task.rationale",
    ),
    "aggregator": (
        "run_id",
        "observation_batch.observations",
    ),
    "gap_filler": (
        "run_id",
        "aggregation.candidate_claims",
        "aggregation.evidence_ids",
        "aggregation.gaps",
    ),
    "verifier": (
        "run_id",
        "aggregation.candidate_claims",
        "aggregation.evidence_ids",
        "gap_filling.blocking_gaps",
    ),
    "finalizer": (
        "run_id",
        "verification.ready_for_final_answer",
    ),
    HARNESS_TERMINAL_NODE: (
        "finalization.final_answer",
    ),
}

NON_EMPTY_REQUIRED_FIELDS = frozenset(
    {
        "plan.objective",
        "plan.subquestions",
        "plan.next_actions",
        "search_task.query",
        "search_task.subquestion",
        "search_task.rationale",
        "observation_batch.observations",
        "aggregation.candidate_claims",
        "aggregation.evidence_ids",
        "finalization.final_answer",
    }
)

_MISSING = object()


class HarnessFieldError(ValueError):
    """Raised when a graph node starts without confirmed required fields."""


def normalize_harness_node(value: Any, *, allow_terminal: bool = False) -> str:
    node = str(value or "").strip().lower().replace(" ", "_")
    allowed = HARNESS_CONFIRMABLE_NODES if allow_terminal else HARNESS_NODE_NAMES
    if node not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"harness node must be one of: {allowed_values}")
    return node


def _get_field_value(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, BaseModel):
            if not hasattr(current, part):
                return _MISSING
            current = getattr(current, part)
        elif isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        else:
            return _MISSING
    return current


def _field_is_satisfied(data: Any, path: str) -> bool:
    value = _get_field_value(data, path)
    if value is _MISSING or value is None:
        return False
    if path == "verification.ready_for_final_answer":
        return value is True
    if path not in NON_EMPTY_REQUIRED_FIELDS:
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def confirm_next_step_fields(
    state: dict[str, Any],
    *,
    current_step: str,
    next_step: str,
    required_fields: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
) -> StepFieldConfirmation:
    """Build the field confirmation emitted by one node for the next node."""

    normalized_current = normalize_harness_node(current_step)
    normalized_next = normalize_harness_node(next_step, allow_terminal=True)
    required = list(required_fields or NEXT_STEP_REQUIRED_FIELDS.get(normalized_next, ()))
    satisfied = [field for field in required if _field_is_satisfied(state, field)]
    missing = [field for field in required if field not in satisfied]
    return StepFieldConfirmation(
        current_step=normalized_current,
        next_step=normalized_next,
        required_fields=required,
        satisfied_fields=satisfied,
        missing_fields=missing,
        ready=not missing,
        metadata=metadata or {},
    )


def require_next_step_ready(
    state: dict[str, Any],
    *,
    next_step: str,
) -> StepFieldConfirmation:
    """Validate the previous node confirmed every field needed by next_step."""

    normalized_next = normalize_harness_node(next_step)
    raw_confirmation = state.get("field_confirmation")
    if raw_confirmation is None:
        confirmations = state.get("field_confirmations") or []
        raw_confirmation = confirmations[-1] if confirmations else None
    if raw_confirmation is None:
        raise HarnessFieldError(
            f"{normalized_next} cannot start before required fields are confirmed"
        )

    confirmation = StepFieldConfirmation.model_validate(raw_confirmation)
    if confirmation.next_step != normalized_next:
        raise HarnessFieldError(
            f"{normalized_next} cannot start from confirmation for "
            f"{confirmation.next_step}"
        )

    checked = confirm_next_step_fields(
        state,
        current_step=confirmation.current_step,
        next_step=confirmation.next_step,
        required_fields=confirmation.required_fields,
        metadata=confirmation.metadata,
    )
    if not checked.ready:
        missing = ", ".join(checked.missing_fields)
        raise HarnessFieldError(
            f"{normalized_next} cannot start; missing required fields: {missing}"
        )
    return checked


class StepFieldConfirmation(BaseModel):
    """A node's explicit contract that the next node has all required fields."""

    current_step: str
    next_step: str
    required_fields: list[str] = Field(default_factory=list)
    satisfied_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    ready: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("current_step", mode="before")
    @classmethod
    def validate_current_step(cls, value: Any) -> str:
        return normalize_harness_node(value)

    @field_validator("next_step", mode="before")
    @classmethod
    def validate_next_step(cls, value: Any) -> str:
        return normalize_harness_node(value, allow_terminal=True)


class ResearchHarnessInput(BaseModel):
    """Input contract for one executable Deep Search harness run."""

    user_id: UUID
    objective: str
    thread_id: UUID | None = None
    mode: str = "deep_search"
    subquestions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    observations: list[ResearchObservation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective", mode="before")
    @classmethod
    def clean_objective(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("objective cannot be empty")
        return text

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, value: Any) -> str:
        return validate_research_token("mode", value, RESEARCH_MODES)

    @field_validator("subquestions", "gaps", "next_actions", "stop_criteria", mode="before")
    @classmethod
    def clean_text_lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class ResearchPlan(BaseModel):
    run_id: UUID
    objective: str
    subquestions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchTask(BaseModel):
    run_id: UUID
    query: str
    subquestion: str
    rationale: str
    expected_source_types: list[str] = Field(default_factory=lambda: ["web"])
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query", "subquestion", "rationale", mode="before")
    @classmethod
    def clean_required_text(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("search task text fields cannot be empty")
        return text


class ObservationBatch(BaseModel):
    run_id: UUID
    query: str
    status: str = "completed"
    observations: list[ResearchObservation] = Field(default_factory=list)
    exhausted_queries: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        return validate_research_token("status", value, RESEARCH_STEP_STATUSES)


class CandidateClaim(BaseModel):
    claim: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    source_titles: list[str] = Field(default_factory=list)
    quality: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("quality", mode="before")
    @classmethod
    def validate_quality(cls, value: Any) -> str:
        return validate_research_token("quality", value, EVIDENCE_QUALITIES)

    @field_validator("claim", mode="before")
    @classmethod
    def clean_claim(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("claim cannot be empty")
        return text


class AggregationResult(BaseModel):
    run_id: UUID
    candidate_claims: list[CandidateClaim] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GapFillingResult(BaseModel):
    run_id: UUID
    blocking_gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    should_continue: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerifiedClaim(BaseModel):
    claim: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    confidence: str = "supported"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    run_id: UUID
    admitted_claims: list[VerifiedClaim] = Field(default_factory=list)
    rejected_claims: list[CandidateClaim] = Field(default_factory=list)
    uncertain_claims: list[CandidateClaim] = Field(default_factory=list)
    blocking_gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    ready_for_final_answer: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalizationResult(BaseModel):
    run_id: UUID
    final_answer: str
    verified_claims: list[VerifiedClaim] = Field(default_factory=list)
    remaining_uncertainty: list[str] = Field(default_factory=list)
    status: str = "completed"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchHarnessResumeState(BaseModel):
    """Minimal state reconstructed from Postgres after context loss."""

    run_id: UUID
    status: str
    objective: str
    subquestions: list[str] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    exhausted_queries: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    evidence_count: int = 0
    last_step_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchHarnessResult(BaseModel):
    """Executable harness result returned to callers and verification scripts."""

    user_id: UUID
    run_id: UUID
    status: str
    finalization: FinalizationResult
    field_confirmations: list[StepFieldConfirmation] = Field(default_factory=list)
    research_state: ResearchStateResult
    resume_state: ResearchHarnessResumeState | None = None
    resumed_from_postgres: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)
