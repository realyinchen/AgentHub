from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.memory.contracts import MemoryEvent
from app.services.memory.providers.postgres import PostgresMemoryProvider


CONSTRAINTS_CONTRACT_VERSION = "personalized-recommendation-constraints-v1"
_PROFILE_TYPES = {"preference", "correction"}
_LIKE_POLARITIES = {"like", "want"}
_DISLIKE_POLARITIES = {"dislike", "avoid"}
_TAG_SUBJECTS = {"tag", "theme", "style", "genre", "mood", "pacing", "content"}
_AUTHOR_SUBJECTS = {"author"}
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.IGNORECASE)
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "book",
    "books",
    "for",
    "i",
    "me",
    "novel",
    "novels",
    "of",
    "or",
    "please",
    "recommend",
    "the",
    "to",
}


class PersonalizedRecommendationConstraints(BaseModel):
    """CurrentMemory-derived constraints for ordinary recommendations."""

    user_id: UUID
    original_query: str = ""
    effective_query: str = ""
    preferred_terms: list[str] = Field(default_factory=list)
    avoided_terms: list[str] = Field(default_factory=list)
    favorite_authors: list[str] = Field(default_factory=list)
    disliked_authors: list[str] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    search_terms_added: list[str] = Field(default_factory=list)
    applied_to_search: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


async def build_personalized_recommendation_constraints(
    session: AsyncSession,
    *,
    user_id: UUID,
    query: str,
    max_search_terms: int = 3,
) -> PersonalizedRecommendationConstraints:
    provider = PostgresMemoryProvider(session)
    current = await provider.list_current(
        user_id=user_id,
        query="",
        memory_types=sorted(_PROFILE_TYPES),
        limit=100,
    )
    constraints = _constraints_from_memories(
        user_id=user_id,
        query=query,
        memories=current.memories,
    )
    _apply_search_query_constraints(
        constraints,
        max_search_terms=max_search_terms,
    )
    return constraints


def _constraints_from_memories(
    *,
    user_id: UUID,
    query: str,
    memories: list[MemoryEvent],
) -> PersonalizedRecommendationConstraints:
    constraints = PersonalizedRecommendationConstraints(
        user_id=user_id,
        original_query=query,
        effective_query=query,
        source_memory_ids=[str(memory.id) for memory in memories if memory.id],
        metadata={
            "contract_version": CONSTRAINTS_CONTRACT_VERSION,
            "constraint_source": "current_memory",
            "current_memory_count": len(memories),
        },
    )
    for memory in memories:
        if memory.type not in _PROFILE_TYPES:
            continue
        value = memory.value.strip()
        if not value:
            continue
        if memory.subject in _AUTHOR_SUBJECTS:
            if memory.polarity in _LIKE_POLARITIES:
                constraints.favorite_authors = _add_unique(
                    constraints.favorite_authors,
                    value,
                )
            elif memory.polarity in _DISLIKE_POLARITIES:
                constraints.disliked_authors = _add_unique(
                    constraints.disliked_authors,
                    value,
                )
        elif memory.subject in _TAG_SUBJECTS:
            if memory.polarity in _LIKE_POLARITIES:
                constraints.preferred_terms = _add_unique(
                    constraints.preferred_terms,
                    value,
                )
            elif memory.polarity in _DISLIKE_POLARITIES:
                constraints.avoided_terms = _add_unique(
                    constraints.avoided_terms,
                    value,
                )
    return constraints


def _apply_search_query_constraints(
    constraints: PersonalizedRecommendationConstraints,
    *,
    max_search_terms: int,
) -> None:
    additions: list[str] = []
    for value in [*constraints.favorite_authors, *constraints.preferred_terms]:
        if len(additions) >= max(0, max_search_terms):
            break
        if _is_redundant_query_term(value, constraints.original_query):
            continue
        additions.append(value)

    constraints.search_terms_added = additions
    constraints.applied_to_search = bool(additions)
    if additions:
        constraints.effective_query = " ".join(
            item for item in [constraints.original_query.strip(), *additions] if item
        )
    else:
        constraints.effective_query = constraints.original_query


def _is_redundant_query_term(value: str, query: str) -> bool:
    normalized_value = value.strip().lower()
    normalized_query = query.strip().lower()
    if not normalized_value:
        return True
    if normalized_value in normalized_query:
        return True
    value_terms = _query_terms(normalized_value)
    query_terms = set(_query_terms(normalized_query, max_terms=30))
    return bool(value_terms) and all(term in query_terms for term in value_terms)


def _query_terms(query: str, max_terms: int = 12) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _WORD_RE.findall(query.lower()):
        if len(match) < 2 or match in _QUERY_STOPWORDS or match in seen:
            continue
        seen.add(match)
        terms.append(match)
        if len(terms) >= max_terms:
            break
    return terms


def _add_unique(values: list[str], value: str) -> list[str]:
    seen = {item.lower() for item in values}
    item = value.strip()
    if item and item.lower() not in seen:
        return [*values, item]
    return values
