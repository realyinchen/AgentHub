from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.agent_core.contracts import (
    AgentCoreModel,
    ControllerMode,
    ControllerOutput,
)
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
)


CONTROLLER_GOLDEN_DATASET_VERSION = "controller-golden-v1"
CONTROLLER_GOLDEN_REPORT_VERSION = "controller-golden-report-v1"
ControllerGoldenCategory = Literal[
    "simple_direct",
    "conversation_recall",
    "memory_read",
    "memory_write",
    "memory_forget",
    "clarification",
    "task_planning",
    "task_cancel",
    "safety",
]


class ControllerGoldenExpectation(AgentCoreModel):
    allowed_modes: list[ControllerMode] = Field(min_length=1, max_length=4)
    required_capabilities: list[str] = Field(
        default_factory=list,
        max_length=8,
    )
    forbidden_capabilities: list[str] = Field(
        default_factory=list,
        max_length=8,
    )
    required_text_fragments: list[str] = Field(
        default_factory=list,
        max_length=8,
    )
    forbidden_text_fragments: list[str] = Field(
        default_factory=list,
        max_length=8,
    )
    required_call_arguments: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        max_length=8,
    )
    min_plan_steps: int = Field(default=0, ge=0, le=64)
    required_plan_capabilities: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    require_plan_dependency_edge: bool = False
    max_proposal_count: int = Field(default=8, ge=0, le=32)

    @model_validator(mode="after")
    def validate_capability_sets(self) -> "ControllerGoldenExpectation":
        overlap = set(self.required_capabilities).intersection(
            self.forbidden_capabilities
        )
        if overlap:
            raise ValueError(
                "required and forbidden Controller capabilities overlap"
            )
        required_text = {
            _normalized_fragment(item)
            for item in self.required_text_fragments
        }
        forbidden_text = {
            _normalized_fragment(item)
            for item in self.forbidden_text_fragments
        }
        if "" in required_text or "" in forbidden_text:
            raise ValueError(
                "Controller text fragments cannot be empty"
            )
        if required_text.intersection(forbidden_text):
            raise ValueError(
                "required and forbidden Controller text fragments overlap"
            )
        if (
            self.required_text_fragments
            and self.allowed_modes != ["direct_answer"]
        ):
            raise ValueError(
                "required text fragments require direct_answer"
            )
        if self.required_call_arguments:
            if self.allowed_modes != ["capability_proposals"]:
                raise ValueError(
                    "call argument constraints require capability proposals"
                )
            if not set(self.required_call_arguments).issubset(
                self.required_capabilities
            ):
                raise ValueError(
                    "call argument constraints require their capabilities"
                )
        has_plan_constraints = bool(
            self.min_plan_steps
            or self.required_plan_capabilities
            or self.require_plan_dependency_edge
        )
        if (
            has_plan_constraints
            and self.allowed_modes != ["task_plan_proposal"]
        ):
            raise ValueError(
                "plan constraints require task_plan_proposal"
            )
        return self


class ControllerGoldenCase(AgentCoreModel):
    case_id: str = Field(pattern="^[a-z0-9_.-]{1,128}$")
    category: ControllerGoldenCategory
    critical: bool = True
    safety: bool = False
    simple_direct: bool = False
    explicit_tool: bool = False
    current_user_message: str = Field(min_length=1, max_length=4_000)
    context: ControllerContextSnapshot = Field(
        default_factory=ControllerContextSnapshot
    )
    expected: ControllerGoldenExpectation
    reference_output: ControllerOutput

    @model_validator(mode="after")
    def validate_denominator_flags(self) -> "ControllerGoldenCase":
        if self.simple_direct:
            if self.expected.allowed_modes != ["direct_answer"]:
                raise ValueError(
                    "simple-direct cases must require direct_answer"
                )
            if (
                self.expected.max_proposal_count != 0
                or self.expected.required_capabilities
            ):
                raise ValueError(
                    "simple-direct cases must require zero proposals"
                )
        if self.explicit_tool and not self.expected.required_capabilities:
            raise ValueError(
                "explicit-tool cases require a capability expectation"
            )
        return self


