from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import uuid
from collections import Counter
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.book_intent import TurnPolicy, build_turn_policy
from app.services.planning import ComplexityAssessment, TaskPlan, build_task_plan


logger = logging.getLogger(__name__)

TURN_EXECUTION_PLAN_VERSION = "turn-execution-plan-v1"
_ROUTER_LLM_TIMEOUT_SECONDS = 6

IntentLayer = Literal["hard_rule", "keyword_semantic", "llm_router"]
ToolDecisionValue = Literal["required", "optional", "forbidden"]
PreActionStatus = Literal["ok", "failed", "skipped"]

_ASCII_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_WEB_COMMAND_RE = re.compile(
    "|".join(
        f"(?:{pattern})"
        for pattern in (
            r"\u641c(?:\u7d22|\u4e00\u4e0b|\u4e00\u4e2a|\u4e00\u4e9b)?",
            r"\u67e5(?:\u4e00\u4e0b|\u67e5)?",
            r"\u5e2e\u6211(?:\u641c|\u67e5)",
            r"\u7f51\u4e0a(?:\u641c|\u67e5|\u770b)",
            r"\bsearch\b",
            r"\blook\s+up\b",
            r"\bfind\s+online\b",
            r"\bgoogle\b",
        )
    ),
    re.IGNORECASE,
)
_WEATHER_RE = re.compile(r"\u5929\u6c14|\u6c14\u6e29|\u964d\u96e8|\u4e0b\u96e8|\bweather\b|\bforecast\b", re.IGNORECASE)
_MEMORY_LOOKUP_RE = re.compile(
    "|".join(
        f"(?:{pattern})"
        for pattern in (
            r"\u6211\u53eb\u4ec0\u4e48",
            r"\u6211\u7684\u540d\u5b57",
            r"\u6211\u662f\u8c01",
            r"\u4f60\u77e5\u9053\u6211\u662f\u8c01",
            r"\u4f60\u77e5\u9053\u6211\u53eb",
            r"\u4f60\u8bb0\u5f97\u6211",
            r"\u6211\u7684(?:\u732b|\u732b\u54aa|\u72d7|\u72d7\u72d7|\u5ba0\u7269)",
            r"(?:\u4f60\u8fd8?\u8bb0\u5f97|\u8fd8?\u8bb0\u5f97)(?:\u5173\u4e8e)?\u6211\u7684",
            r"\u6211\u7684.+(?:\u662f\u4ec0\u4e48|\u53eb\u4ec0\u4e48|\u6709\u54ea\u4e9b|\u653e\u5728\u54ea|\u5728\u54ea)",
            r"\bwhat(?:'s| is)\s+my\s+name\b",
            r"\bwho\s+am\s+i\b",
            r"\bdo\s+you\s+remember\s+me\b",
        )
    ),
    re.IGNORECASE,
)
_BOOK_TITLE_TEXT = r"[^。！？!?,，；;\n\r]{1,80}"
_QUOTED_BOOK_TITLE_RE = re.compile(
    r"(?:\u300a(?P<cjk>[^《》]{1,80})\u300b|[\"'](?P<quoted>[^\"']{1,80})[\"'])"
)
_READING_FEEDBACK_RE = re.compile(
    "|".join(
        f"(?:{pattern})"
        for pattern in (
            r"\u770b\u8fc7",
            r"\u8bfb\u8fc7",
            r"\u5df2\u8bfb",
            r"\u8bfb\u5b8c",
            r"\u5df2\u7ecf\u8bfb",
            r"\balready\s+read\b",
            r"\bfinished\s+reading\b",
            r"\bread\s+it\b",
        )
    ),
    re.IGNORECASE,
)
_NEGATIVE_BOOK_FEEDBACK_RE = re.compile(
    "|".join(
        f"(?:{pattern})"
        for pattern in (
            r"\u4e0d\u611f\u5174\u8da3",
            r"\u6ca1\u5174\u8da3",
            r"\u4e0d\u559c\u6b22",
            r"\u8ba8\u538c",
            r"\bnot\s+interested\b",
            r"\bdislike\b",
            r"\bhate\b",
        )
    ),
    re.IGNORECASE,
)
_TITLE_AFTER_READ_RE = re.compile(
    rf"(?:\u6211)?(?:\u5df2\u7ecf)?(?:\u770b\u8fc7|\u8bfb\u8fc7|\u8bfb\u5b8c|\u5df2\u8bfb)(?:\u4e86|\u8fc7)?(?P<title>{_BOOK_TITLE_TEXT})",
    re.IGNORECASE,
)
_TITLE_AFTER_EN_READ_RE = re.compile(
    rf"\bi\s+(?:already\s+)?(?:read|finished(?:\s+reading)?)\s+(?P<title>{_BOOK_TITLE_TEXT})",
    re.IGNORECASE,
)
_TITLE_BEFORE_NEGATIVE_RE = re.compile(
    rf"(?:\u6211)?(?:\u5bf9)?(?P<title>{_BOOK_TITLE_TEXT})(?:\u4e0d\u611f\u5174\u8da3|\u6ca1\u5174\u8da3|\u4e0d\u559c\u6b22|\u8ba8\u538c)",
    re.IGNORECASE,
)
_TITLE_AFTER_NEGATIVE_RE = re.compile(
    rf"(?:\u6211)?(?:\u4e0d\u611f\u5174\u8da3|\u6ca1\u5174\u8da3|\u4e0d\u559c\u6b22|\u8ba8\u538c)(?:\u8fd9\u672c|\u8fd9\u672c\u4e66)?(?P<title>{_BOOK_TITLE_TEXT})",
    re.IGNORECASE,
)
_TITLE_AFTER_EN_NEGATIVE_RE = re.compile(
    rf"\b(?:not\s+interested\s+in|dislike|hate)\s+(?P<title>{_BOOK_TITLE_TEXT})",
    re.IGNORECASE,
)

