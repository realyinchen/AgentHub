from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.routing.interaction_contracts import (
    BusinessRoutingContext,
    GoalClause,
    GoalDecision,
    RoutingEvidence,
)
from app.services.routing.clarification import is_memory_clarification_answer
from app.services.routing.speech_act import analyze_speech_act


_INTENT_TO_GOAL: dict[str, tuple[str, str]] = {
    "answer_question": ("answer_question", "general"),
    "memory_lookup": ("retrieve_personal_context", "personal_context"),
    "memory_update": ("share_personal_information", "personal_context"),
    "weather_lookup": ("answer_current_question", "weather"),
    "external_lookup": ("answer_factual_question", "general"),
    "recommend_books": ("recommend_books", "books"),
    "recommendation_history": ("review_recommendation_history", "books"),
    "reading_feedback": ("record_reading_feedback", "books"),
    "conversation_recall": ("recall_conversation", "conversation"),
    "deep_research": ("research_topic", "research"),
    "retrieve_current_information": ("answer_current_question", "weather"),
    "find_books": ("recommend_books", "books"),
    "record_reading_feedback": ("record_reading_feedback", "books"),
}
_FOLLOW_UP_RE = re.compile(
    r"^(?:再|继续|还有|类似|换一批|接着|改成|那|这本|这个|它|"
    r"more\b|another\b|continue\b)",
    re.I,
)
_BOOK_RE = re.compile(
    r"书|图书|小说|读物|作品|绘本|科普|阅读|作者|《[^》]+》|book|novel|author",
    re.I,
)
_WEATHER_RE = re.compile(r"天气|气温|降雨|下雨|weather|forecast", re.I)
_PERSONAL_LOOKUP_RE = re.compile(
    r"^(?:我是谁|你(?:还)?记得我|关于我你记得什么|"
    r"我(?:平时|通常)?.*(?:喜欢|偏好).*(?:什么|哪些).*|"
    r"what do you remember about me)\s*[？?]?$",
    re.I,
)
_CONVERSATION_RECALL_RE = re.compile(
    r"(?:我刚才|我上面|我之前刚刚)(?:跟你)?(?:说|讲|问|告诉)(?:了)?什么|"
    r"(?:刚才|上面)(?:我们)?(?:说|聊)(?:了)?什么|"
    r"(?:你刚才|你上面)(?:说|回答)(?:了)?什么|"
    r"\bwhat did (?:i|you) (?:just )?say\b",
    re.I,
)
_RECOMMEND_RE = re.compile(
    r"推荐|找(?:一|几|三|些|本|\d)*本?|类似(?:的|作品|读物|书)|"
    r"有没有.*(?:书|读物|小说|科普)|recommend|suggest",
    re.I,
)
_BOOK_FIND_RE = re.compile(
    r"(?:帮我)?找《[^》]+》.*(?:信息|资料)|查询《[^》]+》|find .*book",
    re.I,
)
_RESEARCH_RE = re.compile(r"深度(?:搜索|研究)|研究报告|deep research", re.I)
_CURRENT_RE = re.compile(
    r"今天|明天|现在|此刻|当前|最新|实时|现任|本周|价格|汇率|新闻|"
    r"today|tomorrow|current|latest|now|real[- ]?time|price|news",
    re.I,
)
_EXPLICIT_EXTERNAL_RE = re.compile(
    r"搜索|联网|网上查|查一下|官网|search|browse|look up|find online",
    re.I,
)
_READING_FEEDBACK_RE = re.compile(
    r"(?:已经|刚刚|刚)?(?:读过|看过|读完)|标记为(?:已读|不喜欢|想读)|"
    r"mark .* (?:read|finished)",
    re.I,
)
_EXPLICIT_MEMORY_RE = re.compile(
    r"^(?:先)?(?:请)?(?:记住|记一下|保存|以后要记得)\s*[:：]?\s*(?!这个|那个|它)",
    re.I,
)
_DURABLE_PERSONAL_STATEMENT_RE = re.compile(
    r"^(?:我)(?:现在|以后|平时|通常)?(?:不)?(?:叫|是|喜欢|偏好|只看|不看|住在|从事)"
    r"(?!谁|什么|哪|多少)[^？?]+[。.!！]?$|"
    r"^my (?:name|preference|job|home)\b|^i (?:like|prefer|live|work)\b",
    re.I,
)
_AMBIGUOUS_FOLLOW_UP_RE = re.compile(
    r"^(?:来几个|找几本类似|再来|类似的|改成|那|这本|这个|它)|"
    r"(?:把)?(?:这个|那个|它)(?:记住|保存)",
    re.I,
)
_YOU_ARE_RE = re.compile(r"^(?:你是谁|who are you)\s*[？?]?$", re.I)
_CAPABILITY_PROHIBITION_RE = re.compile(
    r"(?:不要|别|无需|不用|禁止|请勿).*(?:搜索|联网|推荐|找书|深度研究|拆解|记住)|"
    r"(?:do not|don't|without).*(?:search|browse|recommend|research|decompose|remember)",
    re.I,
)