class ControllerGoldenDataset(AgentCoreModel):
    dataset_version: Literal["controller-golden-v1"] = (
        CONTROLLER_GOLDEN_DATASET_VERSION
    )
    cases: list[ControllerGoldenCase] = Field(
        min_length=1,
        max_length=10_000,
    )

    @model_validator(mode="after")
    def validate_coverage(self) -> "ControllerGoldenDataset":
        ids = [item.case_id for item in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate Controller golden case IDs")
        required_categories = {
            "simple_direct",
            "conversation_recall",
            "memory_read",
            "memory_write",
            "memory_forget",
            "clarification",
            "task_planning",
            "task_cancel",
            "safety",
        }
        missing = required_categories.difference(
            item.category for item in self.cases
        )
        if missing:
            raise ValueError(
                "Controller golden dataset misses categories: "
                + ", ".join(sorted(missing))
            )
        for name, predicate in (
            ("critical", lambda item: item.critical),
            ("safety", lambda item: item.safety),
            ("simple_direct", lambda item: item.simple_direct),
            ("explicit_tool", lambda item: item.explicit_tool),
        ):
            if not any(predicate(item) for item in self.cases):
                raise ValueError(
                    f"Controller golden {name} denominator is empty"
                )
        return self


class LoadedControllerGoldenDataset(AgentCoreModel):
    dataset: ControllerGoldenDataset
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class ControllerGoldenCaseResult(AgentCoreModel):
    case_id: str
    category: ControllerGoldenCategory
    passed: bool
    observed_mode: ControllerMode | None = None
    proposal_count: int = Field(default=0, ge=0)
    required_capabilities_satisfied: bool = False
    required_text_fragments_satisfied: bool = True
    required_call_arguments_satisfied: bool = True
    plan_structure_satisfied: bool = True
    simple_tool_triggered: bool = False
    controller_call_count: int = Field(default=1, ge=0)
    runtime_call_count: int = Field(default=0, ge=0)
    reason_codes: list[str] = Field(default_factory=list)


def _normalized_fragment(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


class ControllerGoldenReport(AgentCoreModel):
    report_version: Literal["controller-golden-report-v1"] = (
        CONTROLLER_GOLDEN_REPORT_VERSION
    )
    status: Literal["passed", "failed", "blocked"]
    live_model_evidence: bool
    commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    source_dirty_worktree: bool
    generated_at: datetime
    model_id: UUID | None = None
    certification_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    dataset_version: str = Field(min_length=1, max_length=64)
    dataset_hash: str = Field(pattern="^[0-9a-f]{64}$")
    sample_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    critical_count: int = Field(ge=0)
    critical_passed: int = Field(ge=0)
    safety_count: int = Field(ge=0)
    safety_passed: int = Field(ge=0)
    explicit_tool_count: int = Field(ge=0)
    explicit_tool_passed: int = Field(ge=0)
    simple_direct_count: int = Field(ge=0)
    simple_tool_trigger_count: int = Field(ge=0)
    total_controller_calls: int = Field(ge=0)
    total_runtime_calls: int = Field(ge=0)
    reasons: list[str] = Field(default_factory=list)
    failed_case_ids: list[str] = Field(default_factory=list)
    cases: list[ControllerGoldenCaseResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_provenance(self) -> "ControllerGoldenReport":
        if (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset() is None
        ):
            raise ValueError(
                "Controller golden generated_at must be timezone-aware"
            )
        if self.live_model_evidence:
            if self.source_dirty_worktree:
                raise ValueError(
                    "live Controller evidence requires clean source"
                )
            if self.model_id is None or self.certification_id is None:
                raise ValueError(
                    "live Controller evidence requires model certification"
                )
        return self


__all__ = [
    "CONTROLLER_GOLDEN_DATASET_VERSION",
    "CONTROLLER_GOLDEN_REPORT_VERSION",
    "ControllerGoldenCase",
    "ControllerGoldenCaseResult",
    "ControllerGoldenDataset",
    "ControllerGoldenExpectation",
    "ControllerGoldenReport",
    "LoadedControllerGoldenDataset",
]
