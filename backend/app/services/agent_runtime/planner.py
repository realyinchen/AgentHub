from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import (
    SYSTEM_ARGUMENT_FIELDS,
    ActionPlan,
    PlannedAction,
)
from app.services.book_intent import TurnPolicy
from app.services.fast_path import decide_fast_path
from app.services.turn_execution import TurnExecutionPlan, build_turn_execution_plan


logger = logging.getLogger(__name__)

_LLM_PLANNER_TIMEOUT_SECONDS = 6
_POTENTIAL_PERSONAL_STATE_QUERY_RE = re.compile(
    r"(?:"
    r"\u6211\u7684.+(?:\u4ec0\u4e48|\u54ea|\u600e\u6837|\u591a\u5c11|\u51e0|\u5728\u54ea|\u4ec0\u4e48\u65f6\u5019)|"
    r"\u6211(?:\u4ec0\u4e48\u65f6\u5019|\u5e73\u65f6|\u901a\u5e38|\u4e4b\u524d|\u66fe\u7ecf|\u6709\u51e0|\u559c\u6b22\u4ec0\u4e48|\u4e0d\u559c\u6b22\u4ec0\u4e48)|"
    r"(?:\u4f60\u8fd8?\u8bb0\u5f97|\u6211\u8bf4\u8fc7|\u6211\u4e4b\u524d\u8bf4).+|"
    r"\b(?:what|when|where|which|how many)\b.+\b(?:my|i|me)\b|"
    r"\bdo you remember\b.+\b(?:my|me)\b"
    r")",
    re.IGNORECASE,
)
_POTENTIAL_EXTERNAL_FACT_QUERY_RE = re.compile(
    r"(?:\u8c01|\u591a\u5c11|\u54ea\u4e2a|\u54ea\u5bb6|\u4f55\u65f6|\u4ec0\u4e48\u65f6\u5019|\u662f\u5426|\u6709\u6ca1\u6709).*[?\uff1f]|"
    r"\b(?:who|when|how\s+many|which|is\s+there|are\s+there)\b.*[?]",
    re.IGNORECASE,
)
_STABLE_EXPLANATION_RE = re.compile(
    r"^(?:\u4ec0\u4e48\u662f|\u4e3a\u4ec0\u4e48|\u4e3a\u5565|\u600e\u4e48|\u5982\u4f55|\u89e3\u91ca|\u8bf4\u660e|\u8bb2\u89e3|\u539f\u7406|\u5b9a\u4e49)|"
    r"^(?:what\s+is|why|how\s+do|how\s+does|explain|define)\b",
    re.IGNORECASE,
)
_KNOWN_OPERATIONS = frozenset(
    {
        "search_memory",
        "capture_user_state",
        "remember_memory",
        "revise_memory",
        "forget_memory",
        "web_search",
        "get_current_time",
        "search_books",
        "get_recommendation_history",
        "remember_reading_preference",
        "record_book_feedback",
        "record_recommendation_signal",
        "start_research",
        "inspect_research_state",
        "search_research_sources",
        "search_research_scholar_sources",
        "fetch_research_source",
        "collect_research_sources",
        "add_evidence",
        "build_research_observations",
        "analyze_research_data",
        "extract_research_source_records",
        "build_research_report",
        "finalize_research_answer",
        "build_recommendation_research_report",
        "plan_book_assistant_turn",
        "plan_recommendation_research_workflow",
        "run_recommendation_research_workflow",
        "run_research_harness",
    }
)


