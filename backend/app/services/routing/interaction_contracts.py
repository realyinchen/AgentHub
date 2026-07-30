from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.conversation.contracts import ConversationTurn
from app.services.system_owned_fields import (
    MODEL_PROPOSAL_FORBIDDEN_FIELDS,
    find_forbidden_paths,
)


INTERACTION_DECISION_CONTRACT_VERSION = "interaction-decision-v1"

DecisionStatus = Literal[
    "accepted",
    "clarification_required",
    "safe_default",
]
EvidenceSource = Literal["rule", "keyword", "vector", "router_model", "context"]
ProviderStatus = Literal["matched", "no_match", "degraded", "failed", "unavailable"]
EvidencePolarity = Literal["supports", "opposes", "neutral"]
ClausePolarity = Literal["affirmative", "negative", "mixed"]
ClauseRelation = Literal["root", "then", "and", "contrast", "condition"]
RequirementLevel = Literal["forbidden", "not_required", "optional", "required", "unknown"]
PersistenceDisposition = Literal[
    "forbidden",
    "not_warranted",
    "candidate",
    "explicitly_requested",
    "uncertain",
]
StateChangeDisposition = Literal[
    "forbidden",
    "none",
    "proposed",
    "explicitly_requested",
    "uncertain",
]
PlanningMode = Literal[
    "direct_answer",
    "static_workflow",
    "decomposition_required",
    "clarification_required",
]
AbstractCapability = Literal[
    "conversation_context",
    "long_term_memory_read",
    "external_information",
    "current_information",
    "memory_persistence",
    "business_state_change",
    "book_catalog_search",
    "decomposition",
]
ConstraintOperator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "in",
    "not_in",
    "gte",
    "lte",
    "exists",
]


class InteractionModel(BaseModel):
    """Closed decision contract: unknown and system-owned inputs are rejected."""

    model_config = ConfigDict(extra="forbid")


class GoalClause(InteractionModel):
    clause_id: str
    text: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    relation: ClauseRelation = "root"
    polarity: ClausePolarity = "affirmative"
    quoted_spans: list[str] = Field(default_factory=list)

    @field_validator("clause_id", mode="before")
    @classmethod
    def normalize_clause_id(cls, value: Any) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("clause_id cannot be empty")
        return token

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            raise ValueError("clause text cannot be empty")
        return text


class RoutingEvidence(InteractionModel):
    """Non-executable observation emitted by a recall provider."""

    clause_id: str | None = None
    intent: str
    source: EvidenceSource
    raw_score: float = Field(ge=0.0, le=1.0)
    calibrated_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    polarity: EvidencePolarity = "supports"
    matched_span: str = ""
    reasons: list[str] = Field(default_factory=list)
    domain: str = "general"

    @field_validator("intent", "domain", mode="before")
    @classmethod
    def normalize_token(cls, value: Any) -> str:
        token = str(value or "").strip().lower().replace(" ", "_")
        if not token:
            raise ValueError("evidence token cannot be empty")
        return token

    @property
    def confidence(self) -> float:
        if self.calibrated_confidence is not None:
            return self.calibrated_confidence
        return self.raw_score


class RecallBatch(InteractionModel):
    """One provider result; degraded/failed is distinct from a true no-match."""

    provider: str
    source: EvidenceSource
    provider_status: ProviderStatus
    evidence: list[RoutingEvidence] = Field(default_factory=list)
    model_key: str | None = None
    latency_ms: float = Field(default=0.0, ge=0.0)
    degraded_reason: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: Any) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("provider cannot be empty")
        return token

    @model_validator(mode="after")
    def validate_status(self) -> "RecallBatch":
        if self.provider_status == "matched" and not self.evidence:
            raise ValueError("matched recall batch must contain evidence")
        if self.provider_status == "no_match" and self.evidence:
            raise ValueError("no_match recall batch cannot contain evidence")
        if self.provider_status in {"degraded", "failed", "unavailable"}:
            if not str(self.degraded_reason or "").strip():
                raise ValueError(
                    f"{self.provider_status} recall batch requires degraded_reason"
                )
        return self


