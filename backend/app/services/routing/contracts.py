from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.routing.interaction_contracts import (
    BusinessRoutingContext,
    InteractionDecision,
)
from app.services.system_owned_fields import (
    ACTION_ARGUMENT_FORBIDDEN_FIELDS,
    find_forbidden_paths,
)


ROUTING_DECISION_CONTRACT_VERSION = "routing-decision-v1"

IntentSource = Literal["rule", "keyword", "vector", "router_model"]
RouteType = Literal["fast_path", "slow_path"]
Complexity = Literal["low", "medium", "high"]
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


class RoutingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutingQuery(RoutingModel):
    """Business input accepted by the routing funnel.

    Identity, request, credential, and permission fields deliberately do not
    exist in this contract.
    """

    text: str = Field(min_length=1)
    context: BusinessRoutingContext = Field(default_factory=BusinessRoutingContext)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class IntentCandidate(RoutingModel):
    """Non-executable recall evidence.

    A candidate may describe a likely user intent, but it intentionally has no
    operation/tool field. Only InteractionDecision plus capability compilers
    can produce ProposedAction values.
    """

    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: IntentSource
    evidence: list[str] = Field(default_factory=list)
    domain: str = "general"

    @field_validator("intent", "domain", mode="before")
    @classmethod
    def normalize_token(cls, value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "_")


class RoutingConstraint(RoutingModel):
    """A filtering or policy condition, never an execution argument."""

    field: str
    operator: ConstraintOperator = "equals"
    value: Any = None
    source: IntentSource = "rule"
    reason: str = ""

    @field_validator("field", mode="before")
    @classmethod
    def normalize_field(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("constraint field cannot be empty")
        return text


class ProposedAction(RoutingModel):
    """A business-only action proposal produced by routing."""

    action_key: str
    capability: str
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    required: bool = True
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("action_key", "capability", "operation", mode="before")
    @classmethod
    def normalize_action_token(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("action token cannot be empty")
        return text

    @field_validator("arguments")
    @classmethod
    def reject_system_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        invalid = sorted(
            find_forbidden_paths(
                value,
                forbidden_fields=ACTION_ARGUMENT_FORBIDDEN_FIELDS,
            )
        )
        if invalid:
            raise ValueError(
                "routing cannot propose system-owned fields: " + ", ".join(invalid)
            )
        return value


class RoutingRequirements(RoutingModel):
    """Explicit answers to capability-selection questions."""

    direct_answer_allowed: bool = True
    conversation_read_required: bool = False
    memory_read_required: bool = False
    memory_write_required: bool = False
    weather_required: bool = False
    external_search_required: bool = False
    decomposition_required: bool = False


class RoutingDecision(RoutingModel):
    """The sole output of rule, semantic, and future model routing."""

    result_mode: str = "routing_decision"
    contract_version: str = ROUTING_DECISION_CONTRACT_VERSION
    intent_candidates: list[IntentCandidate] = Field(default_factory=list)
    route_type: RouteType
    complexity: Complexity
    planner_required: bool
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    constraints: list[RoutingConstraint] = Field(default_factory=list)
    requirements: RoutingRequirements = Field(default_factory=RoutingRequirements)
    interaction_decision: InteractionDecision | None = None
    primary_intent: str = "answer_question"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_graph(self) -> "RoutingDecision":
        keys = [action.action_key for action in self.proposed_actions]
        if len(keys) != len(set(keys)):
            raise ValueError("action_key values must be unique")
        known = set(keys)
        for action in self.proposed_actions:
            missing = [key for key in action.depends_on if key not in known]
            if missing:
                raise ValueError(
                    f"action {action.action_key} has unknown dependencies: {missing}"
                )
        if (
            self.interaction_decision is not None
            and self.interaction_decision.status
            in {"clarification_required", "safe_default"}
            and self.proposed_actions
        ):
            raise ValueError(
                "non-accepted interaction decisions cannot authorize actions"
            )
        return self