def build_fast_action_plan(user_input: UserInput) -> ActionPlan | None:
    """Return a deterministic plan without performing any side effect."""

    decision = decide_fast_path(user_input)
    if not decision.handled or decision.intent is None:
        return None

    operation = ""
    capability = "memory"
    arguments: dict[str, Any] = {}
    if decision.intent == "memory_write":
        operation = "capture_user_state"
        arguments = {
            "raw_text": user_input.content,
            "capture_mode": (
                "raw_first"
                if decision.metadata.get("generic_user_state")
                else "deterministic"
            ),
            "explicit": bool(decision.metadata.get("explicit")),
        }
    elif decision.intent == "memory_lookup":
        operation = "search_memory"
        arguments = {
            "query": str(decision.metadata.get("query") or ""),
            "lookup_kind": str(decision.metadata.get("lookup_kind") or "generic"),
            "limit": 100 if decision.metadata.get("lookup_kind") else 20,
        }
    else:
        capability = "book"
        operation = "record_book_feedback"
        feedback = dict(decision.metadata.get("feedback") or {})
        arguments = {
            "book_title": str(feedback.get("book_title") or "").strip(),
            "interaction_type": str(
                feedback.get("interaction_type")
                or feedback.get("event_type")
                or "read"
            ).strip(),
            "note": user_input.content,
        }

    action = PlannedAction(
        capability=capability,
        operation=operation,
        arguments=arguments,
        reason=decision.reason,
        metadata={"fast_intent_confidence": decision.confidence},
    )
    return ActionPlan(
        source="deterministic_rule",
        route_type="fast_path",
        intent=decision.intent,
        goal=user_input.content,
        confidence=decision.confidence,
        complexity="low",
        planner_used=False,
        response_mode="deterministic",
        actions=[action],
        metadata={
            "decision_only": True,
            "fast_path_executes_nothing": True,
            "fast_path_reason": decision.reason,
        },
    )


