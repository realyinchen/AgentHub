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
        "recommendation_history",
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
    "can_view_recommendation_history",
    "can_record_recommendation_signal",
    "can_start_research",
    "can_use_research_tools",
    "can_use_web_search",
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
            "One of answer_question, update_memory, recommend_books, "
            "recommendation_history, deep_search, research_report, manage_memory."
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
    can_view_recommendation_history: bool = False
    can_record_recommendation_signal: bool = False
    can_start_research: bool = False
    can_use_research_tools: bool = False
    can_use_web_search: bool = False
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
    "\u8bb0\u4f4f",
    "\u8bb0\u4e00\u4e0b",
    "\u5e2e\u6211\u8bb0",
    "\u4f60\u8bb0\u4e0b",
    "\u6211\u53eb(?!\u4ec0\u4e48)",
    r"^\s*\u6211\u662f(?!\u8c01|\u4ec0\u4e48|\u5565)(?!\u4e00\u4e2a|\u4e00\u540d)[\w\u4e00-\u9fff\u00b7\.\-]{1,32}\s*(?:[.!?\u3002\uff01\uff1f])?\s*$",
    "\u53eb\u6211",
    "\u6211\u662f.*(?:\u4f60\u8bb0\u4f4f|\u8bb0\u4f4f|\u8bb0\u4e00\u4e0b)",
    "\u6211\u7684.*(?:\u4f5c\u606f|\u4e60\u60ef|\u504f\u597d|\u5174\u8da3|\u7231\u597d|\u540d\u5b57|\u6635\u79f0)",
    "\u6211(?:\u901a\u5e38|\u4e00\u822c|\u7ecf\u5e38|\u6bcf\u5929|\u957f\u671f|\u4e00\u76f4).*(?:\u7761|\u8d77|\u8bfb|\u770b|\u559c\u6b22|\u505a|\u542c|\u8fd0\u52a8|\u5de5\u4f5c)",
    "\u6211\u4e60\u60ef",
    "\u6211\u7684\u4f5c\u606f",
    "\u6211\u6709(?:\u4e00\u53ea)?(?:\u732b\u54aa|\u732b|\u72d7\u72d7|\u72d7)(?:\u53eb|\u540d\u5b57\u53eb)",
    "\u6211\u559c\u6b22",  # I like
    "\u6211\u4e0d\u559c\u6b22",  # I dislike
    "\u4e0d\u7231\u770b",
    "\u559c\u6b22.*\u8fd9\u79cd",
    "\u4e0d\u8981.*\u8fd9\u79cd",
    "\u4e0d\u611f\u5174\u8da3",
    "\u6ca1\u5174\u8da3",
    "\u907f\u514d",
    "\u8ba8\u538c",
    "\u6211\u60f3\u770b",
    "\u6211\u770b\u8fc7",
    "\u770b\u8fc7",
    "\u8bfb\u8fc7",
    "\u5df2\u8bfb",
    "\u8bfb\u5b8c",
    r"\bi\s+(?:like|love|prefer|dislike|hate|avoid)\b",
    r"\bi\s+(?:usually|generally|often|always|tend to)\b",
    r"\bi\s+(?:want to read|have read|already read)\b",
    r"\bmy\s+(?:routine|habit|sleep schedule|schedule|hobb(?:y|ies)|interests?|preference)\b",
    r"\bremember\s+(?:that\s+)?(?:my|i|me)\b",
    r"\bmy\s+name\s+is\b",
    r"\bcall\s+me\b",
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

