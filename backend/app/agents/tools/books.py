"""Book recommendation tools for the supervisor agent."""

from __future__ import annotations

import json
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.crud.book import (
    create_book_interaction,
    create_recommendation_event,
    find_book_by_title,
)
from app.infra.database import get_database
from app.schemas.book import BookInteractionCreate
from app.services.book_search import search_and_cache_books_with_status
from app.services.book_search_contracts import get_book_search_hint
from app.services.book_turn_orchestration import (
    BOOK_TURN_ORCHESTRATION_CONTRACT_VERSION,
    plan_book_assistant_turn as plan_book_assistant_turn_result,
)
from app.services.memory import MemoryCandidate, get_memory_orchestrator
from app.services.recommendation_projection import (
    RecommendationCandidateProjection,
    RecommendationProjector,
)
from app.services.recommendation_history import (
    RECOMMENDATION_HISTORY_MODES,
    get_recommendation_history as get_recommendation_history_result,
    normalize_recommendation_history_mode,
)
from app.services.recommendation_constraints import (
    build_personalized_recommendation_constraints,
)
from app.services.recommendation_signals import (
    RecommendationSignalCreate,
    build_follow_up_questions,
    map_interaction_to_recommendation_signal,
    recommendation_signal_from_record,
)
from app.services.tool_admission import (
    ToolAdmissionResult,
    ToolPolicyDeclaration,
    get_tool_admission_gate,
    reset_tool_admission_gate,
)
from app.utils.logging import get_request_id
from app.utils.turn_context import get_current_user_message


SEARCH_BOOKS_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="search_books",
    required_policy_flags=["can_search_books"],
    side_effect_scope="book_cache",
    external_call=True,
    max_calls_per_turn=1,
    blocked_status="intent_blocked",
    metadata={"budget_blocked_status": "loop_detected"},
)
PLAN_BOOK_ASSISTANT_TURN_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="plan_book_assistant_turn",
    required_policy_flags=[],
    side_effect_scope="none",
    blocked_status="tool_blocked",
    metadata={"contract_version": BOOK_TURN_ORCHESTRATION_CONTRACT_VERSION},
)
REMEMBER_READING_PREFERENCE_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="remember_reading_preference",
    required_policy_flags=["can_write_memory"],
    side_effect_scope="long_term_memory",
    writes_long_term_memory=True,
    blocked_status="tool_blocked",
)
RECORD_BOOK_FEEDBACK_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="record_book_feedback",
    required_policy_flags=["can_write_memory"],
    side_effect_scope="multi_scope",
    writes_long_term_memory=True,
    blocked_status="tool_blocked",
)
RECORD_RECOMMENDATION_SIGNAL_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="record_recommendation_signal",
    required_policy_flags=["can_record_recommendation_signal"],
    side_effect_scope="recommendation_state",
    blocked_status="tool_blocked",
)
GET_RECOMMENDATION_HISTORY_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="get_recommendation_history",
    required_policy_flags=["can_view_recommendation_history"],
    side_effect_scope="none",
    blocked_status="tool_blocked",
    metadata={"read_scope": "recommendation_state"},
)
RECOMMENDATION_EXPLANATION_CONTRACT_VERSION = "recommendation-explanation-v1"


class BookSearchInput(BaseModel):
    query: str = Field(
        description="Book recommendation/search query, including genre, mood, author, or constraints."
    )
    limit: int = Field(default=5, ge=1, le=10, description="Maximum books to return.")
    user_id: UUID | None = Field(
        default=None,
        description=(
            "Current user ID. Pass this when available so read or rejected books "
            "can be suppressed from recommendation candidates."
        ),
    )
    allow_additional_search: bool = Field(
        default=False,
        description=(
            "Set true only when the user explicitly asks for another search, "
            "a refined search, or a separate search in the same turn. Keep false "
            "for ordinary recommendations."
        ),
    )