class ActionPlanner:
    """Layered planner: deterministic first, one LLM call only when needed."""

    async def plan(
        self,
        user_input: UserInput,
        *,
        model_name: str = "",
    ) -> ActionPlan:
        fast_plan = build_fast_action_plan(user_input)
        if fast_plan is not None:
            return fast_plan

        route = await build_turn_execution_plan(
            user_message=user_input.content,
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
            model_name=model_name or user_input.model_uuid or user_input.model_name or "",
            thinking_mode=False,
            allow_llm_router=False,
        )
        baseline = self._from_route_plan(route)
        baseline = _augment_compound_request_plan(baseline, user_input.content)
        if not self._needs_llm_planner(route, user_input.content):
            return baseline

        refined, planner_metadata = await self._llm_plan(
            user_input=user_input,
            route=route,
            baseline=baseline,
            model_name=model_name or user_input.model_uuid or user_input.model_name or "",
        )
        if refined is not None:
            return refined
        fallback_actions = _conservative_fallback_actions(
            baseline,
            user_input.content,
        )
        return baseline.model_copy(
            update={
                "source": "llm_planner_fallback",
                "planner_used": True,
                "actions": fallback_actions,
                "metadata": {
                    **baseline.metadata,
                    "llm_planner": planner_metadata,
                },
            }
        )

    def _from_route_plan(self, route: TurnExecutionPlan) -> ActionPlan:
        actions = [
            PlannedAction(
                action_id=item.action_id,
                capability=_capability_for_operation(item.tool_name),
                operation=item.tool_name,
                arguments=_business_arguments(item.args),
                reason=item.reason,
                metadata={
                    "decision": item.decision,
                    "source_intents": item.source_intents,
                },
            )
            for item in route.required_actions
        ]
        return ActionPlan(
            source="deterministic_rule",
            route_type="slow_path",
            intent=route.turn_policy.intent.primary_intent,
            goal=route.user_message,
            confidence=_route_confidence(route),
            complexity=route.complexity.level,
            planner_used=False,
            response_mode="model",
            actions=actions,
            forbidden_operations=route.forbidden_tools,
            policy=route.turn_policy.model_dump(mode="json"),
            metadata={
                "decision_only": True,
                "route_contract_version": route.contract_version,
                "intent_candidates": [
                    item.model_dump(mode="json") for item in route.intent_candidates
                ],
                "optional_actions": [
                    item.model_dump(mode="json") for item in route.optional_actions
                ],
                "task_plan_template": (
                    route.task_plan.model_dump(mode="json")
                    if route.task_plan is not None
                    else None
                ),
            },
        )

    @staticmethod
    def _needs_llm_planner(route: TurnExecutionPlan, user_message: str) -> bool:
        if route.complexity.planner_required:
            return True
        required_operations = {item.tool_name for item in route.required_actions}
        if (
            _looks_like_potential_personal_state_query(user_message)
            and "search_memory" not in required_operations
        ):
            return True
        if (
            _looks_like_potential_external_fact_query(user_message)
            and "web_search" not in required_operations
            and "search_memory" not in required_operations
        ):
            return True
        candidates = route.intent_candidates
        if not candidates:
            return False
        highest = max((item.confidence for item in candidates), default=0.0)
        distinct = {item.intent for item in candidates if item.confidence >= 0.65}
        return highest < 0.9 and (len(distinct) > 1 or "answer_question" not in distinct)

    async def _llm_plan(
        self,
        *,
        user_input: UserInput,
        route: TurnExecutionPlan,
        baseline: ActionPlan,
        model_name: str,
    ) -> tuple[ActionPlan | None, dict[str, Any]]:
        metadata: dict[str, Any] = {"status": "unavailable"}
        model, source = await _resolve_planner_model(model_name)
        metadata["model_source"] = source
        if model is None:
            return None, metadata

        policy = route.turn_policy
        allowed = sorted(
            operation
            for operation in _KNOWN_OPERATIONS
            if operation not in set(route.forbidden_tools)
            and _operation_allowed_by_policy(operation, policy)
        )
        baseline_payload = [
            {
                "capability": action.capability,
                "operation": action.operation,
                "arguments": action.arguments,
                "reason": action.reason,
            }
            for action in baseline.actions
        ]
        prompt = (
            "You are the planning layer of a personal AI runtime. Do not answer "
            "the user and do not execute anything. Produce a minimal JSON action "
            "plan using business parameters only. Never emit user_id, thread_id, "
            "conversation_id, request_id, tenant_id, permissions, or credentials.\n"
            "If the answer depends on facts the user previously told the system, "
            "include search_memory. If the user states durable personal state as "
            "part of a compound request, include capture_user_state with only an "
            "exact user-authored substring as raw_text.\n"
            "Choose web_search for external facts that may have changed after model "
            "training or need current verification. Do not search for timeless "
            "explanations unless external evidence is requested.\n"
            f"Allowed operations: {json.dumps(allowed, ensure_ascii=False)}\n"
            "Return JSON only: "
            '{"intent":"...","confidence":0.0,"actions":['
            '{"capability":"memory|web|book|research|runtime",'
            '"operation":"...","arguments":{},"reason":"...",'
            '"depends_on":[0]}],"notes":"..."}. '
            "Use depends_on as zero-based action indexes. Preserve required baseline "
            "actions unless a more coherent allowed action replaces them.\n"
            f"Policy intent: {policy.intent.primary_intent}\n"
            f"Baseline actions: {json.dumps(baseline_payload, ensure_ascii=False)}\n"
            f"User goal: {user_input.content}"
        )
        try:
            async with asyncio.timeout(_LLM_PLANNER_TIMEOUT_SECONDS):
                response = await model.ainvoke(prompt)
            payload = _parse_json_object(_message_text(response))
            actions = _validate_llm_actions(payload.get("actions"), allowed)
            actions = _merge_required_baseline(actions, baseline.actions)
            if not actions and baseline.actions:
                raise ValueError("planner returned no executable actions")
            confidence = max(0.0, min(float(payload.get("confidence", 0.8)), 0.95))
            metadata.update(
                {
                    "status": "completed",
                    "notes": str(payload.get("notes") or "")[:500],
                    "action_count": len(actions),
                }
            )
            return baseline.model_copy(
                update={
                    "source": "llm_planner",
                    "intent": str(payload.get("intent") or baseline.intent),
                    "confidence": confidence,
                    "planner_used": True,
                    "actions": actions,
                    "metadata": {**baseline.metadata, "llm_planner": metadata},
                }
            ), metadata
        except TimeoutError:
            metadata.update(
                {
                    "status": "timeout",
                    "error": f"planner timed out after {_LLM_PLANNER_TIMEOUT_SECONDS}s",
                }
            )
        except Exception as exc:
            metadata.update(
                {"status": "failed", "error": str(exc) or exc.__class__.__name__}
            )
        logger.warning("LLM planner fallback: %s", metadata)
        return None, metadata


