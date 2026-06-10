"""Book recommendation tools for the supervisor agent."""

from __future__ import annotations

import json
from uuid import UUID

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.crud.book import (
    create_book_interaction,
    find_book_by_title,
    get_or_create_preference_profile,
    update_preference_profile,
)
from app.infra.database import get_database
from app.schemas.book import BookInteractionCreate, UserPreferenceProfileUpdate
from app.services.book_search import search_and_cache_books


class BookSearchInput(BaseModel):
    query: str = Field(
        description="Book recommendation/search query, including genre, mood, author, or constraints."
    )
    limit: int = Field(default=5, ge=1, le=10, description="Maximum books to return.")


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


@tool(args_schema=BookSearchInput)
async def search_books(query: str, limit: int = 5) -> str:
    """Search public web results for books and cache them locally."""
    db = get_database()
    async with db.session() as session:
        books = await search_and_cache_books(session, query=query, limit=limit)

    if not books:
        return "No book candidates found. Try a more specific title, author, genre, or mood."

    payload = [_book_to_dict(book) for book in books]
    return json.dumps(payload, ensure_ascii=False)


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
    db = get_database()
    update = UserPreferenceProfileUpdate(
        preferred_tags=preferred_tags or None,
        disliked_tags=disliked_tags or None,
        favorite_authors=favorite_authors or None,
        disliked_authors=disliked_authors or None,
        notes=note or None,
        profile_summary=profile_summary or None,
        merge=True,
    )
    async with db.session() as session:
        profile = await update_preference_profile(session, user_id=user_id, update=update)

    return json.dumps(
        {
            "user_id": str(profile.user_id),
            "preferred_tags": profile.preferred_tags,
            "disliked_tags": profile.disliked_tags,
            "favorite_authors": profile.favorite_authors,
            "disliked_authors": profile.disliked_authors,
            "profile_summary": profile.profile_summary,
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

        # Ensure a profile row exists even if the feedback itself is unstructured.
        await get_or_create_preference_profile(session, user_id)

    return json.dumps(
        {
            "id": str(interaction.id),
            "user_id": str(interaction.user_id),
            "book_id": str(interaction.book_id) if interaction.book_id else None,
            "book_title": interaction.book_title,
            "interaction_type": interaction.interaction_type,
            "rating": interaction.rating,
        },
        ensure_ascii=False,
    )
