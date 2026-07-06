"""App-owned turn intent and action policy contract.

The assistant may propose actions, but tools are admitted by this contract. The
contract is deliberately small and deterministic for now; model-assisted intent
classification can be added later only if it maps into these fields.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


TURN_INTENT_TYPES = frozenset(
    {
        "answer_question",
        "update_memory",
        "recommend_books",
        "deep_search",
        "research_report",
        "manage_memory",
    }
)

TURN_INTENT_SOURCES = frozenset({"deterministic_rules", "manual", "model_router"})

ACTION_FIELDS = (
    "can_answer_question",
    "can_write_memory",
    "can_manage_memory",
    "can_search_memory",
    "can_search_books",
    "can_recommend_books",
    "can_record_recommendation_signal",
    "can_start_research",
    "can_use_research_tools",
)


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _validate_token(field_name: str, value: Any, allowed: frozenset[str]) -> str:
    token = _normalize_token(value)
    if token not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {allowed_values}")
    return token


def _clean_string_list(values: list[Any] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values or []:
        text = _normalize_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


class TurnIntent(BaseModel):
    """Application-owned contract for one user turn's intent."""

    primary_intent: str = Field(
        description=(
            "One of answer_question, update_memory, recommend_books, deep_search, "
            "research_report, manage_memory."
        )
    )
    intents: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    explicit: bool = Field(
        default=True,
        description="Whether the action intent was explicitly requested by the user.",
    )
    source: str = Field(default="deterministic_rules")
    signals: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("primary_intent", mode="before")
    @classmethod
    def validate_primary_intent(cls, value: Any) -> str:
        return _validate_token("primary_intent", value, TURN_INTENT_TYPES)

    @field_validator("intents", mode="before")
    @classmethod
    def validate_intents(cls, value: Any) -> list[str]:
        intents = [_validate_token("intent", item, TURN_INTENT_TYPES) for item in value or []]
        return intents

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> str:
        return _validate_token("source", value, TURN_INTENT_SOURCES)

    @field_validator("signals", mode="before")
    @classmethod
    def clean_signals(cls, value: Any) -> list[str]:
        return _clean_string_list(value)