def _validate_llm_actions(raw: Any, allowed: list[str]) -> list[PlannedAction]:
    if not isinstance(raw, list):
        return []
    allowed_set = set(allowed)
    provisional: list[tuple[PlannedAction, list[int]]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation") or "").strip()
        if operation not in allowed_set:
            continue
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        arguments = _business_arguments(arguments)
        dependency_indexes = [
            int(value)
            for value in item.get("depends_on", [])
            if isinstance(value, int) and value >= 0
        ]
        provisional.append(
            (
                PlannedAction(
                    capability=str(
                        item.get("capability") or _capability_for_operation(operation)
                    ),
                    operation=operation,
                    arguments=arguments,
                    reason=str(item.get("reason") or "LLM-planned action")[:500],
                ),
                dependency_indexes,
            )
        )
    result: list[PlannedAction] = []
    ids = [item.action_id for item, _ in provisional]
    for index, (action, dependency_indexes) in enumerate(provisional):
        dependencies = [ids[value] for value in dependency_indexes if value < index]
        result.append(action.model_copy(update={"depends_on": dependencies}))
    return result


def _merge_required_baseline(
    actions: list[PlannedAction],
    baseline: list[PlannedAction],
) -> list[PlannedAction]:
    existing = {item.operation for item in actions}
    merged = list(actions)
    for required in baseline:
        if required.operation not in existing:
            merged.append(required)
            existing.add(required.operation)
    return merged


def _conservative_fallback_actions(
    baseline: ActionPlan,
    user_message: str,
) -> list[PlannedAction]:
    actions = list(baseline.actions)
    if (
        _looks_like_potential_personal_state_query(user_message)
        and not any(item.operation == "search_memory" for item in actions)
    ):
        actions.insert(
            0,
            PlannedAction(
                capability="memory",
                operation="search_memory",
                arguments={
                    "query": user_message,
                    "lookup_kind": "generic",
                    "limit": 100,
                },
                reason="Conservative read-only fallback after planner failure.",
                metadata={"fallback": "personal_state_query"},
            ),
        )
    if (
        _looks_like_potential_external_fact_query(user_message)
        and not actions
    ):
        actions.append(
            PlannedAction(
                capability="web",
                operation="web_search",
                arguments={
                    "query": user_message,
                    "max_results": 3,
                    "search_depth": "basic",
                    "include_answer": True,
                },
                reason="Conservative freshness fallback after planner failure.",
                metadata={"fallback": "external_fact_query"},
            )
        )
    return actions


def _augment_compound_request_plan(
    baseline: ActionPlan,
    user_message: str,
) -> ActionPlan:
    """Add obvious multi-action requirements without executing anything.

    This is still decision-only: deterministic rules may output a richer
    ActionPlan, but only SystemRuntime can admit and execute it.
    """

    actions = list(baseline.actions)
    added: list[str] = []
    memory_raw = _extract_compound_memory_raw_text(user_message)
    if memory_raw and not any(item.operation == "capture_user_state" for item in actions):
        actions.insert(
            0,
            PlannedAction(
                capability="memory",
                operation="capture_user_state",
                arguments={
                    "raw_text": memory_raw,
                    "capture_mode": "raw_first",
                    "explicit": True,
                },
                reason="The user explicitly asked to remember a durable personal state inside a compound request.",
                metadata={"compound_expansion": "memory_capture"},
            ),
        )
        added.append("capture_user_state")

    review_query = _extract_external_review_query(user_message)
    if review_query and not any(item.operation == "web_search" for item in actions):
        search_books_ids = [
            item.action_id for item in actions if item.operation == "search_books"
        ]
        insert_index = _first_index_before(actions, "search_books")
        actions.insert(
            insert_index,
            PlannedAction(
                capability="web",
                operation="web_search",
                arguments={
                    "query": review_query,
                    "max_results": 5,
                    "search_depth": "advanced",
                    "include_answer": True,
                },
                reason="The user requested external review/comment evidence before the final answer.",
                metadata={"compound_expansion": "external_review_lookup"},
            ),
        )
        added.append("web_search")
        if search_books_ids:
            web_action_id = actions[insert_index].action_id
            actions = [
                item.model_copy(
                    update={
                        "depends_on": [
                            dep for dep in [*item.depends_on, web_action_id] if dep
                        ]
                    }
                )
                if item.operation == "search_books" and not item.depends_on
                else item
                for item in actions
            ]

    book_query = _extract_book_recommendation_query(user_message)
    if book_query:
        rewritten: list[PlannedAction] = []
        for item in actions:
            if item.operation == "search_books":
                args = dict(item.arguments)
                args["query"] = book_query
                rewritten.append(
                    item.model_copy(
                        update={
                            "arguments": args,
                            "metadata": {
                                **item.metadata,
                                "query_rewritten_by": "compound_request_rule",
                            },
                        }
                    )
                )
                added.append("search_books_query_rewrite")
            else:
                rewritten.append(item)
        actions = rewritten

    if not added:
        return baseline

    return baseline.model_copy(
        update={
            "actions": actions,
            "complexity": "medium" if baseline.complexity == "low" else baseline.complexity,
            "metadata": {
                **baseline.metadata,
                "compound_expansions": added,
            },
        }
    )


def _first_index_before(actions: list[PlannedAction], operation: str) -> int:
    for index, item in enumerate(actions):
        if item.operation == operation:
            return index
    return len(actions)


def _extract_compound_memory_raw_text(user_message: str) -> str:
    text = " ".join(str(user_message or "").split()).strip()
    if not text:
        return ""
    separators = r"(?:，|。|；|,|;|然后|再|顺便|同时|并且|接着)"
    match = re.search(
        rf"(?:先)?(?:请你|请|帮我|替我)?(?:记住|记一下|记下|保存|存一下|note|remember)\s*(?P<raw>.+?)(?={separators}|$)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    raw = str(match.group("raw") or "").strip(" ，,。.;；")
    if not raw:
        return ""
    from app.services.memory.user_state import decide_user_state_capture

    decision = decide_user_state_capture(raw)
    return raw if decision.should_capture else ""


def _extract_external_review_query(user_message: str) -> str:
    text = " ".join(str(user_message or "").split()).strip()
    if not text:
        return ""
    match = re.search(
        r"(?:查一下|查询|搜索|搜一下|看看|看一下)(?P<query>.+?)(?=，|。|；|,|;|然后|再|顺便|同时|并且|接着|$)",
        text,
        re.IGNORECASE,
    )
    clause = str(match.group("query") if match else "").strip(" ，,。.;；")
    if not clause:
        if not re.search(r"(豆瓣|评论|评价|口碑|书评|review|reviews)", text, re.IGNORECASE):
            return ""
        clause = text
    if not re.search(r"(豆瓣|评论|评价|口碑|书评|review|reviews)", clause, re.IGNORECASE):
        return ""
    title = _extract_review_subject(clause) or _extract_review_subject(text)
    if title:
        return f"{title} 豆瓣 书评 评论 评价"
    return clause


def _extract_review_subject(text: str) -> str:
    explicit = re.search(
        r"(?:豆瓣)?(?:关于|有关)(?P<title>[^，。,.；;]+?)(?:的)?(?:评论|评价|口碑|书评|reviews?)",
        text,
        re.IGNORECASE,
    )
    if explicit:
        return str(explicit.group("title") or "").strip()
    match = re.search(
        r"(?:关于|有关)?(?P<title>[^，。,.；;]+?)(?:的)?(?:豆瓣)?(?:评论|评价|口碑|书评|reviews?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    title = str(match.group("title") or "").strip()
    title = re.sub(
        r"^(?:然后|再|顺便|同时|并且|接着)?(?:查一下|查询|搜索|搜一下|看看|看一下)?(?:豆瓣)?(?:关于|有关)?",
        "",
        title,
    ).strip()
    return title


def _extract_book_recommendation_query(user_message: str) -> str:
    text = " ".join(str(user_message or "").split()).strip()
    if not re.search(r"(推荐|书籍|书单|类似|similar|recommend)", text, re.IGNORECASE):
        return ""
    title = _extract_review_subject(text)
    if title and re.search(r"(类似|同类|相似|similar)", text, re.IGNORECASE):
        return f"{title} 类似书籍 推荐"
    match = re.search(
        r"(?:推荐|找|给我)(?:几本|一些|点)?(?:类似|像)?(?P<topic>[^，。,.；;]+?)(?:的)?(?:书籍|书|作品|读物)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    topic = str(match.group("topic") or "").strip()
    topic = re.sub(r"^(?:类似|像)", "", topic).strip()
    return f"{topic} 书籍 推荐" if topic else ""


def _business_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(arguments or {}).items()
        if key not in SYSTEM_ARGUMENT_FIELDS
    }


def _route_confidence(route: TurnExecutionPlan) -> float:
    return max((item.confidence for item in route.intent_candidates), default=0.7)


def _looks_like_potential_personal_state_query(user_message: str) -> bool:
    text = " ".join(str(user_message or "").split()).strip()
    if not text or not _POTENTIAL_PERSONAL_STATE_QUERY_RE.search(text):
        return False
    return any(marker in text for marker in ("?", "\uff1f")) or bool(
        re.search(r"\b(?:what|when|where|which|how many|remember)\b", text, re.I)
    )


def _looks_like_potential_external_fact_query(user_message: str) -> bool:
    text = " ".join(str(user_message or "").split()).strip()
    if not text or _STABLE_EXPLANATION_RE.search(text):
        return False
    if any(token in text for token in ("\u6211", "\u6211\u7684", "\u6211\u4eec")) or re.search(
        r"\b(?:i|my|me)\b",
        text,
        re.I,
    ):
        return False
    if text.rstrip(" ?\uff1f.!\u3002").lower() in {"\u4f60\u662f\u8c01", "who are you"}:
        return False
    return bool(_POTENTIAL_EXTERNAL_FACT_QUERY_RE.search(text))


def _capability_for_operation(operation: str) -> str:
    if "memory" in operation or operation == "capture_user_state":
        return "memory"
    if "book" in operation or "recommendation" in operation:
        return "book"
    if "research" in operation or operation in {
        "add_evidence",
        "collect_research_sources",
        "fetch_research_source",
        "analyze_research_data",
    }:
        return "research"
    if operation == "web_search":
        return "web"
    return "runtime"


def _operation_allowed_by_policy(operation: str, policy: TurnPolicy) -> bool:
    if operation in {"search_memory", "capture_user_state"}:
        return True
    flag = {
        "remember_memory": "can_write_memory",
        "revise_memory": "can_manage_memory",
        "forget_memory": "can_manage_memory",
        "web_search": "can_use_web_search",
        "search_books": "can_search_books",
        "get_recommendation_history": "can_view_recommendation_history",
        "remember_reading_preference": "can_write_memory",
        "record_book_feedback": "can_write_memory",
        "record_recommendation_signal": "can_record_recommendation_signal",
        "start_research": "can_start_research",
    }.get(operation)
    if flag is not None:
        return bool(getattr(policy, flag))
    if "research" in operation or operation in {
        "add_evidence",
        "collect_research_sources",
        "fetch_research_source",
        "analyze_research_data",
    }:
        return bool(policy.can_use_research_tools)
    return True


async def _resolve_planner_model(model_name: str) -> tuple[Any | None, str]:
    try:
        from app.infra.llm import get_llm, get_system_llm
        from app.infra.llm.manager import get_model_manager

        if model_name:
            try:
                return get_llm(model_name, thinking_mode=False), f"runtime:{model_name}"
            except Exception:
                pass
        manager = get_model_manager()
        if not getattr(manager, "_initialized", False):
            try:
                await manager.refresh()
            except Exception:
                pass
        model_id = manager.default_llm_id or manager.get_first_active_llm_id()
        if model_id:
            try:
                return get_llm(model_id, thinking_mode=False), f"runtime:{model_id}"
            except Exception:
                pass
        return get_system_llm(), "system"
    except Exception as exc:
        return None, f"unavailable:{exc}"


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text") or item.get("content") or "")
            if isinstance(item, dict)
            else str(item or "")
            for item in content
        )
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
            raise ValueError("planner did not return JSON")
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("planner returned a non-object payload")
    return payload