_MEMORY_LOOKUP_PATTERNS = [
    "\u6211\u53eb\u4ec0\u4e48",
    "\u6211\u7684\u540d\u5b57",
    "\u4f60\u8bb0\u5f97\u6211\u53eb",
    "\u4f60\u77e5\u9053\u6211\u53eb",
    "\u4f60\u77e5\u9053\u6211\u662f\u8c01",
    "\u4f60\u8bb0\u5f97\u6211\u662f\u8c01",
    "\u6211\u662f\u8c01",
    "\u4f60\u8fd8\u8bb0\u5f97\u6211",
    "\u6211\u7684\u4e60\u60ef",
    "\u6211\u7684\u4f5c\u606f",
    "\u6211\u7684(?:\u732b|\u732b\u54aa|\u72d7|\u72d7\u72d7|\u5ba0\u7269)",
    "(?:\u4f60\u8fd8?\u8bb0\u5f97|\u8fd8?\u8bb0\u5f97)(?:\u5173\u4e8e)?\u6211\u7684",
    "\u6211\u7684.+(?:\u662f\u4ec0\u4e48|\u53eb\u4ec0\u4e48|\u6709\u54ea\u4e9b|\u653e\u5728\u54ea|\u5728\u54ea)",
    "\u6211\u4e4b\u524d\u8ba9\u4f60\u8bb0\u4f4f",
    r"\bwhat(?:'s| is)\s+my\s+name\b",
    r"\bwho\s+am\s+i\b",
    r"\bdo\s+you\s+remember\s+my\s+name\b",
    r"\bdo\s+you\s+remember\s+me\b",
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

_RECOMMENDATION_HISTORY_PATTERNS = [
    "\u9605\u8bfb\u5386\u53f2",
    "\u5df2\u8bfb(?:\u4e66|\u4e66\u5355|\u5217\u8868|\u8bb0\u5f55)",
    "(?:\u8bfb\u8fc7|\u770b\u8fc7).*(?:\u54ea\u4e9b|\u4ec0\u4e48|\u8bb0\u5f55|\u5386\u53f2|\u4e66)",
    "\u62d2\u7edd\u8bb0\u5f55",
    "(?:\u4e0d\u611f\u5174\u8da3|\u6ca1\u5174\u8da3).*(?:\u8bb0\u5f55|\u54ea\u4e9b|\u4e66)",
    "(?:\u4e3a\u4ec0\u4e48|\u4e3a\u5565).*(?:\u6ca1|\u4e0d).*\u63a8\u8350",
    "(?:\u8fc7\u6ee4|\u6291\u5236).*(?:\u8bb0\u5f55|\u4e66|\u5019\u9009)",
    r"\breading\s+history\b",
    r"\bwhat\s+books?\s+have\s+i\s+(?:already\s+)?read\b",
    r"\bwhich\s+books?\s+have\s+i\s+(?:already\s+)?read\b",
    r"\bbooks?\s+i\s+(?:already\s+)?(?:read|finished)\b",
    r"\b(?:already\s+read|finished)\s+books?\b",
    r"\brejected\s+books?\b",
    r"\bnot\s+interested\s+(?:records?|books?)\b",
    r"\bsuppressed\s+(?:records?|books?|candidates?)\b",
    r"\bfiltered\s+out\s+books?\b",
    r"\bwhy\s+(?:did(?:n't| not)|weren't|wasn't).*\brecommend\b",
    r"\bwhy\b(?=[^?!.]*\brecommend(?:ed)?\b)(?=[^?!.]*(?:\bnot\b|\bnever\b|didn't|did not|wasn't|weren't))",
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

_WEB_SEARCH_PATTERNS = [
    "\u5730\u5740",
    "\u5177\u4f53\u5730\u5740",
    "\u8be6\u7ec6\u5730\u5740",
    "\u4f4d\u7f6e",
    "\u5730\u70b9",
    "\u54ea\u91cc",
    "\u5728\u54ea",
    "\u4f4d\u4e8e",
    "\u5b98\u7f51",
    "\u5b98\u65b9\u7f51\u7ad9",
    "\u8054\u7cfb\u7535\u8bdd",
    "\u8054\u7cfb\u65b9\u5f0f",
    "\u8425\u4e1a\u65f6\u95f4",
    "\u5929\u6c14",
    "\u6c14\u6e29",
    "\u964d\u96e8",
    "\u4e0b\u96e8",
    "\u65b0\u95fb",
    "\u70ed\u641c",
    "\u6700\u65b0",
    "\u5f53\u524d",
    "\u73b0\u5728",
    "\u76ee\u524d",
    "\u6700\u8fd1",
    "\u8fd1\u51e0\u5e74",
    "\u622a\u81f3",
    "\u4e3b\u6d41",
    "\u73b0\u72b6",
    "\u8d8b\u52bf",
    "\u6700\u65b0\u7248\u672c",
    "\u653f\u7b56",
    "\u6cd5\u89c4",
    "\u6cd5\u5f8b",
    "\u6392\u540d",
    "\u5e02\u5360\u7387",
    "\u4eca\u5929.*(?:\u600e\u4e48\u6837|\u5982\u4f55)",
    "\u80a1\u4ef7",
    "\u80a1\u7968",
    "\u6c47\u7387",
    "\u8def\u51b5",
    r"(?:\u603b\u7edf|\u603b\u7406|\u4e3b\u5e2d|\u5e02\u957f|\u90e8\u957f|\u8d1f\u8d23\u4eba|\u8463\u4e8b\u957f|\u9996\u5e2d\u6267\u884c\u5b98|CEO)(?:\u662f\u8c01|\u53eb\u4ec0\u4e48)",
    r"(?:\u8c01\u662f|\u73b0\u4efb|\u76ee\u524d\u7684).*(?:\u603b\u7edf|\u603b\u7406|\u4e3b\u5e2d|\u5e02\u957f|\u90e8\u957f|\u8d1f\u8d23\u4eba|\u8463\u4e8b\u957f|\u9996\u5e2d\u6267\u884c\u5b98|CEO)",
    r"\baddress\b",
    r"\blocation\b",
    r"\bwhere\s+is\b",
    r"\bofficial\s+website\b",
    r"\bcontact\b",
    r"\bphone\s+number\b",
    r"\bopening\s+hours?\b",
    r"\bweather\b",
    r"\bforecast\b",
    r"\bnews\b",
    r"\blatest\b",
    r"\bcurrent\b",
    r"\brecent\b",
    r"\bmainstream\b",
    r"\btrend(?:s)?\b",
    r"\bpolicy\b",
    r"\blaw\b",
    r"\bregulation(?:s)?\b",
    r"\bversion\b",
    r"\bstock\b",
    r"\bexchange\s+rate\b",
    r"\bwho\s+is\s+(?:the\s+)?(?:president|prime\s+minister|chair(?:man|person)?|mayor|minister|ceo)\b",
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
_MEMORY_LOOKUP_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _MEMORY_LOOKUP_PATTERNS),
    re.IGNORECASE,
)
_RECOMMENDATION_SIGNAL_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _RECOMMENDATION_SIGNAL_PATTERNS),
    re.IGNORECASE,
)
_RECOMMENDATION_HISTORY_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _RECOMMENDATION_HISTORY_PATTERNS),
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
_WEB_SEARCH_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _WEB_SEARCH_PATTERNS),
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
    memory_lookup = bool(_MEMORY_LOOKUP_RE.search(normalized))
    recommendation_signal = bool(_RECOMMENDATION_SIGNAL_RE.search(normalized))
    recommendation_history = bool(_RECOMMENDATION_HISTORY_RE.search(normalized))
    if recommendation_history:
        memory_lookup = False
    deep_research = bool(_RESEARCH_RE.search(normalized))
    research_report = bool(_RESEARCH_REPORT_RE.search(normalized))
    web_search_recommended = bool(_WEB_SEARCH_RE.search(normalized))

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
    if memory_lookup:
        signals.append("profile_memory_lookup_request")
    if recommendation_signal:
        signals.append("recommendation_behavior_signal")
    if recommendation_history:
        intents.append("recommendation_history")
        signals.append("explicit_recommendation_history_or_suppression_explanation")
    if deep_research:
        intents.append("deep_search")
        signals.append("explicit_deep_search_or_research")
    if research_report:
        intents.append("research_report")
        signals.append("explicit_research_report")
    if web_search_recommended and not explicit_book_search and not deep_research:
        signals.append("time_sensitive_or_current_web_fact")

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
                "recommendation_history",
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
            "recommendation_history": recommendation_history,
            "memory_lookup": memory_lookup,
            "web_search": True,
            "web_search_recommended": (
                web_search_recommended and not explicit_book_search and not deep_research
            ),
        },
    )