class TurnPolicy(BaseModel):
    """Application-owned contract for actions allowed in one user turn."""

    intent: TurnIntent
    can_answer_question: bool = True
    can_write_memory: bool = False
    can_manage_memory: bool = False
    can_search_memory: bool = False
    can_search_books: bool = False
    can_recommend_books: bool = False
    can_record_recommendation_signal: bool = False
    can_start_research: bool = False
    can_use_research_tools: bool = False
    max_book_search_calls: int = Field(default=0, ge=0, le=10)
    requires_verifier: bool = False
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    response_boundary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("allowed_tools", "denied_tools", mode="before")
    @classmethod
    def clean_tools(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("response_boundary", mode="before")
    @classmethod
    def clean_response_boundary(cls, value: Any) -> str:
        return _normalize_text(value)


_EXPLICIT_BOOK_SEARCH_PATTERNS = [
    "\u63a8\u8350",  # recommend
    "\u4e66\u5355",  # book list
    "\u627e(?:\u51e0\u672c|\u4e00\u4e9b|\u4e00\u672c|\u672c|\u70b9|\u4e9b)?.*\u4e66",
    "(?:\u6709\u54ea\u4e9b|\u6709\u4ec0\u4e48|\u6709\u6ca1\u6709|\u6709\u65e0|\u54ea\u4e9b).*\u4e66",
    "(?:\u7c7b\u4f3c|\u76f8\u4f3c|\u540c\u7c7b).*\u4e66",
    "\u4e66.*(?:\u7c7b\u4f3c|\u76f8\u4f3c|\u540c\u7c7b)",
    "(?:\u8bfb|\u770b)(?:\u4ec0\u4e48|\u54ea\u672c|\u54ea\u4e9b).*\u4e66",
    "\u9002\u5408.*\u4e66",
    "(?:\u8c46\u74e3|\u8bc4\u5206|\u6392\u884c|\u699c\u5355|\u5019\u9009\u4e66)",
    r"\brecommend(?:ation|ations)?\b",
    r"\bsuggest(?:ion|ions)?\b",
    r"\bbook\s+list\b",
    r"\bbooks?\s+(?:like|similar to)\b",
    r"\bsimilar\s+books?\b",
    r"\bwhat\s+should\s+i\s+read\b",
    r"\bfind\s+.*books?\b",
    r"\b(?:douban|rating|ratings|rankings?)\b",
]

_BLOCK_BOOK_SEARCH_PATTERNS = [
    "(?:\u4e0d\u8981|\u4e0d\u7528|\u522b|\u65e0\u9700|\u4e0d\u9700\u8981).*\u63a8\u8350",
    "(?:\u4e0d\u8981|\u4e0d\u7528|\u522b|\u65e0\u9700|\u4e0d\u9700\u8981).*\u627e\u4e66",
    "\u4e0d\u662f.*(?:\u63a8\u8350|\u627e\u4e66)",
    "\u53ea(?:\u8981|\u60f3|\u662f)?.*(?:\u89e3\u91ca|\u8bf4\u660e|\u56de\u7b54|\u5206\u6790|\u4e86\u89e3)",
    r"\b(?:do not|don't|no need to)\s+recommend\b",
    r"\bno\s+recommendations?\b",
    r"\bjust\s+(?:explain|describe|answer)\b",
    r"\bonly\s+(?:explain|describe|answer)\b",
]

_MEMORY_UPDATE_PATTERNS = [
    "\u6211\u559c\u6b22",  # I like
    "\u6211\u4e0d\u559c\u6b22",  # I dislike
    "\u4e0d\u7231\u770b",
    "\u559c\u6b22.*\u8fd9\u79cd",
    "\u4e0d\u8981.*\u8fd9\u79cd",
    "\u907f\u514d",
    "\u8ba8\u538c",
    "\u6211\u60f3\u770b",
    "\u6211\u770b\u8fc7",
    r"\bi\s+(?:like|love|prefer|dislike|hate|avoid)\b",
    r"\bi\s+(?:want to read|have read|already read)\b",
]

_MEMORY_MANAGE_PATTERNS = [
    "\u4f60\u8bb0\u4f4f\u4e86\u4ec0\u4e48",
    "\u4f60\u8bb0\u5f97\u4ec0\u4e48",
    "\u5f53\u524d\u8bb0\u5fc6",
    "\u5220\u9664.*\u8bb0\u5fc6",
    "\u5fd8\u8bb0.*\u8bb0\u5fc6",
    "\u4e0d\u8981\u518d\u8bb0",
    r"\bwhat do you remember\b",
    r"\bforget\b.*\bmemory\b",
    r"\bdelete\b.*\bmemory\b",
]

_RECOMMENDATION_SIGNAL_PATTERNS = [
    "\u7ee7\u7eed\u8bb2",
    "\u7ee7\u7eed\u8bf4",
    "\u8be6\u7ec6\u8bb2",
    "\u8bb2\u8bb2",
    "\u5c55\u5f00",
    "\u6211\u4e0d\u611f\u5174\u8da3",
    "\u4e0d\u611f\u5174\u8da3",
    "\u6ca1\u5174\u8da3",
    "\u6211\u770b\u8fc7",
    "\u6211\u8bfb\u8fc7",
    "\u5df2\u8bfb",
    "\u8bfb\u5b8c",
    "\u8fd9\u672c",
    r"\btell\s+me\s+more\b",
    r"\bcontinue\b",
    r"\bnot\s+interested\b",
    r"\balready\s+read\b",
    r"\bread\s+it\b",
]

_RESEARCH_PATTERNS = [
    "deep search",
    "deep research",
    "\u6df1\u5ea6\u641c\u7d22",
    "\u6df1\u5ea6\u7814\u7a76",
    "\u7814\u7a76\u62a5\u544a",
    "\u7cfb\u7edf\u8c03\u7814",
]

_RESEARCH_REPORT_PATTERNS = [
    "\u7814\u7a76\u62a5\u544a",
    "\u8c03\u7814\u62a5\u544a",
    "\u6c47\u603b\u62a5\u544a",
    r"\bresearch report\b",
]

_EXPLICIT_BOOK_SEARCH_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _EXPLICIT_BOOK_SEARCH_PATTERNS),
    re.IGNORECASE,
)
_BLOCK_BOOK_SEARCH_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _BLOCK_BOOK_SEARCH_PATTERNS),
    re.IGNORECASE,
)
_MEMORY_UPDATE_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _MEMORY_UPDATE_PATTERNS),
    re.IGNORECASE,
)
_MEMORY_MANAGE_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _MEMORY_MANAGE_PATTERNS),
    re.IGNORECASE,
)
_RECOMMENDATION_SIGNAL_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _RECOMMENDATION_SIGNAL_PATTERNS),
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _RESEARCH_PATTERNS),
    re.IGNORECASE,
)
_RESEARCH_REPORT_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _RESEARCH_REPORT_PATTERNS),
    re.IGNORECASE,
)


