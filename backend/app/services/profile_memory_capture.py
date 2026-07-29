from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.chat import UserInput
from app.services.memory import MemoryCandidate, MemoryEntityFact
from app.services.memory.schema_registry import canonical_state_key
from app.services.memory.identity import (
    extract_declared_name,
    is_valid_person_name,
)


_NAME_VALUE = r"[\w\u4e00-\u9fff\u00b7\.\-]{1,32}"
_PROFILE_VALUE = r"[^。！？!?,，；;\n\r]{1,80}"
_PROFILE_PREFERENCE_PATTERNS = [
    (
        re.compile(
            rf"\u6211(?:\u5f88|\u975e\u5e38|\u6700)?\u559c\u6b22(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "tag",
        "like",
        "explicit_like",
    ),
    (
        re.compile(
            rf"\u6211(?:\u4e0d\u559c\u6b22|\u8ba8\u538c|\u4e0d\u7231\u770b)(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "tag",
        "dislike",
        "explicit_dislike",
    ),
    (
        re.compile(
            rf"(?:\u6211)?\u907f\u514d(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "content",
        "avoid",
        "explicit_avoid",
    ),
    (
        re.compile(
            rf"(?:\u522b|\u4e0d\u8981|\u4e0d\u60f3)(?:\u592a)?(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "content",
        "avoid",
        "explicit_avoid",
    ),
    (
        re.compile(
            rf"\u6211(?:\u60f3\u770b|\u60f3\u8bfb)(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "content",
        "want",
        "explicit_want_to_read",
    ),
    (
        re.compile(
            rf"\bi\s+(?:like|love|prefer)\s+(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "tag",
        "like",
        "explicit_like",
    ),
    (
        re.compile(
            rf"\bi\s+(?:dislike|hate|avoid)\s+(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "tag",
        "dislike",
        "explicit_dislike",
    ),
]
_PROFILE_USER_FACT_PATTERNS = [
    (
        re.compile(
            rf"\u6211(?:\u901a\u5e38|\u4e00\u822c|\u7ecf\u5e38|\u6bcf\u5929|\u957f\u671f|\u4e00\u76f4)(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "habit",
    ),
    (
        re.compile(
            rf"\u6211\u4e60\u60ef(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "habit",
    ),
    (
        re.compile(
            rf"\u6211\u7684(?:\u4f5c\u606f|\u4e60\u60ef|\u7231\u597d|\u5174\u8da3)(?:\u662f|\u5c31\u662f|:|：)?(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "profile_fact",
    ),
    (
        re.compile(
            rf"\bi\s+(?:usually|generally|often|always|tend to)\s+(?P<value>{_PROFILE_VALUE})",
            re.IGNORECASE,
        ),
        "habit",
    ),
]
_PET_FACT_RES = (
    re.compile(
        rf"\u6211(?:\u8fd8)?(?:\u6709|\u517b\u4e86|\u517b\u7740)(?:\u4e00\u53ea)?"
        rf"(?P<species>\u732b\u54aa|\u732b|\u72d7\u72d7|\u72d7)"
        rf"(?:\u53eb|\u540d\u5b57\u53eb)(?P<name>{_NAME_VALUE})"
        rf"(?:\s*[,\uff0c]?\s*\u662f(?:\u4e00\u53ea)?"
        rf"(?P<descriptor>[^\u3002\uff01\uff1f!?\n\r]{{1,40}}))?",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\u6211(?:\u8fd8)?(?:\u6709|\u517b\u4e86|\u517b\u7740)(?:\u4e00\u53ea)?"
        rf"(?:\u53eb|\u540d\u5b57\u53eb)"
        rf"(?P<name>[\w\u4e00-\u9fff\u00b7\.\-]{{1,16}}?)(?:\u7684)?"
        rf"(?P<species>\u732b\u54aa|\u732b|\u72d7\u72d7|\u72d7)"
        rf"(?:\s*[,\uff0c]?\s*\u662f(?:\u4e00\u53ea)?"
        rf"(?P<descriptor>[^\u3002\uff01\uff1f!?\n\r]{{1,40}}))?",
        re.IGNORECASE,
    ),
)
_PROFILE_LOOKUP_QUESTION_RE = re.compile(
    "|".join(
        f"(?:{pattern})"
        for pattern in (
            r"\u6211\u53eb\u4ec0\u4e48(?:\u540d\u5b57)?",
            r"\u6211\u7684\u540d\u5b57(?:\u662f|\u53eb)?\u4ec0\u4e48",
            r"\u6211\u662f\u8c01",
            r"\u6211\u559c\u6b22\u4ec0\u4e48",
            r"\u6211\u4e0d\u559c\u6b22\u4ec0\u4e48",
            r"\u6211\u7684(?:\u4f5c\u606f|\u4e60\u60ef|\u7231\u597d|\u5174\u8da3)\u662f\u4ec0\u4e48",
            r"\u6211\u7684(?:\u732b|\u732b\u54aa|\u72d7|\u72d7\u72d7|\u5ba0\u7269)(?:\u662f|\u53eb|\u6709)?\u4ec0\u4e48",
            r"\u6211\u7684(?:\u732b|\u732b\u54aa|\u72d7|\u72d7\u72d7|\u5ba0\u7269)(?:\u53eb\u4ec0\u4e48|\u662f\u4ec0\u4e48)",
            r"\bwhat(?:'s| is)\s+my\s+name\b",
            r"\bwho\s+am\s+i\b",
            r"\bwhat\s+do\s+i\s+(?:like|prefer|dislike|hate)\b",
        )
    ),
    re.IGNORECASE,
)
_NON_ASSERTIVE_QUESTION_RE = re.compile(
    r"(?:[?\uff1f]|\u600e\u4e48|\u5982\u4f55|\u4f1a\u4e0d\u4f1a|\u80fd\u4e0d\u80fd|\u662f\u4e0d\u662f)",
    re.IGNORECASE,
)
_TRAILING_PROFILE_NOISE = re.compile(
    r"(?:\u8fd9\u79cd|\u8fd9\u7c7b|\u4e4b\u7c7b|\u8fd9\u6837\u7684?)$",
    re.IGNORECASE,
)


class ProfileMemoryCaptureResult(BaseModel):
    status: str = "skipped"
    captured_count: int = 0
    reason: str = ""
    memories: list[dict[str, Any]] = Field(default_factory=list)


async def capture_explicit_profile_memories(
    user_input: UserInput,
) -> ProfileMemoryCaptureResult:
    """Compatibility adapter into the canonical pre-commit write pipeline."""

    from app.services.conversation.contracts import ConversationWindow
    from app.services.memory.write_contracts import MemoryWriteRequest
    from app.services.memory.write_coordinator import MemoryWriteCoordinator

    if not extract_explicit_profile_memory_candidates(user_input):
        return ProfileMemoryCaptureResult(reason="no_explicit_profile_fact")
    explicit = bool(
        re.search(r"记住|记一下|记下来|保存|\bremember\b", user_input.content, re.I)
    )
    outcome = await MemoryWriteCoordinator().process(
        MemoryWriteRequest(
            utterance=user_input.content,
            target_expression=user_input.content,
            explicit=explicit,
            conversation_context_required=False,
            semantic_fallback_allowed=False,
        ),
        user_input=user_input,
        conversation=ConversationWindow(),
        user_id=user_input.user_id,
        thread_id=user_input.thread_id,
    )
    captured = [
        {
            "memory": memory,
            "decision": {
                "decision": (
                    "allow"
                    if outcome.status == "committed"
                    else "skip_duplicate"
                )
            },
        }
        for memory in outcome.memories
    ]
    return ProfileMemoryCaptureResult(
        status=outcome.status,
        captured_count=(
            len(outcome.memories) if outcome.status == "committed" else 0
        ),
        reason=",".join(outcome.reason_codes),
        memories=captured,
    )


def extract_explicit_profile_memory_candidates(
    user_input: UserInput,
) -> list[MemoryCandidate]:
    text = " ".join(str(user_input.content or "").split()).strip()
    if not text:
        return []
    if _PROFILE_LOOKUP_QUESTION_RE.search(text):
        return []
    if _NON_ASSERTIVE_QUESTION_RE.search(text) and not re.search(
        r"\u8bb0\u4f4f|\u8bb0\u4e00\u4e0b|\bremember\b",
        text,
        re.IGNORECASE,
    ):
        return []

    candidates: list[MemoryCandidate] = []
    name = _extract_name(text)
    if name:
        candidates.append(
            MemoryCandidate(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                type="preference",
                subject="user",
                value=f"name: {name}",
                polarity="neutral",
                confidence=1.0,
                scope="long_term_memory",
                source_text=text,
                source_kind="user_message",
                metadata={
                    "profile_key": "name",
                    "capture_source": "deterministic_profile_memory",
                    "explicit_restore": True,
                },
            )
        )
    candidates.extend(_extract_entity_candidates(user_input, text))
    candidates.extend(_extract_preference_candidates(user_input, text))
    candidates.extend(_extract_user_fact_candidates(user_input, text))
    return _dedupe_candidates(
        [_with_user_state_metadata(candidate, raw_text=text) for candidate in candidates]
    )


def has_explicit_profile_memory_statement(text: str) -> bool:
    """Return whether text contains a deterministic profile fact, without IDs."""

    normalized = " ".join(str(text or "").split()).strip()
    if not normalized or _PROFILE_LOOKUP_QUESTION_RE.search(normalized):
        return False
    if _extract_name(normalized):
        return True
    if any(pattern.search(normalized) for pattern in _PET_FACT_RES):
        return True
    if any(pattern.search(normalized) for pattern, *_ in _PROFILE_PREFERENCE_PATTERNS):
        return True
    return any(pattern.search(normalized) for pattern, *_ in _PROFILE_USER_FACT_PATTERNS)


def _extract_name(text: str) -> str:
    return extract_declared_name(text)


def _valid_name(name: str) -> bool:
    return is_valid_person_name(name)


def _extract_preference_candidates(
    user_input: UserInput,
    text: str,
) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    for pattern, subject, polarity, source in _PROFILE_PREFERENCE_PATTERNS:
        for match in pattern.finditer(text):
            value = _clean_profile_value(match.group("value"))
            if not _valid_profile_value(value):
                continue
            candidates.append(
                MemoryCandidate(
                    user_id=user_input.user_id,
                    thread_id=user_input.thread_id,
                    type="preference",
                    subject=subject,
                    value=value,
                    polarity=polarity,
                    confidence=0.95,
                    scope="long_term_memory",
                    source_text=text,
                    source_kind="user_message",
                    metadata={
                        "profile_key": "preference",
                        "capture_source": "deterministic_profile_memory",
                        "capture_pattern": source,
                    },
                )
            )
    return candidates


def _extract_entity_candidates(
    user_input: UserInput,
    text: str,
) -> list[MemoryCandidate]:
    match = None
    for pattern in _PET_FACT_RES:
        match = pattern.search(text)
        if match:
            break
    if not match:
        return []

    name = str(match.group("name") or "").strip()
    if not _valid_name(name):
        return []

    species_text = str(match.group("species") or "")
    species = "cat" if "\u732b" in species_text else "dog"
    descriptor = str(match.group("descriptor") or "").strip()
    attributes: dict[str, str] = {"species": species}

    pattern_map = {
        "\u4e09\u82b1": "calico",
        "\u9ec4": "yellow",
        "\u6a58": "orange",
        "\u864e\u6591": "tabby",
        "\u9ed1\u767d": "black_and_white",
        "\u767d": "white",
        "\u9ed1": "black",
        "\u7070": "gray",
    }
    for marker, value in pattern_map.items():
        if marker in descriptor:
            attributes["pattern"] = value
            attributes["pattern_label"] = "\u9ec4\u8272" if marker == "\u9ec4" else marker
            break

    breed_map = {
        "\u519c\u6751\u571f\u72d7": "village_dog",
        "\u4e2d\u534e\u7530\u56ed\u72ac": "chinese_rural_dog",
        "\u571f\u72d7": "village_dog",
    }
    for marker, value in breed_map.items():
        if marker in descriptor:
            attributes["breed"] = value
            attributes["breed_label"] = marker
            break

    if "\u6bcd" in descriptor:
        attributes["gender"] = "female"
    elif "\u516c" in descriptor:
        attributes["gender"] = "male"

    fact = MemoryEntityFact(
        entity_type="pet",
        name=name,
        relation="owns",
        attributes=attributes,
    )
    species_label = "\u732b" if species == "cat" else "\u72d7"
    value_parts = [f"\u5ba0\u7269: {name}", f"\u7269\u79cd: {species_label}"]
    if pattern_label := attributes.get("pattern_label"):
        value_parts.append(f"\u82b1\u8272: {pattern_label}")
    if gender := attributes.get("gender"):
        gender_label = "\u6bcd" if gender == "female" else "\u516c"
        value_parts.append(f"\u6027\u522b: {gender_label}")
    if breed_label := attributes.get("breed_label"):
        value_parts.append(f"\u54c1\u79cd: {breed_label}")

    return [
        MemoryCandidate(
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
            type="entity",
            subject="pet",
            value="; ".join(value_parts),
            polarity="neutral",
            confidence=1.0,
            scope="long_term_memory",
            source_text=text,
            source_kind="user_message",
            metadata={
                "profile_key": f"entity:pet:{name.lower()}",
                "capture_source": "deterministic_entity_memory",
                "entity_fact": fact.model_dump(mode="json"),
            },
        )
    ]


def _extract_user_fact_candidates(
    user_input: UserInput,
    text: str,
) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    for pattern, fact_type in _PROFILE_USER_FACT_PATTERNS:
        for match in pattern.finditer(text):
            value = _clean_profile_value(match.group("value"))
            if not _valid_profile_value(value):
                continue
            candidates.append(
                MemoryCandidate(
                    user_id=user_input.user_id,
                    thread_id=user_input.thread_id,
                    type="preference",
                    subject="user",
                    value=f"{fact_type}: {value}",
                    polarity="neutral",
                    confidence=0.9,
                    scope="long_term_memory",
                    source_text=text,
                    source_kind="user_message",
                    metadata={
                        "profile_key": fact_type,
                        "capture_source": "deterministic_profile_memory",
                    },
                )
            )
    return candidates


def _clean_profile_value(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    text = re.split(r"(?:\u4f46\u662f|\u4f46|\u4e0d\u8fc7|\bbut\b)", text, maxsplit=1)[0].strip()
    text = _TRAILING_PROFILE_NOISE.sub("", text).strip()
    return text.strip(" \t\r\n,.;:!?，。！？；：\"'“”‘’（）()[]{}")


def _valid_profile_value(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    lowered = value.lower()
    invalid = {
        "\u4ec0\u4e48",
        "\u5565",
        "\u8c01",
        "\u8fd9\u4e2a",
        "\u8fd9\u4e9b",
        "\u8fd9\u672c",
        "\u8fd9\u672c\u4e66",
        "\u63a8\u8350",
        "\u641c\u7d22",
        "\u56de\u7b54",
        "what",
        "who",
        "this",
        "it",
        "recommend",
        "recommendation",
        "search",
        "answer",
    }
    return lowered not in invalid


def _with_user_state_metadata(
    candidate: MemoryCandidate,
    *,
    raw_text: str,
) -> MemoryCandidate:
    metadata = dict(candidate.metadata)
    profile_key = str(metadata.get("profile_key") or "")
    entity_fact = metadata.get("entity_fact")
    if isinstance(entity_fact, dict):
        category = "relation"
        state_key = canonical_state_key(
            "relation",
            str(entity_fact.get("relation") or "related_to"),
            str(entity_fact.get("entity_type") or "entity"),
            str(entity_fact.get("name") or "unknown"),
        )
        state_value = {
            "entity_type": entity_fact.get("entity_type"),
            "name": entity_fact.get("name"),
            "attributes": entity_fact.get("attributes") or {},
        }
        relation = {
            "subject": "user",
            "predicate": entity_fact.get("relation") or "related_to",
            "object": entity_fact.get("name") or "",
            "object_type": entity_fact.get("entity_type") or "entity",
        }
        use_when = [
            f"用户询问{entity_fact.get('name') or '相关实体'}",
            "用户询问自己的实体、物品、人物或关系",
        ]
    elif profile_key == "name":
        category = "profile"
        state_key = "profile.name"
        state_value = {"name": candidate.value.split(":", 1)[-1].strip()}
        relation = {}
        use_when = ["用户询问自己是谁", "用户询问自己的名字", "称呼用户"]
    elif profile_key in {"habit", "profile_fact"}:
        category = "profile"
        state_key = canonical_state_key("profile", profile_key)
        state_value = {"value": candidate.value}
        relation = {}
        use_when = ["用户询问自己的习惯或画像", "个性化回答与规划"]
    else:
        category = "preference"
        state_key = canonical_state_key(
            "preference",
            candidate.subject,
            candidate.value,
        )
        state_value = {
            "value": candidate.value,
            "polarity": candidate.polarity,
            "subject": candidate.subject,
        }
        relation = {}
        use_when = ["个性化推荐", "用户询问自己的偏好", "生成个性化约束"]

    metadata["user_state"] = {
        "status": "active",
        "category": category,
        "state_key": state_key,
        "summary": candidate.value,
        "raw_text": raw_text,
        "state_value": state_value,
        "relation": relation,
        "use_when": use_when,
        "valid_until": None,
        "confirmation_question": "",
        "organizer": "deterministic_fast_capture",
    }
    metadata["precommit"] = {
        "source_identified": True,
        "reference_resolved": True,
        "completeness_validated": True,
        "persistence_approved": True,
        "extraction_method": "deterministic",
        "source_kind": "current_user_assertion",
        "source_turn_offset": 0,
    }
    return candidate.model_copy(update={"metadata": metadata})


def _dedupe_candidates(candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
    result: list[MemoryCandidate] = []
    seen: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        key = (
            candidate.type,
            candidate.subject,
            candidate.value.strip().lower(),
            candidate.polarity,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result