_SEMANTIC_PROTOTYPES: dict[str, list[str]] = {
    "external_lookup": [
        "what is the current address",
        "where is this place located",
        "find the official website",
        "look up contact information",
        "\u5177\u4f53\u5730\u5740",
        "\u5b98\u65b9\u7f51\u7ad9",
        "\u8054\u7cfb\u65b9\u5f0f",
    ],
    "current_fact": [
        "latest news today",
        "current price today",
        "stock price now",
        "exchange rate today",
        "\u6700\u65b0\u6d88\u606f",
        "\u73b0\u5728\u4ef7\u683c",
    ],
    "weather_lookup": [
        "weather today",
        "weather forecast",
        "is it raining today",
        "\u4eca\u5929\u5929\u6c14",
        "\u5929\u6c14\u9884\u62a5",
    ],
    "memory_lookup": [
        "what is my name",
        "who am i",
        "what do you remember about me",
        "\u6211\u53eb\u4ec0\u4e48",
        "\u6211\u662f\u8c01",
    ],
    "recommend_books": [
        "recommend books for me",
        "what should i read next",
        "find warm character driven novels",
        "\u63a8\u8350\u4e66",
        "\u4e66\u5355",
        "\u60f3\u770b\u70b9\u6e29\u6696\u7684\u5c0f\u8bf4",
        "\u9002\u5408\u6211\u7684\u4e66",
    ],
    "recommendation_history": [
        "reading history",
        "why was this book not recommended",
        "show rejected books",
        "\u9605\u8bfb\u5386\u53f2",
        "\u5df2\u8bfb\u8bb0\u5f55",
        "\u4e3a\u4ec0\u4e48\u6ca1\u63a8\u8350",
        "\u62d2\u7edd\u8bb0\u5f55",
    ],
    "reading_feedback": [
        "i already read this book",
        "i am not interested in this book",
        "mark this book as read",
        "\u6211\u770b\u8fc7\u8fd9\u672c\u4e66",
        "\u6211\u8bfb\u8fc7\u8fd9\u672c",
        "\u8fd9\u672c\u6211\u4e0d\u611f\u5174\u8da3",
    ],
    "deep_research": [
        "deep research this topic",
        "make a research report",
        "\u6df1\u5ea6\u641c\u7d22",
        "\u6df1\u5ea6\u7814\u7a76",
        "\u7814\u7a76\u62a5\u544a",
    ],
}

_ROUTER_ALLOWED_INTENTS = frozenset(
    {
        "answer_question",
        "external_lookup",
        "current_fact",
        "weather_lookup",
        "memory_lookup",
        "memory_update",
        "recommend_books",
        "recommendation_history",
        "reading_feedback",
        "deep_research",
    }
)


class IntentCandidate(BaseModel):
    intent: str
    layer: IntentLayer
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("intent", mode="before")
    @classmethod
    def normalize_intent(cls, value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "_")


class TurnToolDecision(BaseModel):
    tool_name: str
    decision: ToolDecisionValue
    reason: str = ""
    source_intents: list[str] = Field(default_factory=list)
    action_id: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_name", mode="before")
    @classmethod
    def normalize_tool_name(cls, value: Any) -> str:
        return str(value or "").strip()


class PreActionResult(BaseModel):
    action_id: str
    tool_name: str
    status: PreActionStatus
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str = ""
    duration_ms: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TurnExecutionPlan(BaseModel):
    result_mode: str = "turn_execution_plan"
    contract_version: str = TURN_EXECUTION_PLAN_VERSION
    user_message: str = ""
    turn_policy: TurnPolicy
    intent_candidates: list[IntentCandidate] = Field(default_factory=list)
    tool_decisions: list[TurnToolDecision] = Field(default_factory=list)
    required_actions: list[TurnToolDecision] = Field(default_factory=list)
    optional_actions: list[TurnToolDecision] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    complexity: ComplexityAssessment = Field(default_factory=ComplexityAssessment)
    task_plan: TaskPlan | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


async def build_turn_execution_plan(
    *,
    user_message: str,
    user_id: UUID | None = None,
    thread_id: UUID | None = None,
    model_name: str = "",
    thinking_mode: bool = False,
    allow_llm_router: bool = True,
) -> TurnExecutionPlan:
    """Run layer 0-3 routing and return app-owned action candidates.

    This function is decision-only. Callers must pass its required actions
    through ``SystemRuntime`` and consume a ``PlanReceipt`` before answering.
    ``allow_llm_router=False`` lets the unified ActionPlanner use one LLM call
    for both ambiguous intent resolution and complex task planning.
    """

    message = _compact_text(user_message, max_length=1000)
    policy = build_turn_policy(message)
    candidates = _dedupe_candidates(
        [
            *_layer0_hard_rule_candidates(message, policy),
            *_layer1_keyword_semantic_candidates(message, policy),
        ]
    )
    router_metadata: dict[str, Any] = {"router_llm_used": False}

    if allow_llm_router and _needs_llm_router(message, candidates, policy):
        llm_candidates, router_metadata = await _layer2_llm_router_candidates(
            message,
            model_name=model_name,
            thinking_mode=thinking_mode,
        )
        candidates = _dedupe_candidates([*candidates, *llm_candidates])

    decisions = _layer3_policy_decisions(
        policy=policy,
        candidates=candidates,
        user_message=message,
        user_id=user_id,
        thread_id=thread_id,
    )
    required = [item for item in decisions if item.decision == "required"]
    optional = [item for item in decisions if item.decision == "optional"]
    forbidden = [item.tool_name for item in decisions if item.decision == "forbidden"]
    complexity, task_plan = build_task_plan(
        user_message=message,
        policy=policy,
        required_actions=required,
    )
    return TurnExecutionPlan(
        user_message=message,
        turn_policy=policy,
        intent_candidates=candidates,
        tool_decisions=decisions,
        required_actions=required,
        optional_actions=optional,
        forbidden_tools=_dedupe_strings([*forbidden, *policy.denied_tools]),
        complexity=complexity,
        task_plan=task_plan,
        metadata={
            "layer0": "deterministic_hard_rules",
            "layer1": "keyword_plus_local_semantic_vectors",
            "layer2": "router_llm_structured_candidates_only",
            "layer3": "policy_engine_final_decision",
            "router_llm": router_metadata,
            "decision_only": True,
            "executes_required_tools": False,
            "llm_router_enabled": allow_llm_router,
            "route_type": "slow_path",
            "planner_used": task_plan is not None,
        },
    )


