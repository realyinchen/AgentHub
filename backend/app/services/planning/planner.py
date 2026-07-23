from __future__ import annotations

import re
from typing import Any

from app.services.book_intent import TurnPolicy
from app.services.planning.contracts import (
    ComplexityAssessment,
    TaskPlan,
    TaskStep,
)


_SYSTEM_FIELDS = frozenset({"user_id", "thread_id", "request_id", "tenant_id"})
_DEEP_RESEARCH_RE = re.compile(
    r"deep\s+(?:search|research)|\u6df1\u5ea6(?:\u641c\u7d22|\u7814\u7a76)|\u7814\u7a76\u62a5\u544a",
    re.IGNORECASE,
)
_MULTI_STEP_RE = re.compile(
    r"\u5206\u6790|\u5bf9\u6bd4|\u6bd4\u8f83|\u8c03\u7814|\u7814\u7a76|\u62a5\u544a|\banaly[sz]e\b|\bcompare\b|\bresearch\b|\breport\b",
    re.IGNORECASE,
)
_CONSTRAINT_PATTERNS = (
    re.compile(r"\u6700\u8fd1(?:\u4e00|\u4e24|\u4e24|\u4e09|\d+)\u5e74|\u8fd1(?:\u4e24|\u4e24|\u4e09|\d+)\u5e74"),
    re.compile(r"\u4e2d\u6587\u7248|\u4e2d\u8bd1\u672c|\bchinese(?:\s+edition)?\b", re.IGNORECASE),
    re.compile(r"\u53e3\u7891|\u8bc4\u5206|\u8bc4\u4ef7|\u9ad8\u5206|\brating\b|\breviews?\b", re.IGNORECASE),
    re.compile(r"\u4e0d\u8981|\u907f\u514d|\u522b\u592a|\u4e0d\u559c\u6b22|\bavoid\b|\bwithout\b", re.IGNORECASE),
    re.compile(r"\u6700\u597d|\u5e0c\u671b|\u504f\u597d|\u559c\u6b22|\bprefer\b|\bideally\b", re.IGNORECASE),
)


def assess_task_complexity(
    *,
    user_message: str,
    policy: TurnPolicy,
    required_actions: list[Any],
) -> ComplexityAssessment:
    reasons: list[str] = []
    constraint_count = sum(
        1 for pattern in _CONSTRAINT_PATTERNS if pattern.search(user_message)
    )
    action_count = len(required_actions)
    deep_research = bool(_DEEP_RESEARCH_RE.search(user_message)) or bool(
        policy.can_start_research
    )

    if deep_research:
        reasons.append("deep_research_requested")
    if constraint_count >= 3:
        reasons.append("multiple_user_constraints")
    if action_count >= 3:
        reasons.append("multi_capability_execution")
    if _MULTI_STEP_RE.search(user_message) and action_count >= 2:
        reasons.append("multi_step_analysis_requested")

    planner_required = deep_research or action_count >= 3 or (
        constraint_count >= 3 and action_count >= 2
    )
    if planner_required:
        level = "high"
    elif action_count >= 2 or constraint_count >= 2:
        level = "medium"
    else:
        level = "low"

    return ComplexityAssessment(
        level=level,
        planner_required=planner_required,
        reasons=reasons,
        constraint_count=constraint_count,
        required_action_count=action_count,
    )


def build_task_plan(
    *,
    user_message: str,
    policy: TurnPolicy,
    required_actions: list[Any],
) -> tuple[ComplexityAssessment, TaskPlan | None]:
    assessment = assess_task_complexity(
        user_message=user_message,
        policy=policy,
        required_actions=required_actions,
    )
    if not assessment.planner_required:
        return assessment, None

    steps: list[TaskStep] = []
    previous_step_id = ""
    for index, action in enumerate(required_actions, start=1):
        tool_name = str(getattr(action, "tool_name", "") or "unknown")
        step_id = f"step_{index}_{tool_name}"
        raw_input = dict(getattr(action, "args", {}) or {})
        business_input = {
            key: value for key, value in raw_input.items() if key not in _SYSTEM_FIELDS
        }
        steps.append(
            TaskStep(
                step_id=step_id,
                capability=_capability_for_tool(tool_name),
                action=tool_name,
                input=business_input,
                depends_on=[previous_step_id] if previous_step_id else [],
                required=True,
            )
        )
        previous_step_id = step_id

    return assessment, TaskPlan(
        goal=user_message,
        task_type=policy.intent.primary_intent,
        complexity=assessment,
        steps=steps,
        metadata={
            "uses_llm": False,
            "system_fields_removed": sorted(_SYSTEM_FIELDS),
        },
    )


def _capability_for_tool(tool_name: str) -> str:
    if "memory" in tool_name:
        return "memory"
    if "book" in tool_name or "recommendation" in tool_name:
        return "book"
    if "research" in tool_name or tool_name in {"add_evidence", "visit_source"}:
        return "research"
    if tool_name == "web_search":
        return "web"
    return "runtime"
