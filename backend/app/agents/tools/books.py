"""Book recommendation tools for the supervisor agent."""

from __future__ import annotations

import asyncio
import json
import time
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.crud.book import (
    create_book_interaction,
    find_book_by_title,
)
from app.infra.database import get_database
from app.schemas.book import BookInteractionCreate
from app.services.book_search import search_and_cache_books_with_status
from app.services.memory import MemoryEvent, get_memory_orchestrator
from app.utils.logging import get_request_id

_SEARCH_BOOKS_GUARD_TTL_SECONDS = 15 * 60
_search_books_turn_guard: dict[str, float] = {}


class BookSearchInput(BaseModel):
    query: str = Field(
        description="Book recommendation/search query, including genre, mood, author, or constraints."
    )
    limit: int = Field(default=5, ge=1, le=10, description="Maximum books to return.")
    allow_additional_search: bool = Field(
        default=False,
        description=(
            "Set true only when the user explicitly asks for another search, "
            "a refined search, or a separate search in the same turn. Keep false "
            "for ordinary recommendations."
        ),
    )


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
    note: str = Field(default="", description="Optional feedback note.")
    rating: int | None = Field(default=None, ge=1, le=5)


def _book_to_dict(book) -> dict:
    return {
        "id": str(book.id),
        "title": book.title,
        "authors": book.authors or [],
        "summary": book.summary,
        "rating": float(book.rating) if book.rating is not None else None,
        "source_name": book.source_name,
        "source_url": book.source_url,
        "external_id": book.external_id,
    }


def reset_search_books_guard() -> None:
    """Reset ordinary-search loop guard. Intended for verification scripts."""
    _search_books_turn_guard.clear()


def _current_search_guard_key() -> str:
    request_id = get_request_id()
    if request_id and request_id != "-":
        return f"request:{request_id}"

    task = asyncio.current_task()
    if task is not None:
        return f"task:{id(task)}"
    return "process"


def _cleanup_search_guard(now: float) -> None:
    expired = [
        key
        for key, seen_at in _search_books_turn_guard.items()
        if now - seen_at > _SEARCH_BOOKS_GUARD_TTL_SECONDS
    ]
    for key in expired:
        _search_books_turn_guard.pop(key, None)


def _mark_or_detect_repeated_search(allow_additional_search: bool) -> bool:
    if allow_additional_search:
        return False

    now = time.monotonic()
    _cleanup_search_guard(now)
    key = _current_search_guard_key()
    if key in _search_books_turn_guard:
        return True
    _search_books_turn_guard[key] = now
    return False


def _loop_detected_payload(query: str, limit: int) -> dict:
    return {
        "status": "loop_detected",
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
    }


async def _search_books_impl(
    query: str,
    limit: int = 5,
    allow_additional_search: bool = False,
) -> str:
    if _mark_or_detect_repeated_search(allow_additional_search):
        return json.dumps(_loop_detected_payload(query, limit), ensure_ascii=False)

    db = get_database()
    async with db.session() as session:
        result = await search_and_cache_books_with_status(
            session,
            query=query,
            limit=limit,
        )

    payload = {
        "status": result.status,
        "query": query,
        "books": [_book_to_dict(book) for book in result.books],
        "result_count": result.result_count,
        "source": result.source,
        "next_action_hint": result.next_action_hint,
        "error": result.error,
        "duration_ms": result.duration_ms,
        "requested_limit": limit,
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=BookSearchInput)
async def search_books(
    query: str,
    limit: int = 5,
    allow_additional_search: bool = False,
) -> str:
    """Search public web results for books and cache them locally."""
    return await _search_books_impl(
        query=query,
        limit=limit,
        allow_additional_search=allow_additional_search,
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
    orchestrator = get_memory_orchestrator()
    metadata = {
        key: value
        for key, value in {"note": note, "profile_summary": profile_summary}.items()
        if value
    }

    events: list[MemoryEvent] = []
    for value in preferred_tags or []:
        events.append(
            MemoryEvent(
                user_id=user_id,
                type="preference",
                subject="tag",
                value=value,
                polarity="like",
                metadata=metadata,
            )
        )
    for value in disliked_tags or []:
        events.append(
            MemoryEvent(
                user_id=user_id,
                type="preference",
                subject="tag",
                value=value,
                polarity="dislike",
                metadata=metadata,
            )
        )
    for value in favorite_authors or []:
        events.append(
            MemoryEvent(
                user_id=user_id,
                type="preference",
                subject="author",
                value=value,
                polarity="like",
                metadata=metadata,
            )
        )
    for value in disliked_authors or []:
        events.append(
            MemoryEvent(
                user_id=user_id,
                type="preference",
                subject="author",
                value=value,
                polarity="dislike",
                metadata=metadata,
            )
        )

    if not events and (note or profile_summary):
        events.append(
            MemoryEvent(
                user_id=user_id,
                type="preference",
                subject="user",
                value=note or profile_summary,
                polarity="neutral",
                metadata=metadata,
            )
        )

    saved = [await orchestrator.remember_memory(event) for event in events]
    profile = await orchestrator.search_memory(user_id=user_id, limit=20)

    return json.dumps(
        {
            "saved_events": [event.model_dump(mode="json") for event in saved],
            "profile": profile.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )


@tool(args_schema=RecordBookFeedbackInput)
async def record_book_feedback(
    user_id: UUID,
    book_title: str,
    interaction_type: str,
    note: str = "",
    rating: int | None = None,
) -> str:
    """Record user feedback on a recommended or mentioned book."""
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
    saved_memory = await get_memory_orchestrator().remember_memory(
        MemoryEvent(
            user_id=user_id,
            type=memory_type,
            subject="book",
            value=interaction.book_title or book_title,
            polarity=polarity_map.get(normalized_type, "neutral"),
            metadata={
                "interaction_id": str(interaction.id),
                "interaction_type": normalized_type,
                "note": note,
                "rating": rating,
            },
        )
    )

    return json.dumps(
        {
            "id": str(interaction.id),
            "user_id": str(interaction.user_id),
            "book_id": str(interaction.book_id) if interaction.book_id else None,
            "book_title": interaction.book_title,
            "interaction_type": interaction.interaction_type,
            "rating": interaction.rating,
            "memory_event_id": str(saved_memory.id) if saved_memory.id else None,
        },
        ensure_ascii=False,
    )
