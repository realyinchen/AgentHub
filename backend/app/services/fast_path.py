from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.chat import UserInput
from app.services.books.feedback import extract_book_feedback
from app.services.memory import MemoryEvent
from app.services.memory.identity import resolve_current_name
from app.services.memory.user_state import decide_user_state_capture
from app.services.profile_memory_capture import (
    ProfileMemoryCaptureResult,
    has_explicit_profile_memory_statement,
)

FastPathIntent = Literal[
    "conversation_recall",
    "memory_write",
    "memory_lookup",
    "reading_feedback",
]

_MEMORY_NAME_LOOKUP_RE = re.compile(
    r"\u6211\u662f\u8c01|\u6211\u53eb\u4ec0\u4e48|\u6211\u7684\u540d\u5b57|\bwho\s+am\s+i\b|\bwhat(?:'s| is)\s+my\s+name\b",
    re.IGNORECASE,
)
_CONVERSATION_RECALL_RE = re.compile(
    r"(?:我刚才|我上面|我之前刚刚)(?:跟你)?(?:说|讲|问|告诉)(?:了)?什么|"
    r"(?:刚才|上面)(?:我们)?(?:说|聊)(?:了)?什么|"
    r"(?:你刚才|你上面)(?:说|回答)(?:了)?什么|"
    r"\bwhat did (?:i|you) (?:just )?say\b",
    re.IGNORECASE,
)
_MEMORY_PET_LOOKUP_RE = re.compile(
    r"\u6211\u7684(?:\u732b|\u732b\u54aa|\u72d7|\u72d7\u72d7|\u5ba0\u7269)(?:\u53eb\u4ec0\u4e48|\u662f\u4ec0\u4e48|\u662f\u4ec0\u4e48\u6837|\u662f\u4ec0\u4e48\u54c1\u79cd)?",
    re.IGNORECASE,
)
_MEMORY_PET_COUNT_RE = re.compile(
    r"(?:我有(?:多少|几)只宠物|我有(?:什么|哪些)宠物|我(?:都)?有哪些宠物|我的宠物有(?:多少|几)只|"
    r"\bhow\s+many\s+pets?\s+do\s+i\s+have\b|\bwhat\s+pets?\s+do\s+i\s+have\b)"
    r"(?:吗|呢)?",
    re.IGNORECASE,
)
_AMBIGUOUS_MEMORY_REFERENCE_RE = re.compile(
    r"(?:记住|记一下|记下来|别忘了)(?:这个|那个|这件事|那件事|它|他|她)(?:吧|啊|呀)?$|"
    r"\bremember\s+(?:this|that|it|him|her)\b",
    re.IGNORECASE,
)
_GENERIC_MEMORY_LOOKUP_RES = (
    re.compile(
        r"(?:查一下|查询|看看|看一下)?我的(?P<topic>记忆|用户画像|偏好|喜好|习惯|状态|资料|信息)(?:吗|呢)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:查一下|查询|看看|看一下)(?:我|我的)(?P<topic>.+?)(?:吗|呢)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:你还?记得|还?记得)(?:关于)?我的(?P<topic>.+?)(?:吗|是什么|叫什么|有哪些|怎么样|在哪(?:里)?|放在哪(?:里)?)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"我的(?P<topic>.+?)(?:是什么|叫什么|有哪些|怎么样|在哪(?:里)?|放在哪(?:里)?|你记得吗)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:我之前让你记住了什么|你记得我的什么|你记得我什么|你记得关于我的哪些事)",
        re.IGNORECASE,
    ),
)
_RECOMMENDATION_HISTORY_QUERY_RE = re.compile(
    r"(?:\u5df2\u8bfb|\u9605\u8bfb\u5386\u53f2|\u8bfb\u8fc7|\u770b\u8fc7|\u62d2\u7edd\u8bb0\u5f55|"
    r"\u4e0d\u611f\u5174\u8da3|\u4e3a\u4ec0\u4e48.*\u6ca1.*\u63a8\u8350|\u6291\u5236\u8bb0\u5f55|"
    r"\breading\s+history\b|\brejected\s+books?\b|\bwhy.*not.*recommend)",
    re.IGNORECASE,
)
_SLOW_PATH_MARKER_RE = re.compile(
    r"deep\s+(?:search|research)|\u6df1\u5ea6(?:\u641c\u7d22|\u7814\u7a76)|\u7814\u7a76|\u62a5\u544a|\u63a8\u8350|\u641c\u7d22|\u67e5\u4e00\u4e0b|\u5929\u6c14|\u987a\u4fbf|\u540c\u65f6|\u7136\u540e|\u53e6\u5916|\banaly[sz]e\b|\bcompare\b|\brecommend\b|\bsearch\b",
    re.IGNORECASE,
)


class FastPathDecision(BaseModel):
    route_type: str = "slow_path"
    handled: bool = False
    intent: FastPathIntent | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def decide_fast_path(user_input: UserInput) -> FastPathDecision:
    return decide_fast_path_text(user_input.content)