class DecisionConstraint(InteractionModel):
    """Business filtering or policy condition; never an execution argument."""

    field: str
    operator: ConstraintOperator = "equals"
    value: Any = None
    source: EvidenceSource = "rule"
    reason: str = ""

    @field_validator("field", mode="before")
    @classmethod
    def validate_field(cls, value: Any) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("constraint field cannot be empty")
        if token.casefold() in MODEL_PROPOSAL_FORBIDDEN_FIELDS:
            raise ValueError(f"system-owned field is forbidden: {token}")
        return token

    @field_validator("value")
    @classmethod
    def reject_system_values(cls, value: Any) -> Any:
        invalid = find_forbidden_paths(
            value,
            forbidden_fields=MODEL_PROPOSAL_FORBIDDEN_FIELDS,
            root="value",
        )
        if invalid:
            raise ValueError(
                "system-owned fields are forbidden in constraints: "
                + ", ".join(sorted(invalid))
            )
        return value


class PendingMemoryWriteContext(InteractionModel):
    """Ephemeral continuation state projected from the last runtime receipt."""

    kind: Literal["reference", "completeness", "conflict"]
    original_utterance: str = Field(min_length=1, max_length=4000)
    target_expression: str = ""
    question: str = Field(min_length=1, max_length=1000)

    @field_validator(
        "original_utterance",
        "target_expression",
        "question",
        mode="before",
    )
    @classmethod
    def normalize_pending_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class BusinessRoutingContext(InteractionModel):
    """Small, identity-free business context used only to resolve follow-ups."""

    recent_user_messages: list[str] = Field(default_factory=list, max_length=8)
    conversation_turns: list[ConversationTurn] = Field(
        default_factory=list,
        max_length=16,
    )
    previous_primary_intent: str | None = None
    active_subject: str | None = None
    previous_constraints: list[DecisionConstraint] = Field(default_factory=list)
    pending_memory_write: PendingMemoryWriteContext | None = None

    @field_validator("recent_user_messages", mode="before")
    @classmethod
    def normalize_messages(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return [
            " ".join(str(message or "").split()).strip()
            for message in value
            if str(message or "").strip()
        ]

    @field_validator("previous_primary_intent", mode="before")
    @classmethod
    def normalize_previous_intent(cls, value: Any) -> str | None:
        if value is None:
            return None
        token = str(value).strip().lower().replace(" ", "_")
        return token or None

    @field_validator("active_subject", mode="before")
    @classmethod
    def normalize_subject(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split()).strip()
        return text or None


class InteractionDecisionInput(InteractionModel):
    """Complete, non-executable input consumed by InteractionDecisionMaker."""

    text: str = Field(min_length=1)
    clauses: list[GoalClause] = Field(default_factory=list)
    evidence: list[RoutingEvidence] = Field(default_factory=list)
    recall_batches: list[RecallBatch] = Field(default_factory=list)
    constraints: list[DecisionConstraint] = Field(default_factory=list)
    context: BusinessRoutingContext = Field(default_factory=BusinessRoutingContext)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            raise ValueError("decision input text cannot be empty")
        return text

    @classmethod
    def from_legacy_candidates(
        cls,
        text: str,
        candidates: Iterable[Any],
        *,
        constraints: Iterable[Any] = (),
        context: BusinessRoutingContext | None = None,
    ) -> "InteractionDecisionInput":
        """Adapt legacy candidates while deliberately discarding operations."""

        from app.services.routing.segmenter import segment_utterance

        evidence = [_legacy_evidence(candidate) for candidate in candidates]
        adapted_constraints = [
            _legacy_constraint(constraint) for constraint in constraints
        ]
        return cls(
            text=text,
            clauses=segment_utterance(text),
            evidence=evidence,
            constraints=adapted_constraints,
            context=context or BusinessRoutingContext(),
        )

    def all_evidence(self) -> list[RoutingEvidence]:
        return [
            *self.evidence,
            *(item for batch in self.recall_batches for item in batch.evidence),
        ]

    def incomplete_evidence_reasons(self) -> list[str]:
        return [
            f"{batch.provider}:{batch.provider_status}:{batch.degraded_reason}"
            for batch in self.recall_batches
            if batch.provider_status in {"degraded", "failed", "unavailable"}
        ]


class GoalDecision(InteractionModel):
    kind: str
    domain: str = "general"
    topic: str | None = None
    legacy_intents: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ExistingInformationDecision(InteractionModel):
    conversation_context: RequirementLevel = "not_required"
    long_term_memory: RequirementLevel = "not_required"
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ExternalInformationDecision(InteractionModel):
    current_information: RequirementLevel = "not_required"
    external_information: RequirementLevel = "not_required"
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryPersistenceDecision(InteractionModel):
    disposition: PersistenceDisposition = "not_warranted"
    subject: str | None = None
    operation: Literal["create", "correct"] | None = None
    target_expression: str | None = None
    explicit: bool = False
    conversation_context_required: bool = False
    pending_clarification: PendingMemoryWriteContext | None = None
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class BusinessStateDecision(InteractionModel):
    disposition: StateChangeDisposition = "none"
    target: str | None = None
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class PlanningDecision(InteractionModel):
    mode: PlanningMode = "direct_answer"
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class AxisConfidence(InteractionModel):
    goal: float = Field(ge=0.0, le=1.0)
    existing_information: float = Field(ge=0.0, le=1.0)
    external_information: float = Field(ge=0.0, le=1.0)
    memory_persistence: float = Field(ge=0.0, le=1.0)
    business_state: float = Field(ge=0.0, le=1.0)
    planning: float = Field(ge=0.0, le=1.0)


class ClauseDecision(InteractionModel):
    clause_id: str
    text: str
    goal: GoalDecision
    existing_information: ExistingInformationDecision
    external_information: ExternalInformationDecision
    memory_persistence: MemoryPersistenceDecision
    business_state: BusinessStateDecision
    planning: PlanningDecision
    prohibited_capabilities: list[AbstractCapability] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class InteractionDecision(InteractionModel):
    """Pure decision output. It cannot authorize or describe execution."""

    result_mode: Literal["interaction_decision"] = "interaction_decision"
    contract_version: Literal["interaction-decision-v1"] = (
        INTERACTION_DECISION_CONTRACT_VERSION
    )
    status: DecisionStatus
    clauses: list[ClauseDecision] = Field(min_length=1)
    planning: PlanningDecision
    constraints: list[DecisionConstraint] = Field(default_factory=list)
    prohibited_capabilities: list[AbstractCapability] = Field(default_factory=list)
    direct_answer_allowed: bool
    confidence_by_axis: AxisConfidence
    unresolved_questions: list[str] = Field(default_factory=list)
    evidence_limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def clarification_has_question(self) -> "InteractionDecision":
        if self.status == "clarification_required" and not self.unresolved_questions:
            raise ValueError(
                "clarification_required decisions need an unresolved question"
            )
        return self


def evidence_for_clause(
    evidence: Sequence[RoutingEvidence],
    clause: GoalClause,
) -> list[RoutingEvidence]:
    """Return clause-local evidence plus global evidence relevant to its text."""

    local: list[RoutingEvidence] = []
    normalized = clause.text.casefold()
    for item in evidence:
        if item.clause_id == clause.clause_id:
            local.append(item)
            continue
        if item.clause_id is not None:
            continue
        if not item.matched_span or item.matched_span.casefold() in normalized:
            local.append(item)
    return local


def _legacy_evidence(candidate: Any) -> RoutingEvidence:
    data = candidate if isinstance(candidate, dict) else vars(candidate)
    reasons = data.get("evidence") or data.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    source = str(data.get("source") or "rule")
    if source not in {"rule", "keyword", "vector", "router_model", "context"}:
        source = "rule"
    return RoutingEvidence(
        intent=data.get("intent") or "answer_question",
        source=source,
        raw_score=float(data.get("confidence", data.get("raw_score", 0.0))),
        reasons=[str(reason) for reason in reasons],
        domain=data.get("domain") or "general",
    )


def _legacy_constraint(constraint: Any) -> DecisionConstraint:
    data = constraint if isinstance(constraint, dict) else vars(constraint)
    source = str(data.get("source") or "rule")
    if source not in {"rule", "keyword", "vector", "router_model", "context"}:
        source = "rule"
    return DecisionConstraint(
        field=data.get("field"),
        operator=data.get("operator", "equals"),
        value=data.get("value"),
        source=source,
        reason=data.get("reason", ""),
    )