class PlanBookAssistantTurnInput(BaseModel):
    user_id: UUID | None = Field(
        default=None,
        description="Current user ID, when available, for personalized constraints.",
    )
    user_message: str = Field(
        default="",
        description="Original user message. Defaults to current turn context.",
    )
    query: str = Field(
        default="",
        description="Recommendation or research query. Defaults to user_message.",
    )
    candidates: list[dict] = Field(
        default_factory=list,
        description="Existing book candidates, normally from search_books.books.",
    )
    research_report: dict = Field(
        default_factory=dict,
        description="Existing research-report-v1 payload, if already available.",
    )
    research_state: dict = Field(
        default_factory=dict,
        description="Existing ResearchStateResult payload, if already available.",
    )
    book_title: str = Field(
        default="",
        description="Optional title for recommendation-history explanations.",
    )
    metadata: dict = Field(default_factory=dict)


class RememberReadingPreferenceInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    preferred_tags: list[str] = Field(
        default_factory=list,
        description="Genres, moods, themes, or traits the user likes.",
    )
    disliked_tags: list[str] = Field(
        default_factory=list,
        description="Genres, moods, themes, or traits the user dislikes.",
    )
    favorite_authors: list[str] = Field(
        default_factory=list,
        description="Authors the user likes.",
    )
    disliked_authors: list[str] = Field(
        default_factory=list,
        description="Authors the user dislikes.",
    )
    note: str = Field(
        default="",
        description="Short natural-language memory note to append to the profile.",
    )
    profile_summary: str = Field(
        default="",
        description="Optional concise updated preference summary.",
    )


class RecordBookFeedbackInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    book_title: str = Field(description="Book title the feedback refers to.")
    interaction_type: str = Field(
        description=(
            "Feedback type, e.g. want_to_read, read, like, dislike, "
            "not_interested, similar, recommended."
        )
    )
    thread_id: UUID | None = Field(default=None, description="Current thread ID.")
    note: str = Field(default="", description="Optional feedback note.")
    rating: int | None = Field(default=None, ge=1, le=5)


class RecordRecommendationSignalInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    thread_id: UUID | None = Field(default=None, description="Current thread ID.")
    book_title: str = Field(default="", description="Book title if the signal refers to one.")
    event_type: str = Field(
        description=(
            "Recommendation event type such as detail_requested, followup_clicked, "
            "followup_matched, not_interested, read, liked, disliked, or recommended."
        )
    )
    signal_polarity: str = Field(default="neutral")
    signal_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = Field(default="agent_tool")
    note: str = Field(default="")
    metadata: dict = Field(default_factory=dict)


class GetRecommendationHistoryInput(BaseModel):
    user_id: UUID = Field(description="Current user ID from system context.")
    history_mode: str = Field(
        default="all",
        description=(
            "One of all, reading_history, rejection_history, or "
            "suppression_explanation."
        ),
    )
    query: str = Field(default="", description="Original user history question.")
    book_title: str = Field(
        default="",
        description="Optional concrete title for a suppression explanation.",
    )
    limit: int = Field(default=20, ge=1, le=50)


def _book_to_dict(
    book,
    projection: RecommendationCandidateProjection | None = None,
    source_info: dict | None = None,
) -> dict:
    payload = {
        "id": str(book.id),
        "title": book.title,
        "authors": book.authors or [],
        "summary": book.summary,
        "rating": float(book.rating) if book.rating is not None else None,
        "source_name": book.source_name,
        "source_url": book.source_url,
        "external_id": book.external_id,
    }
    if source_info:
        payload["candidate_source"] = source_info
    if projection is not None:
        payload["recommendation"] = projection.model_dump(mode="json")
    explanation = _build_recommendation_explanation(
        book=book,
        projection=projection,
        source_info=source_info or {},
    )
    if explanation:
        payload["recommendation_explanation"] = explanation
    return payload