def decide_fast_path_text(content: str) -> FastPathDecision:
    """Classify a text-only fast path without accepting system identity."""

    text = " ".join(str(content or "").split()).strip()
    if not text:
        return FastPathDecision(reason="empty_input")

    normalized_lookup = text.rstrip(" ?\uff1f.!\u3002")
    if _CONVERSATION_RECALL_RE.fullmatch(normalized_lookup):
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="conversation_recall",
            confidence=0.99,
            reason="deterministic_conversation_recall",
            metadata={"recall_scope": "current_thread"},
        )
    if _MEMORY_NAME_LOOKUP_RE.fullmatch(normalized_lookup):
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="memory_lookup",
            confidence=0.99,
            reason="deterministic_name_lookup",
            metadata={"lookup_kind": "name"},
        )
    if _MEMORY_PET_COUNT_RE.fullmatch(normalized_lookup):
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="memory_lookup",
            confidence=0.99,
            reason="deterministic_pet_count_lookup",
            metadata={"lookup_kind": "pet_count"},
        )
    if _MEMORY_PET_LOOKUP_RE.fullmatch(normalized_lookup):
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="memory_lookup",
            confidence=0.98,
            reason="deterministic_pet_lookup",
            metadata={"lookup_kind": "pet"},
        )

    generic_lookup = (
        None
        if _RECOMMENDATION_HISTORY_QUERY_RE.search(normalized_lookup)
        else _generic_memory_lookup(normalized_lookup)
    )
    if generic_lookup is not None:
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="memory_lookup",
            confidence=0.94,
            reason="generic_user_state_lookup",
            metadata={"lookup_kind": "generic", "query": generic_lookup},
        )

    feedback = extract_book_feedback(text)
    if feedback and not _SLOW_PATH_MARKER_RE.search(text):
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="reading_feedback",
            confidence=0.96,
            reason="deterministic_concrete_book_feedback",
            metadata={"feedback": feedback},
        )

    has_profile_statement = has_explicit_profile_memory_statement(text)
    if (
        has_profile_statement
        and len(text) <= 180
        and not _SLOW_PATH_MARKER_RE.search(text)
        and not any(marker in text for marker in ("?", "\uff1f"))
    ):
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="memory_write",
            confidence=0.98,
            reason="deterministic_standalone_memory_statement",
            metadata={"candidate_count": 1},
        )

    user_state = decide_user_state_capture(text)
    if (
        user_state.should_capture
        and len(text) <= 600
        and not _SLOW_PATH_MARKER_RE.search(text)
    ):
        return FastPathDecision(
            route_type="fast_path",
            handled=True,
            intent="memory_write",
            confidence=0.99 if user_state.explicit else 0.93,
            reason=(
                "generic_explicit_memory_request"
                if user_state.explicit
                else "generic_standalone_user_state"
            ),
            metadata={
                "generic_user_state": True,
                "explicit": user_state.explicit,
            },
        )

    return FastPathDecision(reason="requires_agent_runtime")


def _memory_write_response(capture: ProfileMemoryCaptureResult) -> str:
    admitted = [item for item in capture.memories if item.get("memory")]
    if not admitted:
        return "\u8fd9\u6761\u4fe1\u606f\u6ca1\u6709\u901a\u8fc7\u957f\u671f\u8bb0\u5fc6\u51c6\u5165\uff0c\u6211\u6ca1\u6709\u628a\u5b83\u5f53\u4f5c\u5df2\u8bb0\u4f4f\u7684\u4e8b\u5b9e\u3002"
    candidates = [item.get("candidate") or {} for item in admitted]
    name = next(
        (
            str(item.get("value") or "").split(":", 1)[-1].strip()
            for item in candidates
            if (item.get("metadata") or {}).get("profile_key") == "name"
        ),
        "",
    )
    if name:
        return f"\u597d\u7684\uff0c\u6211\u8bb0\u4f4f\u4e86\uff0c\u4f60\u53eb{name}\u3002"
    entity = next(
        (
            (item.get("metadata") or {}).get("entity_fact")
            for item in candidates
            if (item.get("metadata") or {}).get("entity_fact")
        ),
        None,
    )
    if isinstance(entity, dict):
        return f"\u597d\u7684\uff0c\u6211\u8bb0\u4f4f\u4e86\u3002{_render_pet_fact(entity)}"
    return "\u597d\u7684\uff0c\u6211\u5df2\u7ecf\u628a\u8fd9\u6761\u7a33\u5b9a\u7684\u7528\u6237\u504f\u597d\u8bb0\u4f4f\u4e86\u3002"