def _layer0_hard_rule_candidates(
    user_message: str,
    policy: TurnPolicy,
) -> list[IntentCandidate]:
    candidates: list[IntentCandidate] = []
    metadata = policy.intent.metadata

    if bool(metadata.get("web_search_recommended")):
        candidates.append(
            IntentCandidate(
                intent="external_lookup",
                layer="hard_rule",
                confidence=0.96,
                evidence=["turn_policy.web_search_recommended"],
                metadata={"source": "turn_policy"},
            )
        )
    if _WEB_COMMAND_RE.search(user_message) and not policy.can_search_books:
        candidates.append(
            IntentCandidate(
                intent="external_lookup",
                layer="hard_rule",
                confidence=0.92,
                evidence=["explicit_search_or_lookup_command"],
            )
        )
    if _WEATHER_RE.search(user_message):
        candidates.append(
            IntentCandidate(
                intent="weather_lookup",
                layer="hard_rule",
                confidence=0.95,
                evidence=["weather_keyword"],
            )
        )
    if not policy.can_view_recommendation_history and (
        bool(metadata.get("memory_lookup")) or _MEMORY_LOOKUP_RE.search(user_message)
    ):
        candidates.append(
            IntentCandidate(
                intent="memory_lookup",
                layer="hard_rule",
                confidence=0.95,
                evidence=["profile_memory_lookup"],
            )
        )
    if policy.can_write_memory:
        candidates.append(
            IntentCandidate(
                intent="memory_update",
                layer="hard_rule",
                confidence=0.9,
                evidence=["turn_policy.can_write_memory"],
            )
        )
    if (
        not policy.can_view_recommendation_history
        and (
            bool(metadata.get("recommendation_signal"))
            or _book_feedback_from_message(user_message)
        )
    ):
        feedback = _book_feedback_from_message(user_message)
        candidates.append(
            IntentCandidate(
                intent="reading_feedback",
                layer="hard_rule",
                confidence=0.94 if feedback else 0.82,
                evidence=[
                    "recommendation_behavior_signal",
                    *(["extractable_book_feedback"] if feedback else []),
                ],
                metadata={"feedback": feedback or {}},
            )
        )
    if policy.can_recommend_books:
        candidates.append(
            IntentCandidate(
                intent="recommend_books",
                layer="hard_rule",
                confidence=0.95,
                evidence=["turn_policy.can_recommend_books"],
            )
        )
    if policy.can_view_recommendation_history:
        candidates.append(
            IntentCandidate(
                intent="recommendation_history",
                layer="hard_rule",
                confidence=0.95,
                evidence=["turn_policy.can_view_recommendation_history"],
            )
        )
    if policy.can_start_research:
        candidates.append(
            IntentCandidate(
                intent="deep_research",
                layer="hard_rule",
                confidence=0.95,
                evidence=["turn_policy.can_start_research"],
            )
        )
    return candidates


def _layer1_keyword_semantic_candidates(
    user_message: str,
    policy: TurnPolicy,
) -> list[IntentCandidate]:
    candidates: list[IntentCandidate] = []
    normalized = user_message.strip()
    if not normalized:
        return candidates

    for intent, prototypes in _SEMANTIC_PROTOTYPES.items():
        best_score = max((_cosine_text_similarity(normalized, item) for item in prototypes), default=0.0)
        if best_score >= 0.36:
            candidates.append(
                IntentCandidate(
                    intent=intent,
                    layer="keyword_semantic",
                    confidence=min(0.88, 0.55 + best_score),
                    evidence=[f"prototype_similarity:{best_score:.2f}"],
                    metadata={"match_type": "local_vector_semantic"},
                )
            )

    if policy.intent.primary_intent == "answer_question" and not candidates:
        candidates.append(
            IntentCandidate(
                intent="answer_question",
                layer="keyword_semantic",
                confidence=0.7,
                evidence=["no_tool_intent_detected"],
            )
        )
    return candidates


async def _layer2_llm_router_candidates(
    user_message: str,
    *,
    model_name: str = "",
    thinking_mode: bool = False,
) -> tuple[list[IntentCandidate], dict[str, Any]]:
    metadata: dict[str, Any] = {"router_llm_used": True, "status": "skipped"}
    model, model_source = await _resolve_router_model(model_name, thinking_mode)
    metadata["model_source"] = model_source
    if model is None:
        metadata["status"] = "unavailable"
        return [], metadata

    prompt = (
        "You are an intent router. Return structured intent candidates only; "
        "do not answer the user and do not execute tools.\n"
        "Allowed intent names: answer_question, external_lookup, current_fact, "
        "weather_lookup, memory_lookup, memory_update, recommend_books, "
        "recommendation_history, reading_feedback, deep_research.\n"
        "Return JSON only in this shape: "
        "{\"intents\":[{\"intent\":\"external_lookup\",\"confidence\":0.0,"
        "\"evidence\":[\"short reason\"],\"suggested_tools\":[\"web_search\"]}],"
        "\"notes\":\"optional\"}.\n\n"
        f"User message: {user_message}"
    )
    try:
        async with asyncio.timeout(_ROUTER_LLM_TIMEOUT_SECONDS):
            response = await model.ainvoke(prompt)
        payload = _parse_json_object(_message_text(response))
    except TimeoutError:
        metadata["status"] = "timeout"
        metadata["error"] = f"router LLM timed out after {_ROUTER_LLM_TIMEOUT_SECONDS}s"
        return [], metadata
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc) or exc.__class__.__name__
        return [], metadata

    raw_intents = payload.get("intents") if isinstance(payload, dict) else []
    candidates: list[IntentCandidate] = []
    for item in raw_intents if isinstance(raw_intents, list) else []:
        if not isinstance(item, dict):
            continue
        intent = str(item.get("intent") or "").strip().lower().replace(" ", "_")
        if intent not in _ROUTER_ALLOWED_INTENTS:
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        candidates.append(
            IntentCandidate(
                intent=intent,
                layer="llm_router",
                confidence=max(0.0, min(confidence, 0.9)),
                evidence=[
                    _compact_text(evidence, max_length=120)
                    for evidence in item.get("evidence", [])[:4]
                ],
                metadata={
                    "router_notes": payload.get("notes", ""),
                    "suggested_tools": [
                        _compact_text(tool_name, max_length=80)
                        for tool_name in item.get("suggested_tools", [])[:6]
                    ],
                },
            )
        )

    metadata["status"] = "ok"
    metadata["candidate_count"] = len(candidates)
    return candidates, metadata