def _build_recommendation_explanation(
    *,
    book,
    projection: RecommendationCandidateProjection | None,
    source_info: dict,
) -> dict:
    if projection is None and not source_info:
        return {}

    query_features = _feature_briefs(projection, "query")
    memory_features = _feature_briefs(projection, "long_term_memory")
    behavior_features = [
        *_feature_briefs(projection, "recommendation_event"),
        *_feature_briefs(projection, "book_interaction"),
    ]
    source_features = _feature_briefs(projection, "candidate_source")
    contribution_sources = []
    if source_info:
        contribution_sources.append(source_info.get("candidate_source") or "candidate_source")
    if source_features:
        contribution_sources.append("candidate_source")
    if query_features:
        contribution_sources.append("query")
    if memory_features:
        contribution_sources.append("long_term_memory")
    if behavior_features:
        contribution_sources.append("behavior_signal")

    summary_parts = []
    source_label = _candidate_source_label(source_info)
    if source_label:
        summary_parts.append(f"candidate source: {source_label}")
    if projection is not None:
        if projection.positive_reasons:
            summary_parts.append(f"positive: {projection.positive_reasons[0]}")
        if projection.negative_reasons:
            summary_parts.append(f"caution: {projection.negative_reasons[0]}")
        if projection.suppressed and projection.suppression_reasons:
            summary_parts.append(
                f"suppressed: {', '.join(projection.suppression_reasons[:3])}"
            )

    return {
        "contract_version": RECOMMENDATION_EXPLANATION_CONTRACT_VERSION,
        "book_id": str(getattr(book, "id", "")),
        "book_title": getattr(book, "title", ""),
        "summary": "; ".join(summary_parts),
        "candidate_source": source_info,
        "contribution_sources": _unique_strings(contribution_sources),
        "score": projection.score if projection is not None else None,
        "score_breakdown": (
            {
                "base_score": projection.base_score,
                "source_score": projection.source_score,
                "query_score": projection.query_score,
                "memory_score": projection.memory_score,
                "behavior_score": projection.behavior_score,
            }
            if projection is not None
            else {}
        ),
        "positive_reasons": projection.positive_reasons[:5] if projection else [],
        "negative_reasons": projection.negative_reasons[:5] if projection else [],
        "suppression_reasons": projection.suppression_reasons[:5] if projection else [],
        "features": {
            "query": query_features,
            "candidate_source": source_features,
            "long_term_memory": memory_features,
            "behavior": behavior_features,
        },
    }


def _feature_briefs(
    projection: RecommendationCandidateProjection | None,
    source: str,
) -> list[dict]:
    if projection is None:
        return []
    return [
        {
            "source": feature.source,
            "key": feature.key,
            "value": feature.value,
            "score_delta": feature.score_delta,
            "reason": feature.reason,
        }
        for feature in projection.features
        if feature.source == source
    ][:8]


def _candidate_source_label(source_info: dict) -> str:
    source = str(source_info.get("candidate_source") or "").strip()
    if source == "book_cache":
        return "local Book Cache"
    if source == "external_search":
        provider = str(source_info.get("source") or "external search").strip()
        return provider
    return source


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def reset_search_books_guard() -> None:
    """Reset ordinary-search loop guard. Intended for verification scripts."""
    reset_tool_admission_gate()


def _intent_blocked_payload(
    query: str,
    limit: int,
    user_message: str,
    admission: ToolAdmissionResult,
) -> dict:
    return {
        "status": "intent_blocked",
        "result_mode": "ordinary_recommendation",
        "query": query,
        "books": [],
        "result_count": 0,
        "source": "ordinary_recommendation_intent_gate",
        "next_action_hint": get_book_search_hint("intent_blocked"),
        "error": None,
        "duration_ms": 0,
        "requested_limit": limit,
        "metadata": {
            "reason": "explicit_recommendation_or_search_intent_required",
            "user_message": user_message,
            "tool_admission": admission.model_dump(mode="json"),
        },
    }


def _loop_detected_payload(
    query: str,
    limit: int,
    admission: ToolAdmissionResult,
) -> dict:
    return {
        "status": "loop_detected",
        "result_mode": "ordinary_recommendation",
        "query": query,
        "books": [],
        "result_count": 0,
        "source": "ordinary_recommendation_guard",
        "next_action_hint": (
            "A search has already been attempted in this ordinary recommendation "
            "turn. Stop searching and answer from current memory, existing search "
            "results, and general book knowledge."
        ),
        "error": None,
        "duration_ms": 0,
        "requested_limit": limit,
        "metadata": {
            "tool_admission": admission.model_dump(mode="json"),
        },
    }