def _memory_lookup_response(memories: list[MemoryEvent], *, lookup_kind: str) -> str:
    if lookup_kind == "name":
        resolved_name = resolve_current_name(memories)
        if resolved_name:
            return f"\u4f60\u53eb{resolved_name}\u3002"
        for memory in memories:
            if memory.metadata.get("profile_key") != "name":
                continue
            name = memory.value.split(":", 1)[-1].strip()
            if name:
                return f"\u4f60\u53eb{name}\u3002"
        return "\u6211\u8fd8\u6ca1\u6709\u8bb0\u5f55\u4f60\u7684\u540d\u5b57\u3002"

    if lookup_kind == "pet":
        pet_facts = _collect_pet_facts(memories)
        if pet_facts:
            return _render_pet_fact(pet_facts[0])
        return "\u6211\u8fd8\u6ca1\u6709\u8bb0\u5f55\u4f60\u7684\u5ba0\u7269\u4fe1\u606f\u3002"

    if lookup_kind == "pet_count":
        pet_facts = _collect_pet_facts(memories)
        if not pet_facts:
            return "我还没有记录你的宠物信息。"
        rendered = "；".join(_render_pet_fact(fact).rstrip("。") for fact in pet_facts)
        return f"你有{len(pet_facts)}只宠物：{rendered}。"

    if not memories:
        return "我还没有找到与你这次询问相关的用户状态记录。"
    lines = ["我记得你说过："]
    for memory in memories[:8]:
        source = memory.raw_text or memory.value
        lines.append(f"- {source}")
    return "\n".join(lines)


def _generic_memory_lookup(text: str) -> str | None:
    for pattern in _GENERIC_MEMORY_LOOKUP_RES:
        match = pattern.fullmatch(text)
        if not match:
            continue
        topic = str(match.groupdict().get("topic") or "").strip(" ，,。.!?？")
        return topic
    return None


def _immediate_memory_clarification(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if _AMBIGUOUS_MEMORY_REFERENCE_RE.search(normalized):
        return "你说的“这个/那个”具体指什么？"
    return ""


def _collect_pet_facts(memories: list[MemoryEvent]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for memory in memories:
        fact = memory.metadata.get("entity_fact")
        if not (
            memory.type == "entity"
            and memory.subject == "pet"
            and isinstance(fact, dict)
        ):
            relation = memory.relation if isinstance(memory.relation, dict) else {}
            object_type = str(relation.get("object_type") or "").lower()
            if object_type not in {"pet", "cat", "dog", "宠物", "猫", "狗"}:
                continue
            state_value = memory.state_value if isinstance(memory.state_value, dict) else {}
            name = str(relation.get("object") or state_value.get("name") or "").strip()
            if not name:
                continue
            fact = {
                "name": name,
                "entity_type": "pet",
                "relation": str(relation.get("predicate") or "owns"),
                "attributes": state_value.get("attributes") or {},
            }
        name = str(fact.get("name") or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        facts.append(fact)
    return facts


def _render_pet_fact(fact: dict[str, Any]) -> str:
    name = str(fact.get("name") or "")
    attributes = fact.get("attributes") or {}
    species = "\u732b\u54aa" if attributes.get("species") == "cat" else "\u72d7\u72d7"
    details: list[str] = []
    pattern = attributes.get("pattern_label")
    if pattern:
        details.append(str(pattern))
    breed = attributes.get("breed_label")
    if breed:
        details.append(str(breed))
    gender = attributes.get("gender")
    if gender == "female":
        details.append("\u6bcd")
    elif gender == "male":
        details.append("\u516c")
    descriptor = "".join(details)
    species_noun = "\u732b" if attributes.get("species") == "cat" else "\u72d7"
    if descriptor:
        noun = "" if descriptor.endswith(("\u732b", "\u72d7", "\u72ac")) else species_noun
        return f"\u4f60\u7684{species}\u53eb{name}\uff0c\u662f\u4e00\u53ea{descriptor}{noun}\u3002"
    return f"\u4f60\u7684{species}\u53eb{name}\u3002"


def _reading_feedback_response(payload: dict[str, Any]) -> str:
    if str(payload.get("status") or "").lower() in {"tool_blocked", "failed"}:
        return "\u8fd9\u6761\u9605\u8bfb\u53cd\u9988\u6ca1\u6709\u6210\u529f\u4fdd\u5b58\u3002"
    title = str(
        payload.get("book_title")
        or _nested_value(payload, ("interaction", "book_title"))
        or _nested_value(payload, ("memory", "value"))
        or "\u8fd9\u672c\u4e66"
    )
    return f"\u597d\u7684\uff0c\u5df2\u8bb0\u5f55\u4f60\u5bf9\u300a{title}\u300b\u7684\u9605\u8bfb\u53cd\u9988\u3002"


def _memory_admission_summary(
    capture: ProfileMemoryCaptureResult,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in capture.memories:
        candidate = item.get("candidate") or {}
        decision = item.get("decision") or {}
        memory = item.get("memory") or {}
        result.append(
            {
                "type": candidate.get("type"),
                "subject": candidate.get("subject"),
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "memory_id": memory.get("id"),
            }
        )
    return result


def _nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