def _layer3_policy_decisions(
    *,
    policy: TurnPolicy,
    candidates: list[IntentCandidate],
    user_message: str,
    user_id: UUID | None,
    thread_id: UUID | None,
) -> list[TurnToolDecision]:
    decisions: list[TurnToolDecision] = []
    intent_names = _candidate_names(candidates, minimum_confidence=0.78)

    if intent_names.intersection({"external_lookup", "current_fact", "weather_lookup"}):
        if policy.can_use_web_search:
            decisions.append(
                TurnToolDecision(
                    tool_name="web_search",
                    decision="required",
                    reason="External/current lookup must be grounded by a web tool result.",
                    source_intents=sorted(
                        intent_names.intersection(
                            {"external_lookup", "current_fact", "weather_lookup"}
                        )
                    ),
                    action_id=_new_action_id("web_search"),
                    args={
                        "query": _build_web_search_query(user_message),
                        "max_results": 3,
                        "search_depth": "basic",
                        "include_answer": True,
                    },
                )
            )
        else:
            decisions.append(
                TurnToolDecision(
                    tool_name="web_search",
                    decision="forbidden",
                    reason="Turn policy forbids web search.",
                    source_intents=sorted(intent_names),
                )
            )

    if "memory_lookup" in intent_names:
        if policy.can_search_memory and user_id is not None:
            decisions.append(
                TurnToolDecision(
                    tool_name="search_memory",
                    decision="required",
                    reason="User asked about stored profile memory.",
                    source_intents=["memory_lookup"],
                    action_id=_new_action_id("search_memory"),
                    args={
                        "user_id": str(user_id),
                        "thread_id": str(thread_id) if thread_id else None,
                        "query": user_message,
                        "memory_types": [
                            "state",
                            "preference",
                            "feedback",
                            "reading_state",
                            "entity",
                            "correction",
                        ],
                        "limit": 10,
                    },
                )
            )
        else:
            decisions.append(
                TurnToolDecision(
                    tool_name="search_memory",
                    decision="forbidden",
                    reason="Memory lookup is unavailable without policy permission or user_id.",
                    source_intents=["memory_lookup"],
                )
            )

    if "recommend_books" in intent_names:
        if policy.can_search_books:
            if policy.can_search_memory and user_id is not None:
                _append_tool_decision(
                    decisions,
                    TurnToolDecision(
                        tool_name="search_memory",
                        decision="required",
                        reason="Ordinary recommendation must consume current user memory before answering.",
                        source_intents=["recommend_books"],
                        action_id=_new_action_id("search_memory"),
                        args={
                            "user_id": str(user_id),
                            "thread_id": str(thread_id) if thread_id else None,
                            "query": user_message,
                            "memory_types": [
                                "preference",
                                "reading_state",
                                "feedback",
                                "correction",
                            ],
                            "limit": 10,
                        },
                    ),
                )
            decisions.append(
                TurnToolDecision(
                    tool_name="search_books",
                    decision="required",
                    reason="Explicit book recommendation requires fresh unsuppressed book candidates.",
                    source_intents=["recommend_books"],
                    action_id=_new_action_id("search_books"),
                    args={
                        "query": user_message,
                        "user_id": str(user_id) if user_id else None,
                        "limit": 5,
                        "allow_additional_search": False,
                    },
                )
            )
        else:
            decisions.append(
                TurnToolDecision(
                    tool_name="search_books",
                    decision="forbidden",
                    reason="Turn policy forbids ordinary book search.",
                    source_intents=["recommend_books"],
                )
            )

    if "recommendation_history" in intent_names:
        if policy.can_view_recommendation_history and user_id is not None:
            history_args = _build_recommendation_history_args(
                user_message=user_message,
                user_id=user_id,
            )
            decisions.append(
                TurnToolDecision(
                    tool_name="get_recommendation_history",
                    decision="required",
                    reason="Explicit history or suppression explanation must read suppressed records in history mode.",
                    source_intents=["recommendation_history"],
                    action_id=_new_action_id("get_recommendation_history"),
                    args=history_args,
                )
            )
        else:
            decisions.append(
                TurnToolDecision(
                    tool_name="get_recommendation_history",
                    decision="forbidden",
                    reason="Recommendation history is unavailable without policy permission or user_id.",
                    source_intents=["recommendation_history"],
                )
            )

    if (
        "reading_feedback" in intent_names
        and "recommendation_history" not in intent_names
        and user_id is not None
    ):
        feedback = _feedback_from_candidates(candidates) or _book_feedback_from_message(
            user_message
        )
        if feedback and feedback.get("book_title"):
            if feedback.get("writes_long_term_memory") and policy.can_write_memory:
                decisions.append(
                    TurnToolDecision(
                        tool_name="record_book_feedback",
                        decision="required",
                        reason="The user gave explicit reading/book feedback with an extractable title.",
                        source_intents=["reading_feedback"],
                        action_id=_new_action_id("record_book_feedback"),
                        args={
                            "user_id": str(user_id),
                            "thread_id": str(thread_id) if thread_id else None,
                            "book_title": feedback["book_title"],
                            "interaction_type": feedback["interaction_type"],
                            "note": user_message,
                        },
                        metadata={"feedback": feedback},
                    )
                )
            elif policy.can_record_recommendation_signal:
                decisions.append(
                    TurnToolDecision(
                        tool_name="record_recommendation_signal",
                        decision="required",
                        reason="The user gave an explicit recommendation behavior signal with an extractable title.",
                        source_intents=["reading_feedback"],
                        action_id=_new_action_id("record_recommendation_signal"),
                        args={
                            "user_id": str(user_id),
                            "thread_id": str(thread_id) if thread_id else None,
                            "book_title": feedback["book_title"],
                            "event_type": feedback["event_type"],
                            "signal_polarity": feedback["signal_polarity"],
                            "signal_strength": feedback["signal_strength"],
                            "source": "system",
                            "note": user_message,
                            "metadata": {
                                "capture_source": "turn_execution_policy",
                                "writes_long_term_memory": False,
                            },
                        },
                        metadata={"feedback": feedback},
                    )
                )

    if "deep_research" in intent_names:
        if policy.can_start_research and policy.can_use_research_tools and user_id is not None:
            research_mode = _research_mode_from_message(user_message)
            decisions.extend(
                [
                    TurnToolDecision(
                        tool_name="start_research",
                        decision="required",
                        reason="Deep Research requires app-owned research state before the model answers.",
                        source_intents=["deep_research"],
                        action_id=_new_action_id("start_research"),
                        args=_build_start_research_args(
                            user_message=user_message,
                            user_id=user_id,
                            thread_id=thread_id,
                            mode=research_mode,
                        ),
                    ),
                    TurnToolDecision(
                        tool_name="search_research_sources",
                        decision="required",
                        reason="Deep Research must attempt source-backed acquisition before the model answers.",
                        source_intents=["deep_research"],
                        action_id=_new_action_id("search_research_sources"),
                        args={
                            "query": user_message,
                            "subquestion": user_message,
                            "limit": 5,
                            "provider_source": "duckduckgo",
                            "include_extraction": True,
                            "metadata": {"capture_source": "turn_execution_policy"},
                        },
                    ),
                    TurnToolDecision(
                        tool_name="collect_research_sources",
                        decision="required",
                        reason="Deep Research source-search results must be logged into research state.",
                        source_intents=["deep_research"],
                        action_id=_new_action_id("collect_research_sources"),
                        args={
                            "user_id": str(user_id),
                            "query": user_message,
                            "subquestion": user_message,
                            "provider_source": "duckduckgo_source_search",
                            "metadata": {"depends_on": "search_research_sources"},
                        },
                    ),
                    TurnToolDecision(
                        tool_name="add_evidence",
                        decision="required",
                        reason="Extractable source records should pass through Evidence Admission before answer synthesis.",
                        source_intents=["deep_research"],
                        action_id=_new_action_id("add_evidence"),
                        args={
                            "user_id": str(user_id),
                            "max_records": 3,
                            "metadata": {"depends_on": "search_research_sources"},
                        },
                    ),
                    TurnToolDecision(
                        tool_name="build_research_report",
                        decision="required",
                        reason="The model should consume an app-built research report, not raw unverified claims only.",
                        source_intents=["deep_research"],
                        action_id=_new_action_id("build_research_report"),
                        args={
                            "user_id": str(user_id),
                            "limit_steps": 100,
                            "limit_evidence": 100,
                        },
                    ),
                    TurnToolDecision(
                        tool_name="finalize_research_answer",
                        decision="required",
                        reason="Deep Research final answer should be projected from verified report claims and gaps.",
                        source_intents=["deep_research"],
                        action_id=_new_action_id("finalize_research_answer"),
                        args={
                            "user_id": str(user_id),
                            "limit_steps": 100,
                            "limit_evidence": 100,
                        },
                    ),
                ]
            )
        else:
            for tool_name in (
                "start_research",
                "search_research_sources",
                "collect_research_sources",
                "add_evidence",
                "build_research_report",
                "finalize_research_answer",
            ):
                decisions.append(
                    TurnToolDecision(
                        tool_name=tool_name,
                        decision="forbidden",
                        reason="Deep Research is unavailable without policy permission or user_id.",
                        source_intents=["deep_research"],
                    )
                )

    seen = {item.tool_name for item in decisions}
    for tool_name in policy.denied_tools:
        if tool_name in seen:
            continue
        decisions.append(
            TurnToolDecision(
                tool_name=tool_name,
                decision="forbidden",
                reason="Denied by current TurnPolicy.",
            )
        )
    return decisions