def _tool_blocked_payload(
    tool_name: str,
    admission: ToolAdmissionResult,
) -> dict:
    return {
        "status": admission.blocked_status or "tool_blocked",
        "tool_name": tool_name,
        "tool_admission": admission.model_dump(mode="json"),
    }


def _book_turn_plan_blocked_payload(
    admission: ToolAdmissionResult,
    user_message: str,
    query: str,
) -> dict:
    return {
        "status": admission.blocked_status or "tool_blocked",
        "result_mode": "book_turn_orchestration",
        "contract_version": BOOK_TURN_ORCHESTRATION_CONTRACT_VERSION,
        "route": "answer_question",
        "query": query,
        "user_message": user_message,
        "recommended_next_tools": [],
        "metadata": {
            "tool_admission": admission.model_dump(mode="json"),
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "writes_research_state": False,
            "writes_evidence": False,
            "external_call": False,
        },
    }


def _history_tool_blocked_payload(
    user_id: UUID,
    history_mode: str,
    query: str,
    book_title: str,
    admission: ToolAdmissionResult,
) -> dict:
    return {
        "status": admission.blocked_status or "tool_blocked",
        "result_mode": "recommendation_history",
        "history_mode": normalize_recommendation_history_mode(history_mode),
        "user_id": str(user_id),
        "query": query,
        "book_title": book_title,
        "records": [],
        "suppressed_records": [],
        "result_count": 0,
        "next_action_hint": (
            "Recommendation history is available only for explicit history or "
            "suppression-explanation turns."
        ),
        "metadata": {
            "tool_admission": admission.model_dump(mode="json"),
            "allowed_history_modes": sorted(RECOMMENDATION_HISTORY_MODES),
        },
    }


@tool(args_schema=PlanBookAssistantTurnInput)
async def plan_book_assistant_turn(
    user_id: UUID | None = None,
    user_message: str = "",
    query: str = "",
    candidates: list[dict] | None = None,
    research_report: dict | None = None,
    research_state: dict | None = None,
    book_title: str = "",
    metadata: dict | None = None,
) -> str:
    """Plan the app-owned route for this book assistant turn without side effects."""
    current_message = user_message or get_current_user_message()
    admission = get_tool_admission_gate().admit_current_turn(
        PLAN_BOOK_ASSISTANT_TURN_TOOL_POLICY
    )
    if not admission.allowed:
        return json.dumps(
            _book_turn_plan_blocked_payload(admission, current_message, query),
            ensure_ascii=False,
        )

    db = get_database()
    async with db.session() as session:
        result = await plan_book_assistant_turn_result(
            session,
            user_message=current_message,
            query=query,
            user_id=user_id,
            candidates=candidates or [],
            research_report=research_report or {},
            research_state=research_state or {},
            book_title=book_title,
            metadata=metadata,
        )
    payload = result.model_dump(mode="json")
    payload["metadata"]["tool_admission"] = admission.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False)


