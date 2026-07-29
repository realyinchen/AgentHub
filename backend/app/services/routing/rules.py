from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.book_intent import build_turn_policy
from app.services.fast_path import FastPathDecision, decide_fast_path_text
from app.services.routing.config import RULE_DECISIVE_THRESHOLD
from app.services.routing.clarification import is_memory_clarification_answer
from app.services.routing.contracts import IntentCandidate, RoutingQuery


_DEEP_RESEARCH_RE = re.compile(
    r"deep\s+(?:search|research)|深度(?:搜索|研究)|研究报告",
    re.IGNORECASE,
)
_WEATHER_RE = re.compile(r"天气|气温|降雨|下雨|weather|forecast", re.IGNORECASE)
_EXPLICIT_SEARCH_RE = re.compile(
    r"搜索|搜一下|查一下|查询|网上查|look\s+up|search|find\s+online",
    re.IGNORECASE,
)
_CURRENT_FACT_RE = re.compile(
    r"今天|现在|当前|最新|实时|现任|价格|汇率|新闻|"
    r"today|current|latest|now|price|exchange\s+rate|news",
    re.IGNORECASE,
)
_STABLE_EXPLANATION_RE = re.compile(
    r"^(?:什么是|为什么|为何|怎么|如何|解释|说明|原理|定义)|"
    r"^(?:what\s+is|why|how\s+do|how\s+does|explain|define)\b",
    re.IGNORECASE,
)
_FACT_LOOKUP_RE = re.compile(
    r"(?:谁|哪里|何时|什么时候|多少|哪家|哪个).*[?？]?|"
    r"\b(?:who|where|when|how\s+many|which)\b",
    re.IGNORECASE,
)
_PERSONAL_REFERENCE_RE = re.compile(
    r"我|我的|你记得|my\b|me\b|do\s+you\s+remember",
    re.IGNORECASE,
)
_PERSONAL_QUESTION_RE = re.compile(
    r"(?:我|我的).*(?:什么|何时|什么时候|哪里|在哪|多少|几个|哪些|怎么|如何)|"
    r"\b(?:what|when|where|which|how\s+many)\b.*\b(?:my|i|me)\b",
    re.IGNORECASE,
)
_COMPOUND_RE = re.compile(
    r"然后|再|同时|并且|接着|顺便|先.+后|,\s*(?:then|and)|\bthen\b",
    re.IGNORECASE,
)


@dataclass
class RuleRecall:
    candidates: list[IntentCandidate] = field(default_factory=list)
    decisive: bool = False
    compound: bool = False
    fast_path: FastPathDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def recall_rules(query: RoutingQuery) -> RuleRecall:
    text = query.text
    if is_memory_clarification_answer(
        text,
        query.context.pending_memory_write,
    ):
        return RuleRecall(
            candidates=[
                IntentCandidate(
                    intent="memory_update",
                    confidence=0.99,
                    source="rule",
                    evidence=["pending_memory_clarification_answer"],
                    domain="memory",
                )
            ],
            decisive=True,
            metadata={
                "pending_memory_clarification": True,
                "fast_path_reason": "pending_memory_clarification_answer",
            },
        )
    policy = build_turn_policy(text)
    fast_path = decide_fast_path_text(text)
    if fast_path.handled and fast_path.intent:
        intent = {
            "conversation_recall": "conversation_recall",
            "memory_write": "memory_update",
            "memory_lookup": "memory_lookup",
            "reading_feedback": "reading_feedback",
        }[fast_path.intent]
        return RuleRecall(
            candidates=[
                IntentCandidate(
                    intent=intent,
                    confidence=fast_path.confidence,
                    source="rule",
                    evidence=[fast_path.reason],
                    domain=(
                        "conversation"
                        if intent == "conversation_recall"
                        else ("memory" if intent.startswith("memory") else "books")
                    ),
                )
            ],
            decisive=True,
            fast_path=fast_path,
            metadata={"fast_path_reason": fast_path.reason},
        )

    candidates: list[IntentCandidate] = []
    compound = bool(_COMPOUND_RE.search(text))
    if _DEEP_RESEARCH_RE.search(text) or policy.can_start_research:
        candidates.append(
            _candidate(
                "deep_research",
                0.99,
                "explicit_deep_research",
                "research",
            )
        )
    if _WEATHER_RE.search(text):
        candidates.append(
            _candidate(
                "weather_lookup",
                0.98,
                "weather_terms",
                "weather",
            )
        )
    if policy.can_recommend_books:
        candidates.append(
            _candidate(
                "recommend_books",
                0.97,
                "explicit_book_request",
                "books",
            )
        )
    if policy.can_view_recommendation_history:
        candidates.append(
            _candidate(
                "recommendation_history",
                0.97,
                "explicit_recommendation_history",
                "books",
            )
        )
    if policy.can_write_memory:
        candidates.append(
            _candidate(
                "memory_update",
                0.95,
                "turn_policy_memory_update",
                "memory",
            )
        )
    if bool(policy.intent.metadata.get("memory_lookup")):
        candidates.append(
            _candidate(
                "memory_lookup",
                0.95,
                "turn_policy_memory_lookup",
                "memory",
            )
        )
    elif _PERSONAL_QUESTION_RE.search(text):
        candidates.append(
            _candidate(
                "memory_lookup",
                0.96,
                "personal_state_question",
                "memory",
            )
        )

    external_signal = bool(
        _EXPLICIT_SEARCH_RE.search(text)
        or _CURRENT_FACT_RE.search(text)
        or policy.intent.metadata.get("web_search_recommended")
    )
    if external_signal and not policy.can_start_research and not policy.can_search_books:
        candidates.append(
            _candidate(
                "external_lookup",
                0.96,
                "explicit_or_current_external_fact",
                "web",
            )
        )
    elif (
        _FACT_LOOKUP_RE.search(text)
        and not _PERSONAL_REFERENCE_RE.search(text)
        and text.rstrip(" ?？.!。").lower() not in {"你是谁", "who are you"}
    ):
        candidates.append(
            _candidate(
                "external_lookup",
                0.90,
                "unverified_entity_fact",
                "web",
            )
        )

    stable = bool(_STABLE_EXPLANATION_RE.search(text))
    if stable and not candidates:
        candidates.append(
            _candidate(
                "answer_question",
                0.97,
                "stable_explanation",
                "general",
            )
        )

    decisive = (
        not compound
        and bool(candidates)
        and max(item.confidence for item in candidates)
        >= RULE_DECISIVE_THRESHOLD
    )
    return RuleRecall(
        candidates=_dedupe(candidates),
        decisive=decisive,
        compound=compound,
        metadata={"stable_explanation": stable},
    )


def _candidate(
    intent: str,
    confidence: float,
    evidence: str,
    domain: str,
) -> IntentCandidate:
    return IntentCandidate(
        intent=intent,
        confidence=confidence,
        source="rule",
        evidence=[evidence],
        domain=domain,
    )


def _dedupe(candidates: list[IntentCandidate]) -> list[IntentCandidate]:
    by_intent: dict[str, IntentCandidate] = {}
    for candidate in candidates:
        current = by_intent.get(candidate.intent)
        if current is None or candidate.confidence > current.confidence:
            by_intent[candidate.intent] = candidate
    return sorted(by_intent.values(), key=lambda item: item.confidence, reverse=True)