def classify_turn_intent(user_message: str) -> TurnIntent:
    """Classify the current user turn into app-owned intent fields."""
    normalized = _normalize_text(user_message)
    if not normalized:
        return TurnIntent(
            primary_intent="answer_question",
            intents=["answer_question"],
            explicit=False,
            confidence=0.3,
            signals=["empty_user_message"],
        )

    signals: list[str] = []
    intents: list[str] = []

    blocked_book_search = bool(_BLOCK_BOOK_SEARCH_RE.search(normalized))
    explicit_book_search = bool(_EXPLICIT_BOOK_SEARCH_RE.search(normalized))
    memory_update = bool(_MEMORY_UPDATE_RE.search(normalized))
    memory_manage = bool(_MEMORY_MANAGE_RE.search(normalized))
    recommendation_signal = bool(_RECOMMENDATION_SIGNAL_RE.search(normalized))
    deep_research = bool(_RESEARCH_RE.search(normalized))
    research_report = bool(_RESEARCH_REPORT_RE.search(normalized))

    if blocked_book_search:
        signals.append("book_search_blocked_by_user_wording")
    if explicit_book_search and not blocked_book_search:
        intents.append("recommend_books")
        signals.append("explicit_book_recommendation_or_search")
    if memory_update:
        intents.append("update_memory")
        signals.append("stable_preference_or_reading_state")
    if memory_manage:
        intents.append("manage_memory")
        signals.append("memory_management_request")
    if recommendation_signal:
        signals.append("recommendation_behavior_signal")
    if deep_research:
        intents.append("deep_search")
        signals.append("explicit_deep_search_or_research")
    if research_report:
        intents.append("research_report")
        signals.append("explicit_research_report")

    if not intents:
        intents.append("answer_question")
        signals.append("default_answer_question")
    elif "answer_question" not in intents:
        intents.insert(0, "answer_question")

    primary_intent = next(
        (
            intent
            for intent in (
                "deep_search",
                "research_report",
                "manage_memory",
                "recommend_books",
                "update_memory",
                "answer_question",
            )
            if intent in intents
        ),
        "answer_question",
    )

    return TurnIntent(
        primary_intent=primary_intent,
        intents=intents,
        explicit=primary_intent != "answer_question",
        confidence=1.0 if primary_intent != "answer_question" else 0.75,
        signals=signals,
        metadata={
            "blocked_book_search": blocked_book_search,
            "explicit_book_search": explicit_book_search and not blocked_book_search,
            "recommendation_signal": recommendation_signal,
        },
    )


