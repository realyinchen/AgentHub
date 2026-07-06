from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.book_intent import ACTION_FIELDS, TurnPolicy, build_turn_policy
from app.utils.logging import get_request_id
from app.utils.turn_context import get_current_user_message


TOOL_SIDE_EFFECT_SCOPES = frozenset(
    {
        "none",
        "memory_read",
        "long_term_memory",
        "research_state",
        "recommendation_state",
        "book_cache",
        "external_call",
        "multi_scope",
    }
)
_TOOL_BUDGET_TTL_SECONDS = 15 * 60


class ToolPolicyDeclaration(BaseModel):
    """App-owned declaration of a tool's policy and side effects."""

    tool_name: str
    required_policy_flags: list[str] = Field(default_factory=list)
    side_effect_scope: str = "none"
    writes_long_term_memory: bool = False
    writes_research_state: bool = False
    external_call: bool = False
    max_calls_per_turn: int = Field(default=0, ge=0, le=100)
    blocked_status: str = "tool_blocked"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name", "blocked_status", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value cannot be empty")
        return text

    @field_validator("required_policy_flags", mode="before")
    @classmethod
    def validate_required_policy_flags(cls, value: Any) -> list[str]:
        flags = [str(item or "").strip() for item in value or []]
        invalid = [item for item in flags if item not in ACTION_FIELDS]
        if invalid:
            raise ValueError(f"unknown policy flags: {', '.join(invalid)}")
        return flags

    @field_validator("side_effect_scope", mode="before")
    @classmethod
    def validate_side_effect_scope(cls, value: Any) -> str:
        scope = str(value or "").strip().lower()
        if scope not in TOOL_SIDE_EFFECT_SCOPES:
            allowed = ", ".join(sorted(TOOL_SIDE_EFFECT_SCOPES))
            raise ValueError(f"side_effect_scope must be one of: {allowed}")
        return scope


class ToolAdmissionResult(BaseModel):
    allowed: bool
    tool_name: str
    reason: str = ""
    blocked_status: str = ""
    remaining_budget: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolAdmissionGate:
    """Shared policy gate for agent tools."""

    _call_counts: dict[str, tuple[int, float]] = {}

    def admit_current_turn(
        self,
        declaration: ToolPolicyDeclaration,
        *,
        bypass_budget: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> ToolAdmissionResult:
        user_message = get_current_user_message()
        policy = build_turn_policy(user_message)
        return self.admit(
            declaration,
            policy=policy,
            turn_key=_current_turn_key(),
            bypass_budget=bypass_budget,
            user_message=user_message,
            metadata=metadata,
        )

    def admit(
        self,
        declaration: ToolPolicyDeclaration,
        *,
        policy: TurnPolicy,
        turn_key: str = "",
        bypass_budget: bool = False,
        user_message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ToolAdmissionResult:
        admission_metadata = {
            "declaration": declaration.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            **(metadata or {}),
        }

        if not user_message.strip():
            admission_metadata["compatibility_allow_without_turn_context"] = True
            return ToolAdmissionResult(
                allowed=True,
                tool_name=declaration.tool_name,
                reason="no_turn_context_compatibility_allow",
                remaining_budget=declaration.max_calls_per_turn,
                metadata=admission_metadata,
            )

        missing_flags = [
            flag for flag in declaration.required_policy_flags if not getattr(policy, flag)
        ]
        if missing_flags:
            return ToolAdmissionResult(
                allowed=False,
                tool_name=declaration.tool_name,
                reason="required_policy_flags_missing",
                blocked_status=declaration.blocked_status,
                remaining_budget=0,
                metadata={
                    **admission_metadata,
                    "missing_policy_flags": missing_flags,
                },
            )

        if declaration.max_calls_per_turn > 0 and not bypass_budget:
            remaining = self._claim_budget(declaration, turn_key or "process")
            if remaining < 0:
                return ToolAdmissionResult(
                    allowed=False,
                    tool_name=declaration.tool_name,
                    reason="tool_budget_exhausted",
                    blocked_status=str(
                        declaration.metadata.get("budget_blocked_status")
                        or declaration.blocked_status
                    ),
                    remaining_budget=0,
                    metadata=admission_metadata,
                )
            return ToolAdmissionResult(
                allowed=True,
                tool_name=declaration.tool_name,
                reason="allowed",
                remaining_budget=remaining,
                metadata=admission_metadata,
            )

        return ToolAdmissionResult(
            allowed=True,
            tool_name=declaration.tool_name,
            reason="allowed",
            remaining_budget=declaration.max_calls_per_turn,
            metadata=admission_metadata,
        )

    def reset(self) -> None:
        self._call_counts.clear()

    def _claim_budget(
        self,
        declaration: ToolPolicyDeclaration,
        turn_key: str,
    ) -> int:
        now = time.monotonic()
        self._cleanup(now)
        key = f"{turn_key}:{declaration.tool_name}"
        count, _ = self._call_counts.get(key, (0, now))
        remaining = declaration.max_calls_per_turn - count
        if remaining <= 0:
            return -1
        self._call_counts[key] = (count + 1, now)
        return declaration.max_calls_per_turn - count - 1

    def _cleanup(self, now: float) -> None:
        expired = [
            key
            for key, (_, seen_at) in self._call_counts.items()
            if now - seen_at > _TOOL_BUDGET_TTL_SECONDS
        ]
        for key in expired:
            self._call_counts.pop(key, None)


def _current_turn_key() -> str:
    request_id = get_request_id()
    if request_id and request_id != "-":
        return f"request:{request_id}"
    task = asyncio.current_task()
    if task is not None:
        return f"task:{id(task)}"
    return "process"


_tool_admission_gate = ToolAdmissionGate()


def get_tool_admission_gate() -> ToolAdmissionGate:
    return _tool_admission_gate


def reset_tool_admission_gate() -> None:
    _tool_admission_gate.reset()
