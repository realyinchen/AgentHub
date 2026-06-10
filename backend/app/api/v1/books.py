"""Book and reading preference endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud.book import (
    create_book_interaction,
    get_book,
    get_or_create_preference_profile,
    list_books,
    update_preference_profile,
)
from app.schemas.book import (
    BookInDB,
    BookInteractionCreate,
    BookInteractionInDB,
    BookSearchResponse,
    UserPreferenceProfileInDB,
    UserPreferenceProfileUpdate,
)
from app.services.book_search import search_and_cache_books

api_router = APIRouter(prefix="/books", tags=["Books"])


@api_router.get("", response_model=list[BookInDB])
async def get_books(
    query: str | None = Query(default=None, description="Search local cached books"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[BookInDB]:
    books = await list_books(db=db, query=query, limit=limit, offset=offset)
    return [BookInDB.model_validate(book) for book in books]


@api_router.get("/search", response_model=BookSearchResponse)
async def search_books(
    query: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(default=5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
) -> BookSearchResponse:
    books = await search_and_cache_books(db=db, query=query, limit=limit)
    return BookSearchResponse(
        query=query,
        books=[BookInDB.model_validate(book) for book in books],
    )


@api_router.post("/interactions", response_model=BookInteractionInDB)
async def save_book_interaction(
    interaction: BookInteractionCreate,
    db: AsyncSession = Depends(get_db),
) -> BookInteractionInDB:
    saved = await create_book_interaction(db=db, interaction=interaction)
    return BookInteractionInDB.model_validate(saved)


@api_router.get("/preferences/{user_id}", response_model=UserPreferenceProfileInDB)
async def get_reading_preferences(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> UserPreferenceProfileInDB:
    profile = await get_or_create_preference_profile(db=db, user_id=user_id)
    return UserPreferenceProfileInDB.model_validate(profile)


@api_router.patch("/preferences/{user_id}", response_model=UserPreferenceProfileInDB)
async def update_reading_preferences(
    user_id: UUID,
    update: UserPreferenceProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> UserPreferenceProfileInDB:
    profile = await update_preference_profile(db=db, user_id=user_id, update=update)
    return UserPreferenceProfileInDB.model_validate(profile)


@api_router.get("/{book_id}", response_model=BookInDB | None)
async def read_book(
    book_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> BookInDB | None:
    book = await get_book(db=db, book_id=book_id)
    return BookInDB.model_validate(book) if book else None