async def _execute_web_search(decision: TurnToolDecision) -> PreActionResult:
    start = time.perf_counter()
    try:
        from app.agents.tools.web import create_web_search

        tool = create_web_search()
        raw_output = await tool.ainvoke(_without_none(decision.args))
        output = _json_or_text(raw_output)
        status = _pre_action_status(output)
        error = _pre_action_error(output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=status,
            input=_without_none(decision.args),
            output=output,
            error=error,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed web_search failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=_without_none(decision.args),
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_search_memory(
    decision: TurnToolDecision,
    *,
    user_id: UUID | None,
    thread_id: UUID | None,
) -> PreActionResult:
    start = time.perf_counter()
    args = {
        **decision.args,
        "user_id": str(user_id) if user_id else decision.args.get("user_id"),
        "thread_id": str(thread_id) if thread_id else decision.args.get("thread_id"),
    }
    try:
        from app.agents.tools.memory import search_memory

        raw_output = await search_memory.ainvoke(_without_none(args))
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=_without_none(args),
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed search_memory failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=_without_none(args),
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_search_books(decision: TurnToolDecision) -> PreActionResult:
    start = time.perf_counter()
    args = _without_none(decision.args)
    try:
        from app.agents.tools.books import search_books

        raw_output = await search_books.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed search_books failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_get_recommendation_history(
    decision: TurnToolDecision,
) -> PreActionResult:
    start = time.perf_counter()
    args = _without_none(decision.args)
    try:
        from app.agents.tools.books import get_recommendation_history

        raw_output = await get_recommendation_history.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed get_recommendation_history failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_record_book_feedback(
    decision: TurnToolDecision,
) -> PreActionResult:
    start = time.perf_counter()
    args = _without_none(decision.args)
    try:
        from app.agents.tools.books import record_book_feedback

        raw_output = await record_book_feedback.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed record_book_feedback failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_record_recommendation_signal(
    decision: TurnToolDecision,
) -> PreActionResult:
    start = time.perf_counter()
    args = _without_none(decision.args)
    try:
        from app.agents.tools.books import record_recommendation_signal

        raw_output = await record_recommendation_signal.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed record_recommendation_signal failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_start_research(decision: TurnToolDecision) -> PreActionResult:
    start = time.perf_counter()
    args = _without_none(decision.args)
    try:
        from app.agents.tools.research import start_research

        try:
            raw_output = await start_research.ainvoke(args)
            metadata_extra: dict[str, Any] = {}
        except Exception as exc:
            if not args.get("thread_id") or not _missing_conversation_thread_error(exc):
                raise
            retry_args = dict(args)
            retry_args.pop("thread_id", None)
            raw_output = await start_research.ainvoke(retry_args)
            args = retry_args
            metadata_extra = {
                "thread_id_dropped": True,
                "thread_id_drop_reason": "conversation_not_created",
            }
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={
                "decision": decision.model_dump(mode="json"),
                **metadata_extra,
            },
        )
    except Exception as exc:
        logger.exception("Pre-executed start_research failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_search_research_sources(
    decision: TurnToolDecision,
) -> PreActionResult:
    start = time.perf_counter()
    args = _without_none(decision.args)
    try:
        from app.agents.tools.research import search_research_sources

        raw_output = await search_research_sources.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed search_research_sources failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_collect_research_sources(
    decision: TurnToolDecision,
    previous_results: list[PreActionResult],
) -> PreActionResult:
    start = time.perf_counter()
    run_id = _research_run_id_from_results(previous_results)
    search_output = _latest_output(previous_results, "search_research_sources")
    records = _research_source_records(search_output)
    args = {
        **decision.args,
        "run_id": run_id,
        "sources": records,
        "status": _research_collection_status(search_output),
        "rationale": "Record system-executed source search results before evidence admission.",
        "duration_ms": _result_duration(previous_results, "search_research_sources"),
        "error": _research_source_search_error(search_output),
    }
    args = _without_none(args)
    if not run_id:
        return _dependency_skipped_result(
            decision,
            start,
            args,
            "missing run_id from start_research",
        )

    try:
        from app.agents.tools.research import collect_research_sources

        raw_output = await collect_research_sources.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={
                "decision": decision.model_dump(mode="json"),
                "source_record_count": len(records),
            },
        )
    except Exception as exc:
        logger.exception("Pre-executed collect_research_sources failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_add_research_evidence(
    decision: TurnToolDecision,
    previous_results: list[PreActionResult],
) -> PreActionResult:
    start = time.perf_counter()
    run_id = _research_run_id_from_results(previous_results)
    records = _research_source_records(
        _latest_output(previous_results, "search_research_sources")
    )
    max_records = int(decision.args.get("max_records") or 3)
    selected = records[: max(0, min(max_records, 5))]
    base_args = {
        **decision.args,
        "run_id": run_id,
        "record_count": len(selected),
    }
    if not run_id:
        return _dependency_skipped_result(
            decision,
            start,
            _without_none(base_args),
            "missing run_id from start_research",
        )
    if not selected:
        return _dependency_skipped_result(
            decision,
            start,
            _without_none(base_args),
            "no extractable source records from search_research_sources",
        )

    added: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        from app.agents.tools.research import add_evidence

        for record in selected:
            args = _without_none(
                {
                    "user_id": decision.args.get("user_id"),
                    "run_id": run_id,
                    "source_type": record.get("source_type") or "web",
                    "source_title": record.get("source_title") or "",
                    "source_url": record.get("source_url") or "",
                    "claim": record.get("claim") or "",
                    "excerpt": record.get("excerpt") or record.get("claim") or "",
                    "quality": record.get("quality") or "unknown",
                    "relevance": record.get("relevance") or 3,
                    "known_facts": [record.get("claim")]
                    if record.get("claim")
                    else [],
                    "metadata": {
                        "capture_source": "turn_execution_policy",
                        "source_record": record,
                    },
                }
            )
            if not args.get("claim"):
                errors.append("skipped record without claim")
                continue
            raw_output = await add_evidence.ainvoke(args)
            output = _json_or_text(raw_output)
            added.append({"input": args, "output": output})

        status: PreActionStatus = "ok" if added else "failed"
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=status,
            input=_without_none(base_args),
            output={
                "status": "ok" if added else "empty_result",
                "result_mode": "research_evidence_admission_batch",
                "run_id": run_id,
                "added_count": len(added),
                "attempted_count": len(selected),
                "results": added,
                "errors": errors,
            },
            error="; ".join(errors) if not added and errors else "",
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed add_evidence failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=_without_none(base_args),
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_build_research_report(
    decision: TurnToolDecision,
    previous_results: list[PreActionResult],
) -> PreActionResult:
    start = time.perf_counter()
    run_id = _research_run_id_from_results(previous_results)
    args = _without_none({**decision.args, "run_id": run_id})
    if not run_id:
        return _dependency_skipped_result(
            decision,
            start,
            args,
            "missing run_id from start_research",
        )
    try:
        from app.agents.tools.research import build_research_report

        raw_output = await build_research_report.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed build_research_report failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