def build_turn_policy(user_message: str) -> TurnPolicy:
    """Build the action policy for one turn from the app-owned intent contract."""
    intent = classify_turn_intent(user_message)
    intent_names = set(intent.intents)
    blocked_book_search = bool(intent.metadata.get("blocked_book_search"))

    can_search_books = "recommend_books" in intent_names and not blocked_book_search
    can_recommend_books = can_search_books
    can_record_recommendation_signal = bool(
        intent.metadata.get("recommendation_signal")
        or can_recommend_books
        or "update_memory" in intent_names
    )
    can_start_research = "deep_search" in intent_names or "research_report" in intent_names
    can_use_research_tools = can_start_research
    can_write_memory = "update_memory" in intent_names
    can_manage_memory = "manage_memory" in intent_names
    can_search_memory = (
        can_write_memory
        or can_recommend_books
        or can_manage_memory
        or can_start_research
    )

    allowed_tools = ["get_current_time"]
    denied_tools: list[str] = []
    if can_search_memory:
        allowed_tools.append("search_memory")
    else:
        denied_tools.append("search_memory")
    if can_write_memory:
        allowed_tools.extend(["remember_memory", "revise_memory"])
    else:
        denied_tools.extend(["remember_memory", "revise_memory"])
    if can_manage_memory:
        if "search_memory" not in allowed_tools:
            allowed_tools.append("search_memory")
        allowed_tools.append("forget_memory")
    else:
        denied_tools.append("forget_memory")

    if can_search_books:
        allowed_tools.append("search_books")
    else:
        denied_tools.append("search_books")

    if can_record_recommendation_signal:
        allowed_tools.append("record_recommendation_signal")
    else:
        denied_tools.append("record_recommendation_signal")

    if can_start_research:
        allowed_tools.extend(
            [
                "start_research",
                "inspect_research_state",
                "search_research",
                "visit_source",
                "add_evidence",
                "update_research_state",
                "finish_research",
            ]
        )
    else:
        denied_tools.extend(
            [
                "start_research",
                "inspect_research_state",
                "search_research",
                "visit_source",
                "add_evidence",
                "update_research_state",
                "finish_research",
            ]
        )

    response_boundary = (
        "Answer only the user's stated question. Do not recommend books unless "
        "the user explicitly asks in a later turn."
    )
    if can_recommend_books:
        response_boundary = (
            "Recommend books within the ordinary recommendation budget. Honor "
            "current memory and current-turn constraints."
        )
    elif can_start_research:
        response_boundary = (
            "Use structured research state. Evidence and observations must not "
            "enter final answers unless admitted by the verifier."
        )
    elif "manage_memory" in intent_names:
        response_boundary = "Answer or act only on current-memory management."

    return TurnPolicy(
        intent=intent,
        can_answer_question=True,
        can_write_memory=can_write_memory,
        can_manage_memory=can_manage_memory,
        can_search_memory=can_search_memory,
        can_search_books=can_search_books,
        can_recommend_books=can_recommend_books,
        can_record_recommendation_signal=can_record_recommendation_signal,
        can_start_research=can_start_research,
        can_use_research_tools=can_use_research_tools,
        max_book_search_calls=1 if can_search_books else 0,
        requires_verifier=can_start_research,
        allowed_tools=allowed_tools,
        denied_tools=denied_tools,
        response_boundary=response_boundary,
        metadata={"contract_version": "turn-policy-v1"},
    )


def has_explicit_book_search_intent(user_message: str) -> bool:
    """Compatibility wrapper for ordinary recommendation/search admission."""
    return build_turn_policy(user_message).can_search_books


def build_book_turn_policy_prompt(user_message: str) -> str:
    """Render the turn policy into a compact system-prompt block."""
    policy = build_turn_policy(user_message)
    intent = policy.intent
    lines = [
        "Current Turn Policy",
        "-------------------",
        "contract_version: turn-policy-v1",
        f"primary_intent: {intent.primary_intent}",
        f"intents: {', '.join(intent.intents)}",
        f"signals: {', '.join(intent.signals) if intent.signals else 'none'}",
        f"can_write_memory: {'yes' if policy.can_write_memory else 'no'}",
        f"can_manage_memory: {'yes' if policy.can_manage_memory else 'no'}",
        f"can_search_memory: {'yes' if policy.can_search_memory else 'no'}",
        f"can_search_books: {'yes' if policy.can_search_books else 'no'}",
        f"can_recommend_books: {'yes' if policy.can_recommend_books else 'no'}",
        f"can_record_recommendation_signal: {'yes' if policy.can_record_recommendation_signal else 'no'}",
        f"can_start_research: {'yes' if policy.can_start_research else 'no'}",
        f"max_book_search_calls: {policy.max_book_search_calls}",
        f"requires_verifier: {'yes' if policy.requires_verifier else 'no'}",
        f"allowed_tools: {', '.join(policy.allowed_tools) if policy.allowed_tools else 'none'}",
        f"denied_tools: {', '.join(policy.denied_tools) if policy.denied_tools else 'none'}",
        f"response_boundary: {policy.response_boundary}",
    ]
    return "\n".join(lines)
