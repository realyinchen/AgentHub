from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.chat import UserInput
from app.services.memory import (
    MemoryAdmissionResult,
    MemoryCandidate,
    MemoryEntityFact,
    get_memory_orchestrator,
)
from app.services.memory.contracts import normalize_memory_token


_NAME_VALUE = r"[\w\u4e00-\u9fff\u00b7\.\-]{1,32}"
_PROFILE_VALUE = r"[^。！？!?,，；;\n\r]{1,80}"
_NAME_PATTERNS = [
    re.compile(
        rf"^\s*\u6211\u662f(?P<name>{_NAME_VALUE})\s*(?:[.!?\u3002\uff01\uff1f])?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:\u6211\u53eb|\u6211\u7684\u540d\u5b57(?:\u53eb|\u662f))(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\u53eb\u6211(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\u6211\u662f(?P<name>{_NAME_VALUE})(?:\s|,|\uff0c)*"
        rf"(?:\u4f60)?(?:\u8bb0\u4f4f|\u8bb0\u4e00\u4e0b|\u8bb0\u4e0b)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:remember\s+(?:that\s+)?)?my\s+name\s+is\s+(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"call\s+me\s+(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
]
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
_TRAILING_NAME_NOISE = re.compile(
    r"(?:\u4f60)?(?:\u8bb0\u4f4f|\u8bb0\u4e00\u4e0b|\u8bb0\u4e0b)$|\u4f60$",
    re.IGNORECASE,
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
    """Persist low-ambiguity user profile facts before the model runs.

    The agent may still call memory tools, but explicit profile facts such as
    "my name is ..." are app-owned enough that they should not depend on model
    discretion. MemoryAdmission and ConflictResolver still decide persistence.
    """

    candidates = extract_explicit_profile_memory_candidates(user_input)
    if not candidates:
        return ProfileMemoryCaptureResult(reason="no_explicit_profile_fact")

    captured: list[dict[str, Any]] = []
    for candidate in candidates:
        result = await get_memory_orchestrator().remember_candidate(candidate)
        captured.append(_capture_item(candidate, result))

    return ProfileMemoryCaptureResult(
        status="completed",
        captured_count=sum(1 for item in captured if item.get("memory") is not None),
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


def _extract_name(text: str) -> str:
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        name = str(match.group("name") or "").strip()
        name = _TRAILING_NAME_NOISE.sub("", name).strip()
        name = name.strip(" \t\r\n,.;:!?，。！？；：\"'“”‘’（）()[]{}")
        if _valid_name(name):
            return name
    return ""


def _valid_name(name: str) -> bool:
    if not name or len(name) > 32:
        return False
    broad = {
        "user",
        "me",
        "myself",
        "what",
        "who",
        "\u6211",
        "\u7528\u6237",
        "\u4e00\u4e2a\u4eba",
        "\u4e00\u4e2a",
        "\u4e00\u540d",
        "\u5b66\u751f",
        "\u8001\u5e08",
        "\u533b\u751f",
        "\u7a0b\u5e8f\u5458",
        "\u5de5\u7a0b\u5e08",
        "\u8bfb\u8005",
        "\u4f5c\u8005",
        "\u4ec0\u4e48",
        "\u5565",
        "\u8c01",
    }
    lowered = name.lower()
    if lowered.startswith(("\u4e00\u4e2a", "\u4e00\u540d")):
        return False
    return lowered not in broad


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
    return text.strip(" \t\r\n,.;:!?锛屻€傦紒锛燂紱锛歕\"'鈥溾€濃€樷€欙紙锛?)[]{}")


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
        state_key = profile_key or (
            f"relation.{entity_fact.get('relation') or 'related_to'}."
            f"{entity_fact.get('entity_type') or 'entity'}."
            f"{entity_fact.get('name') or 'unknown'}"
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
        state_key = f"profile.{profile_key}"
        state_value = {"value": candidate.value}
        relation = {}
        use_when = ["用户询问自己的习惯或画像", "个性化回答与规划"]
    else:
        category = "preference"
        state_key = (
            f"preference.{candidate.subject}."
            f"{normalize_memory_token(candidate.value)[:80]}"
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


def _capture_item(
    candidate: MemoryCandidate,
    result: MemoryAdmissionResult,
) -> dict[str, Any]:
    return {
        "candidate": candidate.model_dump(mode="json"),
        "decision": result.decision.model_dump(mode="json"),
        "memory": result.memory.model_dump(mode="json") if result.memory else None,
        "conflicts": [
            conflict.model_dump(mode="json") for conflict in result.conflicts
        ],
        "provider_sources": result.provider_sources,
    }