async def _execute_finalize_research_answer(
    decision: TurnToolDecision,
    previous_results: list[PreActionResult],
) -> PreActionResult:
    start = time.perf_counter()
    run_id = _research_run_id_from_results(previous_results)
    args = _without_none({**decision.args, "run_id": run_id})
    if not run_id:
        return _dependency_skipped_result(
            decision,
            start,
            args,
            "missing run_id from start_research",
        )
    try:
        from app.agents.tools.research import finalize_research_answer

        raw_output = await finalize_research_answer.ainvoke(args)
        output = _json_or_text(raw_output)
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status=_pre_action_status(output),
            input=args,
            output=output,
            error=_pre_action_error(output),
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )
    except Exception as exc:
        logger.exception("Pre-executed finalize_research_answer failed")
        return PreActionResult(
            action_id=decision.action_id,
            tool_name=decision.tool_name,
            status="failed",
            input=args,
            error=str(exc) or exc.__class__.__name__,
            duration_ms=_duration_ms(start),
            metadata={"decision": decision.model_dump(mode="json")},
        )


def _research_mode_from_message(user_message: str) -> str:
    lowered = str(user_message or "").lower()
    if "deep search" in lowered or "\u6df1\u5ea6\u641c\u7d22" in user_message:
        return "deep_search"
    return "deep_research"


def _build_start_research_args(
    *,
    user_message: str,
    user_id: UUID,
    thread_id: UUID | None,
    mode: str,
) -> dict[str, Any]:
    objective = _compact_text(user_message, max_length=500)
    return _without_none(
        {
            "user_id": str(user_id),
            "thread_id": str(thread_id) if thread_id else None,
            "objective": objective,
            "mode": mode,
            "subquestions": [objective],
            "gaps": ["Need source-backed evidence before final answer."],
            "next_actions": ["Search source-backed documents for the objective."],
            "budget": {
                "max_sources": 5,
                "max_steps": 6,
                "source": "turn_execution_policy",
            },
            "stop_criteria": [
                "Source search attempted and findings or gaps are recorded."
            ],
            "metadata": {
                "capture_source": "turn_execution_policy",
                "system_executed": True,
            },
        }
    )


def _latest_output(
    previous_results: list[PreActionResult],
    tool_name: str,
) -> Any:
    for result in reversed(previous_results):
        if result.tool_name == tool_name:
            return result.output
    return None


def _research_run_id_from_results(previous_results: list[PreActionResult]) -> str:
    paths = (
        ("run", "id"),
        ("state", "run_id"),
        ("run_id",),
        ("id",),
        ("research_state", "run", "id"),
        ("research_state", "state", "run_id"),
    )
    for result in reversed(previous_results):
        if result.tool_name not in {
            "start_research",
            "collect_research_sources",
            "add_evidence",
        }:
            continue
        output = result.output
        if not isinstance(output, dict):
            continue
        for path in paths:
            value = _nested_value(output, path)
            if value:
                return str(value)
    return ""


def _research_source_records(search_output: Any) -> list[dict[str, Any]]:
    if not isinstance(search_output, dict):
        return []

    candidates = [
        _nested_value(search_output, ("extraction", "source_records")),
        search_output.get("source_records"),
        _nested_value(search_output, ("observation_batch", "observations")),
    ]
    for value in candidates:
        records = _coerce_record_list(value)
        if records:
            return records

    documents = _coerce_record_list(search_output.get("source_documents"))
    records: list[dict[str, Any]] = []
    for document in documents:
        content = (
            document.get("claim")
            or document.get("excerpt")
            or document.get("content")
            or document.get("snippet")
            or ""
        )
        if not content:
            continue
        records.append(
            {
                "source_type": document.get("source_type") or "web",
                "source_title": document.get("source_title") or document.get("title") or "",
                "source_url": document.get("source_url") or document.get("url") or "",
                "claim": content,
                "excerpt": document.get("excerpt") or content,
                "quality": document.get("quality") or "unknown",
                "relevance": document.get("relevance") or 3,
                "metadata": document.get("metadata") or {},
            }
        )
    return records