async def _search_books_impl(
    query: str,
    limit: int = 5,
    user_id: UUID | None = None,
    allow_additional_search: bool = False,
) -> str:
    user_message = get_current_user_message()
    admission = get_tool_admission_gate().admit_current_turn(
        SEARCH_BOOKS_TOOL_POLICY,
        bypass_budget=allow_additional_search,
    )
    if not admission.allowed and admission.blocked_status == "loop_detected":
        return json.dumps(
            _loop_detected_payload(query, limit, admission),
            ensure_ascii=False,
        )
    if not admission.allowed:
        return json.dumps(
            _intent_blocked_payload(query, limit, user_message, admission),
            ensure_ascii=False,
        )

    db = get_database()
    effective_query = query
    constraints_payload: dict = {}
    constraints_error: str | None = None
    async with db.session() as session:
        if user_id is not None:
            try:
                constraints = await build_personalized_recommendation_constraints(
                    session,
                    user_id=user_id,
                    query=query,
                )
                effective_query = constraints.effective_query or query
                constraints_payload = constraints.model_dump(mode="json")
            except Exception as exc:
                constraints_error = str(exc)

        result = await search_and_cache_books_with_status(
            session,
            query=effective_query,
            limit=limit,
        )
        books_for_answer = list(result.books)
        projection_payload: dict = {}
        projections_by_book_id: dict[str, RecommendationCandidateProjection] = {}
        if user_id is not None and books_for_answer:
            projection = await RecommendationProjector(session).project_books(
                user_id=user_id,
                query=query,
                books=books_for_answer,
                candidate_sources=result.candidate_sources,
            )
            projection_payload = projection.model_dump(mode="json")
            projections_by_book_id = {
                str(candidate.book_id): candidate
                for candidate in projection.candidates
                if candidate.book_id is not None
            }
            book_by_id = {str(book.id): book for book in books_for_answer}
            books_for_answer = [
                book_by_id[str(candidate.book_id)]
                for candidate in projection.candidates
                if candidate.book_id is not None and str(candidate.book_id) in book_by_id
            ]

    book_payloads = [
        _book_to_dict(
            book,
            projections_by_book_id.get(str(book.id)),
            result.candidate_sources.get(str(book.id)),
        )
        for book in books_for_answer
    ]
    payload = {
        "status": result.status,
        "result_mode": "ordinary_recommendation",
        "query": query,
        "effective_query": effective_query,
        "books": book_payloads,
        "result_count": len(book_payloads),
        "source": result.source,
        "next_action_hint": result.next_action_hint,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "requested_limit": limit,
        "follow_up_questions": [
            question.model_dump(mode="json")
            for question in build_follow_up_questions(query=query, books=book_payloads)
        ],
        "metadata": {
            "tool_admission": admission.model_dump(mode="json"),
            "search": {
                "requested_query": query,
                "effective_query": effective_query,
                "provider_result_query": result.query,
                "cache": result.metadata,
                "candidate_sources": result.candidate_sources,
            },
            "personalization": {
                "user_id": str(user_id) if user_id else None,
                "constraints": constraints_payload,
                "constraints_error": constraints_error,
                "projection": projection_payload,
                "suppressed_books": (
                    projection_payload.get("suppressed_candidates", [])
                    if projection_payload
                    else []
                ),
            },
        },
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=BookSearchInput)
async def search_books(
    query: str,
    limit: int = 5,
    user_id: UUID | None = None,
    allow_additional_search: bool = False,
) -> str:
    """Search public web results for books and cache them locally."""
    return await _search_books_impl(
        query=query,
        limit=limit,
        user_id=user_id,
        allow_additional_search=allow_additional_search,
    )


async def _get_recommendation_history_impl(
    user_id: UUID,
    history_mode: str = "all",
    query: str = "",
    book_title: str = "",
    limit: int = 20,
) -> str:
    admission = get_tool_admission_gate().admit_current_turn(
        GET_RECOMMENDATION_HISTORY_TOOL_POLICY
    )
    if not admission.allowed:
        return json.dumps(
            _history_tool_blocked_payload(
                user_id,
                history_mode,
                query,
                book_title,
                admission,
            ),
            ensure_ascii=False,
        )

    db = get_database()
    async with db.session() as session:
        result = await get_recommendation_history_result(
            session,
            user_id=user_id,
            history_mode=history_mode,
            query=query,
            book_title=book_title,
            limit=limit,
        )
    payload = result.model_dump(mode="json")
    payload["metadata"]["tool_admission"] = admission.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=GetRecommendationHistoryInput)
async def get_recommendation_history(
    user_id: UUID,
    history_mode: str = "all",
    query: str = "",
    book_title: str = "",
    limit: int = 20,
) -> str:
    """Read recommendation history or suppression explanations without side effects."""
    return await _get_recommendation_history_impl(
        user_id=user_id,
        history_mode=history_mode,
        query=query,
        book_title=book_title,
        limit=limit,
    )