class GoalResolver:
    """Resolve what the user wants, without deciding how to execute it."""

    def resolve(
        self,
        clause: GoalClause,
        evidence: Sequence[RoutingEvidence],
        context: BusinessRoutingContext,
    ) -> GoalDecision:
        text = clause.text
        speech = analyze_speech_act(text)
        legacy_intents = sorted({item.intent for item in evidence})

        if is_memory_clarification_answer(
            text,
            context.pending_memory_write,
        ):
            return GoalDecision(
                kind="share_personal_information",
                domain="personal_context",
                topic=context.pending_memory_write.target_expression,
                legacy_intents=legacy_intents,
                rationale=["pending_memory_clarification_answer"],
                confidence=0.99,
            )

        if speech.act != "request":
            domain = "conversation" if speech.act == "social_response" else "general"
            return GoalDecision(
                kind=speech.act,
                domain=domain,
                topic=clause.quoted_spans[0] if clause.quoted_spans else None,
                legacy_intents=legacy_intents,
                rationale=[speech.reason],
                confidence=speech.confidence,
            )

        if (
            clause.polarity in {"negative", "mixed"}
            and _CAPABILITY_PROHIBITION_RE.search(speech.outer_text)
        ):
            return GoalDecision(
                kind="express_constraint",
                domain="policy",
                topic=clause.quoted_spans[0] if clause.quoted_spans else None,
                legacy_intents=legacy_intents,
                rationale=["explicit_capability_prohibition"],
                confidence=0.98,
            )

        if (
            clause.ordinal == 0
            and (
                _FOLLOW_UP_RE.search(text)
                or clause.relation == "then"
                or _AMBIGUOUS_FOLLOW_UP_RE.search(text)
            )
            and not context.previous_primary_intent
            and not context.active_subject
        ):
            return GoalDecision(
                kind="clarify_referent",
                domain="conversation",
                topic=None,
                legacy_intents=legacy_intents,
                rationale=["referential_follow_up_has_no_business_context"],
                confidence=0.98,
            )

        explicit = self._explicit_goal(text)
        ranked = sorted(
            evidence,
            key=lambda item: self._adjusted_score(item, text),
            reverse=True,
        )
        best = ranked[0] if ranked else None

        if explicit is not None:
            kind, domain, confidence, reason = explicit
            if (
                kind == "answer_current_question"
                and any(_WEATHER_RE.search(item) for item in context.recent_user_messages)
            ):
                domain = "weather"
        elif (
            clause.ordinal == 0
            and (
                clause.relation == "then"
                or _FOLLOW_UP_RE.search(text)
                or _AMBIGUOUS_FOLLOW_UP_RE.search(text)
            )
            and context.previous_primary_intent
        ):
            kind, domain = _INTENT_TO_GOAL.get(
                context.previous_primary_intent,
                (context.previous_primary_intent, "general"),
            )
            confidence, reason = 0.90, "resolved_from_previous_business_intent"
        elif best is not None and self._adjusted_score(best, text) >= 0.50:
            kind, domain = _INTENT_TO_GOAL.get(
                best.intent,
                (best.intent, best.domain),
            )
            confidence = min(0.96, self._adjusted_score(best, text))
            reason = f"{best.source}:{best.intent}"
        elif clause.polarity == "negative":
            kind, domain, confidence, reason = (
                "express_constraint",
                "policy",
                0.92,
                "negative_clause",
            )
        else:
            kind, domain, confidence, reason = (
                "answer_question",
                "general",
                0.58,
                "safe_general_goal",
            )

        topic = clause.quoted_spans[0] if clause.quoted_spans else context.active_subject
        return GoalDecision(
            kind=kind,
            domain=domain,
            topic=topic,
            legacy_intents=legacy_intents,
            rationale=[reason],
            confidence=confidence,
        )

    @staticmethod
    def _explicit_goal(text: str) -> tuple[str, str, float, str] | None:
        speech = analyze_speech_act(text)
        surface = speech.outer_text
        if _RESEARCH_RE.search(surface):
            return ("research_topic", "research", 0.98, "explicit_research_request")
        if _READING_FEEDBACK_RE.search(surface) and (
            _BOOK_RE.search(text) or re.search(r"^(?:这本|那本|它)", surface)
        ):
            return (
                "record_reading_feedback",
                "books",
                0.98,
                "explicit_reading_feedback",
            )
        if _EXPLICIT_MEMORY_RE.search(surface):
            return (
                "share_personal_information",
                "personal_context",
                0.98,
                "explicit_memory_statement",
            )
        if _CONVERSATION_RECALL_RE.search(surface):
            return (
                "recall_conversation",
                "conversation",
                0.99,
                "explicit_current_thread_recall",
            )
        if _PERSONAL_LOOKUP_RE.search(surface):
            return (
                "retrieve_personal_context",
                "personal_context",
                0.98,
                "explicit_personal_context_question",
            )
        if _DURABLE_PERSONAL_STATEMENT_RE.search(surface):
            return (
                "share_personal_information",
                "personal_context",
                0.97,
                "durable_personal_statement",
            )
        if _YOU_ARE_RE.search(surface):
            return ("answer_question", "general", 0.99, "assistant_identity_question")
        # A quoted work and an authorship question is an entity fact, not "my memory".
        if re.search(r"《[^》]+》", text) and re.search(r"谁写|作者|who wrote", surface, re.I):
            return (
                "answer_factual_question",
                "books",
                0.97,
                "quoted_work_authorship_question",
            )
        if _BOOK_FIND_RE.search(text):
            return ("find_books", "books", 0.98, "explicit_book_lookup")
        if _RECOMMEND_RE.search(surface) and _BOOK_RE.search(surface):
            return ("recommend_books", "books", 0.97, "explicit_book_recommendation")
        if _CURRENT_RE.search(surface):
            domain = "weather" if _WEATHER_RE.search(surface) else "general"
            return (
                "answer_current_question",
                domain,
                0.97,
                "current_information_request",
            )
        if _WEATHER_RE.search(surface) and not _BOOK_RE.search(surface):
            return ("answer_current_question", "weather", 0.94, "weather_question")
        if _EXPLICIT_EXTERNAL_RE.search(surface):
            return (
                "answer_factual_question",
                "general",
                0.96,
                "explicit_external_information_request",
            )
        return None

    @staticmethod
    def _adjusted_score(evidence: RoutingEvidence, text: str) -> float:
        score = evidence.confidence
        if evidence.polarity == "opposes":
            return 0.0
        if evidence.intent == "weather_lookup" and _BOOK_RE.search(text):
            score -= 0.35
        if evidence.intent == "memory_lookup":
            if re.search(r"《[^》]+》", text):
                score -= 0.60
            elif (
                not _PERSONAL_LOOKUP_RE.search(text)
                and "personal_state_question" not in evidence.reasons
            ):
                score -= 0.20
        if evidence.intent == "recommend_books" and not _BOOK_RE.search(text):
            score -= 0.30
        if evidence.intent == "weather_lookup" and _WEATHER_RE.search(text):
            score += 0.08
        return max(0.0, min(1.0, score))