def _research_collection_status(search_output: Any) -> str:
    if not isinstance(search_output, dict):
        return "failed"
    status = str(search_output.get("status") or "").strip().lower().replace(" ", "_")
    if status in {"timeout", "failed", "skipped"}:
        return status
    if _research_source_records(search_output):
        return "completed"
    return "empty_result"


def _research_source_search_error(search_output: Any) -> str | None:
    if not isinstance(search_output, dict):
        return None
    error = search_output.get("error") or search_output.get("message")
    if error:
        return _compact_text(error, max_length=1000)
    return None


def _result_duration(
    previous_results: list[PreActionResult],
    tool_name: str,
) -> int:
    for result in reversed(previous_results):
        if result.tool_name == tool_name:
            return result.duration_ms
    return 0


def _dependency_skipped_result(
    decision: TurnToolDecision,
    start: float,
    args: dict[str, Any],
    reason: str,
) -> PreActionResult:
    return PreActionResult(
        action_id=decision.action_id,
        tool_name=decision.tool_name,
        status="skipped",
        input=args,
        output={
            "status": "skipped",
            "result_mode": "dependency_skipped",
            "tool_name": decision.tool_name,
            "reason": reason,
        },
        error=reason,
        duration_ms=_duration_ms(start),
        metadata={"decision": decision.model_dump(mode="json")},
    )


def _missing_conversation_thread_error(exc: Exception) -> bool:
    text = str(exc)
    return (
        "research_runs_thread_id_fkey" in text
        or "ForeignKeyViolationError" in text
        and "conversations" in text
    )


def _nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _coerce_record_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    records: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            records.append(item)
            continue
        if hasattr(item, "model_dump"):
            dumped = item.model_dump(mode="json")
            if isinstance(dumped, dict):
                records.append(dumped)
    return records


def _append_tool_decision(
    decisions: list[TurnToolDecision],
    decision: TurnToolDecision,
) -> None:
    for existing in decisions:
        if existing.tool_name == decision.tool_name and existing.decision == decision.decision:
            existing.source_intents = _dedupe_strings(
                [*existing.source_intents, *decision.source_intents]
            )
            existing.reason = existing.reason or decision.reason
            return
    decisions.append(decision)


def _build_recommendation_history_args(
    *,
    user_message: str,
    user_id: UUID,
) -> dict[str, Any]:
    return {
        "user_id": str(user_id),
        "history_mode": _recommendation_history_mode_from_message(user_message),
        "query": user_message,
        "book_title": _extract_book_title(user_message),
        "limit": 20,
    }


def _recommendation_history_mode_from_message(user_message: str) -> str:
    lowered = user_message.lower()
    if (
        "\u4e3a\u4ec0\u4e48" in user_message
        or "\u4e3a\u5565" in user_message
        or "why" in lowered
    ):
        return "suppression_explanation"
    if (
        "\u62d2\u7edd" in user_message
        or "\u4e0d\u611f\u5174\u8da3" in user_message
        or "\u6ca1\u5174\u8da3" in user_message
        or "rejected" in lowered
        or "not interested" in lowered
    ):
        return "rejection_history"
    if (
        "\u5df2\u8bfb" in user_message
        or "\u8bfb\u8fc7" in user_message
        or "\u770b\u8fc7" in user_message
        or "reading history" in lowered
        or "already read" in lowered
    ):
        return "reading_history"
    return "all"


def _feedback_from_candidates(candidates: list[IntentCandidate]) -> dict[str, Any]:
    for candidate in candidates:
        if candidate.intent != "reading_feedback":
            continue
        feedback = candidate.metadata.get("feedback")
        if isinstance(feedback, dict) and feedback.get("book_title"):
            return feedback
    return {}


def _book_feedback_from_message(user_message: str) -> dict[str, Any]:
    text = _compact_text(user_message, max_length=300)
    if not text:
        return {}
    if _looks_like_history_or_feedback_question(text):
        return {}

    quoted_title = _extract_book_title(text)
    if quoted_title and _READING_FEEDBACK_RE.search(text):
        return _feedback_payload(quoted_title, "read")
    if quoted_title and _NEGATIVE_BOOK_FEEDBACK_RE.search(text):
        event_type = "disliked" if _dislike_signal(text) else "not_interested"
        return _feedback_payload(quoted_title, event_type)

    for pattern in (_TITLE_AFTER_READ_RE, _TITLE_AFTER_EN_READ_RE):
        match = pattern.search(text)
        if match:
            title = _clean_book_title(match.group("title"))
            if _valid_book_title(title):
                return _feedback_payload(title, "read")

    for pattern in (
        _TITLE_BEFORE_NEGATIVE_RE,
        _TITLE_AFTER_NEGATIVE_RE,
        _TITLE_AFTER_EN_NEGATIVE_RE,
    ):
        match = pattern.search(text)
        if match:
            title = _clean_book_title(match.group("title"))
            if _valid_book_title(title):
                event_type = "disliked" if _dislike_signal(text) else "not_interested"
                return _feedback_payload(title, event_type)

    return {}


def extract_book_feedback(user_message: str) -> dict[str, Any]:
    """Return deterministic concrete-book feedback for runtime fast paths."""
    return _book_feedback_from_message(user_message)


def _looks_like_history_or_feedback_question(user_message: str) -> bool:
    lowered = user_message.lower()
    has_question_marker = any(
        marker in user_message
        for marker in ("?", "\uff1f", "\u54ea\u4e9b", "\u4ec0\u4e48", "\u5417")
    )
    if "\u8bb0\u5f55" in user_message and (
        _READING_FEEDBACK_RE.search(user_message)
        or _NEGATIVE_BOOK_FEEDBACK_RE.search(user_message)
    ):
        return True
    if has_question_marker and (
        "\u5df2\u8bfb" in user_message
        or "\u8bfb\u8fc7" in user_message
        or "\u770b\u8fc7" in user_message
        or "\u4e0d\u611f\u5174\u8da3" in user_message
        or "reading history" in lowered
        or "already read" in lowered
        or "not interested" in lowered
    ):
        return True
    return False


def _feedback_payload(book_title: str, event_type: str) -> dict[str, Any]:
    interaction_type = "read"
    signal_polarity = "neutral"
    signal_strength = 1.0
    writes_long_term_memory = True
    if event_type == "disliked":
        interaction_type = "dislike"
        signal_polarity = "negative"
        signal_strength = 0.9
    elif event_type == "not_interested":
        interaction_type = "not_interested"
        signal_polarity = "negative"
        signal_strength = 0.8

    return {
        "book_title": book_title,
        "event_type": event_type,
        "interaction_type": interaction_type,
        "signal_polarity": signal_polarity,
        "signal_strength": signal_strength,
        "writes_long_term_memory": writes_long_term_memory,
    }