@tool(args_schema=RememberReadingPreferenceInput)
async def remember_reading_preference(
    user_id: UUID,
    preferred_tags: list[str] | None = None,
    disliked_tags: list[str] | None = None,
    favorite_authors: list[str] | None = None,
    disliked_authors: list[str] | None = None,
    note: str = "",
    profile_summary: str = "",
) -> str:
    """Persist long-term reading preferences for future recommendations."""
    admission = get_tool_admission_gate().admit_current_turn(
        REMEMBER_READING_PREFERENCE_TOOL_POLICY
    )
    if not admission.allowed:
        return json.dumps(
            _tool_blocked_payload("remember_reading_preference", admission),
            ensure_ascii=False,
        )

    orchestrator = get_memory_orchestrator()
    metadata = {
        key: value
        for key, value in {"note": note, "profile_summary": profile_summary}.items()
        if value
    }

    source_text = note or profile_summary
    candidates: list[MemoryCandidate] = []
    for value in preferred_tags or []:
        candidates.append(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="tag",
                value=value,
                polarity="like",
                source_text=source_text,
                source_kind="user_message",
                metadata=metadata,
            )
        )
    for value in disliked_tags or []:
        candidates.append(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="tag",
                value=value,
                polarity="dislike",
                source_text=source_text,
                source_kind="user_message",
                metadata=metadata,
            )
        )
    for value in favorite_authors or []:
        candidates.append(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="author",
                value=value,
                polarity="like",
                source_text=source_text,
                source_kind="user_message",
                metadata=metadata,
            )
        )
    for value in disliked_authors or []:
        candidates.append(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="author",
                value=value,
                polarity="dislike",
                source_text=source_text,
                source_kind="user_message",
                metadata=metadata,
            )
        )

    if not candidates and (note or profile_summary):
        candidates.append(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="user",
                value=note or profile_summary,
                polarity="neutral",
                source_text=source_text,
                source_kind="user_message",
                metadata=metadata,
            )
        )

    admission_results = [
        await orchestrator.remember_candidate(candidate) for candidate in candidates
    ]
    saved = [result.memory for result in admission_results if result.memory is not None]
    profile = await orchestrator.search_memory(user_id=user_id, limit=20)

    return json.dumps(
        {
            "saved_events": [event.model_dump(mode="json") for event in saved],
            "admissions": [
                result.decision.model_dump(mode="json") for result in admission_results
            ],
            "conflicts": [
                [
                    conflict.model_dump(mode="json")
                    for conflict in result.conflicts
                ]
                for result in admission_results
            ],
            "profile": profile.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )


@tool(args_schema=RecordBookFeedbackInput)
async def record_book_feedback(
    user_id: UUID,
    book_title: str,
    interaction_type: str,
    thread_id: UUID | None = None,
    note: str = "",
    rating: int | None = None,
) -> str:
    """Record user feedback on a recommended or mentioned book."""
    tool_admission = get_tool_admission_gate().admit_current_turn(
        RECORD_BOOK_FEEDBACK_TOOL_POLICY
    )
    if not tool_admission.allowed:
        return json.dumps(
            _tool_blocked_payload("record_book_feedback", tool_admission),
            ensure_ascii=False,
        )

    db = get_database()
    async with db.session() as session:
        book = await find_book_by_title(session, book_title)
        interaction = await create_book_interaction(
            session,
            BookInteractionCreate(
                user_id=user_id,
                book_id=book.id if book else None,
                book_title=book.title if book else book_title,
                interaction_type=interaction_type,
                note=note or None,
                rating=rating,
            ),
        )
        signal_plan = map_interaction_to_recommendation_signal(interaction_type)
        recommendation_event = await create_recommendation_event(
            session,
            RecommendationSignalCreate(
                user_id=user_id,
                thread_id=thread_id,
                book_id=book.id if book else None,
                book_title=interaction.book_title or book_title,
                event_type=signal_plan.event_type,
                signal_polarity=signal_plan.signal_polarity,
                signal_strength=signal_plan.signal_strength,
                request_id=get_request_id() if get_request_id() != "-" else "",
                source="book_feedback",
                metadata={
                    "interaction_id": str(interaction.id),
                    "interaction_type": interaction.interaction_type,
                    "note": note,
                    "rating": rating,
                    "writes_long_term_memory": signal_plan.writes_long_term_memory,
                },
            ),
        )

        # The generic memory event below mirrors this feedback into long-term memory.

    normalized_type = interaction_type.strip().lower().replace(" ", "_")
    memory_type = (
        "reading_state"
        if normalized_type in {"want", "want_to_read", "to_read", "read", "finished"}
        else "feedback"
    )
    polarity_map = {
        "want": "want",
        "want_to_read": "want",
        "to_read": "want",
        "read": "read",
        "finished": "read",
        "like": "like",
        "liked": "like",
        "similar": "like",
        "dislike": "dislike",
        "disliked": "dislike",
        "not_interested": "avoid",
        "avoid": "avoid",
    }
    admission_result = await get_memory_orchestrator().remember_candidate(
        MemoryCandidate(
            user_id=user_id,
            type=memory_type,
            subject="book",
            value=interaction.book_title or book_title,
            polarity=polarity_map.get(normalized_type, "neutral"),
            thread_id=thread_id,
            source_kind="book_feedback",
            source_text=note or normalized_type,
            metadata={
                "interaction_id": str(interaction.id),
                "interaction_type": normalized_type,
                "note": note,
                "rating": rating,
            },
        )
    )
    saved_memory = admission_result.memory

    return json.dumps(
        {
            "id": str(interaction.id),
            "user_id": str(interaction.user_id),
            "book_id": str(interaction.book_id) if interaction.book_id else None,
            "book_title": interaction.book_title,
            "interaction_type": interaction.interaction_type,
            "rating": interaction.rating,
            "memory_event_id": (
                str(saved_memory.id) if saved_memory and saved_memory.id else None
            ),
            "recommendation_event": recommendation_signal_from_record(
                recommendation_event
            ).model_dump(mode="json"),
            "memory_admission": admission_result.decision.model_dump(mode="json"),
            "memory_conflicts": [
                conflict.model_dump(mode="json")
                for conflict in admission_result.conflicts
            ],
            "tool_admission": tool_admission.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )


@tool(args_schema=RecordRecommendationSignalInput)
async def record_recommendation_signal(
    user_id: UUID,
    event_type: str,
    thread_id: UUID | None = None,
    book_title: str = "",
    signal_polarity: str = "neutral",
    signal_strength: float = 0.0,
    source: str = "agent_tool",
    note: str = "",
    metadata: dict | None = None,
) -> str:
    """Record a recommendation behavior signal without writing long-term memory."""
    tool_admission = get_tool_admission_gate().admit_current_turn(
        RECORD_RECOMMENDATION_SIGNAL_TOOL_POLICY
    )
    if not tool_admission.allowed:
        return json.dumps(
            _tool_blocked_payload("record_recommendation_signal", tool_admission),
            ensure_ascii=False,
        )

    event_metadata = dict(metadata or {})
    if note:
        event_metadata["note"] = note
    event_metadata["writes_long_term_memory"] = False

    db = get_database()
    async with db.session() as session:
        book = await find_book_by_title(session, book_title) if book_title else None
        saved = await create_recommendation_event(
            session,
            RecommendationSignalCreate(
                user_id=user_id,
                thread_id=thread_id,
                book_id=book.id if book else None,
                book_title=book.title if book else book_title,
                event_type=event_type,
                signal_polarity=signal_polarity,
                signal_strength=signal_strength,
                request_id=get_request_id() if get_request_id() != "-" else "",
                source=source,
                metadata=event_metadata,
            ),
        )

    return json.dumps(
        {
            "recommendation_event": recommendation_signal_from_record(saved).model_dump(
                mode="json"
            ),
            "tool_admission": tool_admission.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
