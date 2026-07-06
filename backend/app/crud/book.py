from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book, BookInteraction, RecommendationEvent, UserPreferenceProfile
from app.models.base import utc_now
from app.schemas.book import BookInteractionCreate, UserPreferenceProfileUpdate
from app.services.recommendation_signals import (
    RecommendationSignalCreate,
    SUPPRESSION_EVENT_TYPES,
    normalize_recommendation_text,
)


def _clean_list(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = str(value).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def _merge_list(existing: Iterable[str] | None, incoming: Iterable[str] | None) -> list[str]:
    return _clean_list([*(existing or []), *(incoming or [])])


async def list_books(
    db: AsyncSession,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Book]:
    stmt = select(Book).order_by(Book.last_seen_at.desc()).offset(offset).limit(limit)
    if query:
        pattern = f"%{query.strip()}%"
        stmt = (
            select(Book)
            .where(
                or_(
                    Book.title.ilike(pattern),
                    Book.summary.ilike(pattern),
                    Book.source_url.ilike(pattern),
                )
            )
            .order_by(Book.last_seen_at.desc())
            .offset(offset)
            .limit(limit)
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_book(db: AsyncSession, book_id: UUID) -> Book | None:
    result = await db.execute(select(Book).where(Book.id == book_id))
    return result.scalar_one_or_none()


async def get_book_by_source_url(db: AsyncSession, source_url: str) -> Book | None:
    result = await db.execute(select(Book).where(Book.source_url == source_url))
    return result.scalar_one_or_none()


async def find_book_by_title(db: AsyncSession, title: str) -> Book | None:
    result = await db.execute(
        select(Book)
        .where(Book.title.ilike(title.strip()))
        .order_by(Book.last_seen_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def upsert_book(db: AsyncSession, data: dict) -> Book:
    source_url = data.get("source_url")
    existing = await get_book_by_source_url(db, source_url) if source_url else None

    normalized = {
        **data,
        "authors": _clean_list(data.get("authors")),
        "tags": _clean_list(data.get("tags")),
        "raw_data": data.get("raw_data") or {},
    }

    if existing is not None:
        for key, value in normalized.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        existing.last_seen_at = utc_now()
        await db.flush()
        await db.refresh(existing)
        return existing

    book = Book(**normalized)
    db.add(book)
    await db.flush()
    await db.refresh(book)
    return book


async def create_book_interaction(
    db: AsyncSession,
    interaction: BookInteractionCreate,
) -> BookInteraction:
    data = interaction.model_dump()
    obj = BookInteraction(**data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def create_recommendation_event(
    db: AsyncSession,
    signal: RecommendationSignalCreate,
) -> RecommendationEvent:
    data = signal.model_dump()
    data["metadata_json"] = data.pop("metadata", {})
    if data.get("book_title"):
        data["book_title"] = normalize_recommendation_text(data["book_title"])
    obj = RecommendationEvent(**data)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def list_recommendation_events(
    db: AsyncSession,
    *,
    user_id: UUID,
    book_title: str = "",
    event_types: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[RecommendationEvent]:
    stmt = select(RecommendationEvent).where(RecommendationEvent.user_id == user_id)
    if book_title.strip():
        stmt = stmt.where(
            func.lower(RecommendationEvent.book_title) == book_title.strip().lower()
        )
    if event_types:
        stmt = stmt.where(RecommendationEvent.event_type.in_(event_types))
    result = await db.execute(
        stmt.order_by(RecommendationEvent.created_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 100)))
    )
    return list(result.scalars().all())


async def get_suppressed_book_titles(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> set[str]:
    interaction_types = {
        "read",
        "finished",
        "already_read",
        "dislike",
        "disliked",
        "not_interested",
        "avoid",
    }
    titles: set[str] = set()

    interaction_result = await db.execute(
        select(BookInteraction.book_title).where(
            BookInteraction.user_id == user_id,
            BookInteraction.book_title.is_not(None),
            BookInteraction.interaction_type.in_(interaction_types),
        )
    )
    for title in interaction_result.scalars().all():
        normalized = normalize_recommendation_text(title).lower()
        if normalized:
            titles.add(normalized)

    event_result = await db.execute(
        select(RecommendationEvent.book_title).where(
            RecommendationEvent.user_id == user_id,
            RecommendationEvent.book_title.is_not(None),
            RecommendationEvent.event_type.in_(list(SUPPRESSION_EVENT_TYPES)),
        )
    )
    for title in event_result.scalars().all():
        normalized = normalize_recommendation_text(title).lower()
        if normalized:
            titles.add(normalized)

    return titles


async def get_or_create_preference_profile(
    db: AsyncSession,
    user_id: UUID,
) -> UserPreferenceProfile:
    result = await db.execute(
        select(UserPreferenceProfile).where(UserPreferenceProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is not None:
        return profile

    profile = UserPreferenceProfile(user_id=user_id)
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


async def update_preference_profile(
    db: AsyncSession,
    user_id: UUID,
    update: UserPreferenceProfileUpdate,
) -> UserPreferenceProfile:
    profile = await get_or_create_preference_profile(db, user_id)
    data = update.model_dump(exclude_unset=True, exclude={"merge"})
    merge = update.merge

    list_fields = {
        "preferred_tags",
        "disliked_tags",
        "favorite_authors",
        "disliked_authors",
    }

    for key, value in data.items():
        if value is None:
            continue
        if key in list_fields:
            current = getattr(profile, key)
            setattr(profile, key, _merge_list(current, value) if merge else _clean_list(value))
        elif key == "notes" and merge and getattr(profile, "notes", ""):
            setattr(profile, key, f"{profile.notes}\n{value}".strip())
        else:
            setattr(profile, key, value)

    await db.flush()
    await db.refresh(profile)
    return profile