def _dislike_signal(user_message: str) -> bool:
    lowered = user_message.lower()
    return (
        "\u4e0d\u559c\u6b22" in user_message
        or "\u8ba8\u538c" in user_message
        or "dislike" in lowered
        or "hate" in lowered
    )


def _extract_book_title(user_message: str) -> str:
    match = _QUOTED_BOOK_TITLE_RE.search(user_message)
    if not match:
        return ""
    return _clean_book_title(match.group("cjk") or match.group("quoted") or "")


def _clean_book_title(value: str) -> str:
    title = " ".join(str(value or "").split()).strip()
    title = re.sub(r"^(?:\u4e86|\u8fc7|\u8fd9\u672c|\u8fd9\u672c\u4e66|\u8fd9\u90e8|\u8fd9\u90e8\u4e66)", "", title)
    title = re.sub(r"(?:\u8fd9\u672c|\u8fd9\u672c\u4e66|\u8fd9\u90e8|\u8fd9\u90e8\u4e66)$", "", title)
    return title.strip(" \t\r\n,.;:!?锛屻€傦紒锛燂紱锛歕\"'鈥溾€濃€樷€欙紙锛?)[]{}")


def _valid_book_title(value: str) -> bool:
    title = str(value or "").strip()
    if not title or len(title) > 80:
        return False
    invalid = {
        "\u8fd9\u672c",
        "\u8fd9\u672c\u4e66",
        "\u8fd9\u4e66",
        "\u8fd9\u90e8",
        "\u5b83",
        "\u8fd9\u4e2a",
        "\u4ec0\u4e48",
        "this",
        "it",
        "book",
        "this book",
    }
    return title.lower() not in invalid


async def _resolve_router_model(
    model_name: str,
    thinking_mode: bool,
) -> tuple[Any | None, str]:
    try:
        from app.infra.llm import get_llm, get_system_llm
        from app.infra.llm.manager import get_model_manager

        if model_name:
            try:
                return get_llm(model_name, thinking_mode=False), f"runtime:{model_name}"
            except Exception as exc:
                logger.debug("Router LLM requested model unavailable: %s", exc)

        manager = get_model_manager()
        if not getattr(manager, "_initialized", False):
            try:
                await manager.refresh()
            except Exception as exc:
                logger.debug("Router LLM model cache refresh failed: %s", exc)
        model_id = manager.default_llm_id or manager.get_first_active_llm_id()
        if model_id:
            try:
                return get_llm(model_id, thinking_mode=False), f"runtime:{model_id}"
            except Exception as exc:
                logger.debug("Router LLM default model unavailable: %s", exc)
        try:
            return get_system_llm(), "system"
        except Exception as exc:
            return None, f"unavailable:{exc}"
    except Exception as exc:
        return None, f"unavailable:{exc}"


def _needs_llm_router(
    user_message: str,
    candidates: list[IntentCandidate],
    policy: TurnPolicy,
) -> bool:
    if not user_message.strip():
        return False
    high_confidence = _candidate_names(candidates, minimum_confidence=0.9)
    if high_confidence.intersection(
        {
            "external_lookup",
            "current_fact",
            "weather_lookup",
            "memory_lookup",
            "recommend_books",
            "recommendation_history",
            "deep_research",
        }
    ):
        return False
    if len(set(policy.intent.intents) - {"answer_question"}) > 1:
        return True
    if policy.intent.primary_intent == "answer_question":
        markers = ("?", "\uff1f", "\u987a\u4fbf", "\u7136\u540e", " and ", " also ")
        return any(marker in user_message.lower() for marker in markers) and bool(candidates)
    return False


def _candidate_names(
    candidates: list[IntentCandidate],
    *,
    minimum_confidence: float,
) -> set[str]:
    return {
        candidate.intent
        for candidate in candidates
        if candidate.confidence >= minimum_confidence
    }


def _dedupe_candidates(candidates: list[IntentCandidate]) -> list[IntentCandidate]:
    best: dict[str, IntentCandidate] = {}
    for candidate in candidates:
        existing = best.get(candidate.intent)
        if existing is None or candidate.confidence > existing.confidence:
            best[candidate.intent] = candidate
            continue
        if existing is not None and candidate.layer != existing.layer:
            existing.evidence = _dedupe_strings([*existing.evidence, *candidate.evidence])
            existing.metadata = {
                **existing.metadata,
                "additional_layers": _dedupe_strings(
                    [
                        *existing.metadata.get("additional_layers", []),
                        candidate.layer,
                    ]
                ),
            }
    return sorted(best.values(), key=lambda item: item.confidence, reverse=True)


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _build_web_search_query(user_message: str) -> str:
    return _compact_text(user_message, max_length=240)


def _cosine_text_similarity(left: str, right: str) -> float:
    left_vec = _text_vector(left)
    right_vec = _text_vector(right)
    if not left_vec or not right_vec:
        return 0.0
    numerator = sum(value * right_vec.get(key, 0) for key, value in left_vec.items())
    left_norm = math.sqrt(sum(value * value for value in left_vec.values()))
    right_norm = math.sqrt(sum(value * value for value in right_vec.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _text_vector(text: str) -> Counter[str]:
    lowered = text.lower()
    tokens = Counter(_ASCII_WORD_RE.findall(lowered))
    cjk_chars = [char for char in lowered if _CJK_RE.match(char)]
    for size in (1, 2, 3):
        for index in range(0, max(0, len(cjk_chars) - size + 1)):
            tokens["".join(cjk_chars[index : index + size])] += 1
    return tokens


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _json_or_text(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _pre_action_status(output: Any) -> PreActionStatus:
    if isinstance(output, dict):
        status = str(output.get("status") or "").strip().lower()
        if status in {"ok", "completed", "success"}:
            return "ok"
        if status in {
            "failed",
            "missing_credentials",
            "unauthorized",
            "forbidden",
            "rate_limited",
            "tool_blocked",
            "invalid_request",
            "timeout",
        }:
            return "failed"
        if output.get("result_mode"):
            return "ok"
    if output:
        return "ok"
    return "failed"


def _pre_action_error(output: Any) -> str:
    if isinstance(output, dict):
        return _compact_text(
            output.get("error") or output.get("message") or "",
            max_length=1000,
        )
    return ""


def _compact_text(value: Any, *, max_length: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _compact_json(value: Any, *, max_length: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _duration_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _new_action_id(tool_name: str) -> str:
    return f"pre_{tool_name}_{uuid.uuid4().hex[:12]}"