def build_turn_policy(user_message: str) -> TurnPolicy:
    """Build the action policy for one turn from the app-owned intent contract."""
    intent = classify_turn_intent(user_message)
    intent_names = set(intent.intents)
    blocked_book_search = bool(intent.metadata.get("blocked_book_search"))

    can_view_recommendation_history = "recommendation_history" in intent_names
    can_search_books = (
        "recommend_books" in intent_names
        and not blocked_book_search
        and not can_view_recommendation_history
    )
    can_recommend_books = can_search_books
    can_record_recommendation_signal = bool(
        intent.metadata.get("recommendation_signal")
        or can_recommend_books
        or "update_memory" in intent_names
    )
    can_start_research = "deep_search" in intent_names or "research_report" in intent_names
    can_use_research_tools = can_start_research
    can_use_web_search = True
    can_write_memory = "update_memory" in intent_names
    can_manage_memory = "manage_memory" in intent_names
    can_lookup_memory = bool(intent.metadata.get("memory_lookup"))
    # Memory recall is a generally available, read-only capability. This flag is
    # permission, not an instruction to execute it; ActionPlanner still decides
    # whether the current turn needs a search_memory action.
    can_search_memory = True

    allowed_tools = ["get_current_time", "plan_book_assistant_turn"]
    denied_tools: list[str] = []
    allowed_tools.append("web_search")
    if can_search_memory:
        allowed_tools.append("search_memory")
    else:
        denied_tools.append("search_memory")
    if can_write_memory:
        allowed_tools.extend(
            [
                "remember_reading_preference",
                "record_book_feedback",
            ]
        )
        denied_tools.extend(["remember_memory", "revise_memory"])
    else:
        denied_tools.extend(
            [
                "remember_memory",
                "revise_memory",
                "remember_reading_preference",
                "record_book_feedback",
            ]
        )
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

    if can_view_recommendation_history:
        allowed_tools.append("get_recommendation_history")
    else:
        denied_tools.append("get_recommendation_history")

    if can_record_recommendation_signal:
        allowed_tools.append("record_recommendation_signal")
    else:
        denied_tools.append("record_recommendation_signal")

    if can_start_research:
        allowed_tools.extend(
            [
                "start_research",
                "inspect_research_state",
                "search_research_sources",
                "search_research_scholar_sources",
                "search_research",
                "visit_source",
                "add_evidence",
                "update_research_state",
                "finish_research",
                "plan_recommendation_research_workflow",
                "run_recommendation_research_workflow",
                "build_recommendation_research_report",
                "build_research_observations",
                "analyze_research_data",
                "extract_research_source_records",
                "collect_research_sources",
                "fetch_research_source",
                "build_research_report",
                "finalize_research_answer",
                "run_research_harness",
            ]
        )
    else:
        denied_tools.extend(
            [
                "start_research",
                "inspect_research_state",
                "search_research_sources",
                "search_research_scholar_sources",
                "search_research",
                "visit_source",
                "add_evidence",
                "update_research_state",
                "finish_research",
                "plan_recommendation_research_workflow",
                "run_recommendation_research_workflow",
                "build_recommendation_research_report",
                "build_research_observations",
                "analyze_research_data",
                "extract_research_source_records",
                "collect_research_sources",
                "fetch_research_source",
                "build_research_report",
                "finalize_research_answer",
                "run_research_harness",
            ]
        )

    response_boundary = (
        "Answer the user's stated question. Use web_search when live, current, "
        "external web, address, location, contact, official-site, opening-hour, "
        "price, or lookup-style facts are useful. For non-English lookup turns, "
        "rewrite the web_search query to concise English while preserving "
        "intent. Do not recommend books unless the user explicitly asks in a "
        "later turn."
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
    elif can_view_recommendation_history:
        response_boundary = (
            "Answer only with recommendation history or suppression explanation. "
            "Do not treat suppressed records as fresh recommendation candidates."
        )
    elif "manage_memory" in intent_names:
        response_boundary = "Answer or act only on current-memory management."
    elif can_lookup_memory:
        response_boundary = (
            "Answer from active long-term memory. If the requested profile fact "
            "is absent, say it is not recorded yet."
        )

    return TurnPolicy(
        intent=intent,
        can_answer_question=True,
        can_write_memory=can_write_memory,
        can_manage_memory=can_manage_memory,
        can_search_memory=can_search_memory,
        can_search_books=can_search_books,
        can_recommend_books=can_recommend_books,
        can_view_recommendation_history=can_view_recommendation_history,
        can_record_recommendation_signal=can_record_recommendation_signal,
        can_start_research=can_start_research,
        can_use_research_tools=can_use_research_tools,
        can_use_web_search=can_use_web_search,
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
        f"can_view_recommendation_history: {'yes' if policy.can_view_recommendation_history else 'no'}",
        f"can_record_recommendation_signal: {'yes' if policy.can_record_recommendation_signal else 'no'}",
        f"can_start_research: {'yes' if policy.can_start_research else 'no'}",
        f"can_use_web_search: {'yes' if policy.can_use_web_search else 'no'}",
        f"max_book_search_calls: {policy.max_book_search_calls}",
        f"requires_verifier: {'yes' if policy.requires_verifier else 'no'}",
        f"allowed_tools: {', '.join(policy.allowed_tools) if policy.allowed_tools else 'none'}",
        f"denied_tools: {', '.join(policy.denied_tools) if policy.denied_tools else 'none'}",
        f"response_boundary: {policy.response_boundary}",
    ]
    return "\n".join(lines)
