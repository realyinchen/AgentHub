from __future__ import annotations

from uuid import UUID

from app.infra.database import get_database
from app.services.memory.contracts import (
    CurrentMemoryListResult,
    MemoryEvent,
    MemoryEventListResult,
    MemoryForgetResult,
    MemorySearchResult,
)
from app.services.memory.providers.postgres import PostgresMemoryProvider


class MemoryOrchestrator:
    """Coordinates memory providers behind the app-owned contract."""

    async def search_memory(
        self,
        *,
        user_id: UUID,
        query: str = "",
        thread_id: UUID | None = None,
        memory_types: list[str] | None = None,
        limit: int = 10,
    ) -> MemorySearchResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            return await provider.search(
                user_id=user_id,
                query=query,
                thread_id=thread_id,
                memory_types=memory_types,
                limit=limit,
            )

    async def list_memory_events(
        self,
        *,
        user_id: UUID,
        query: str = "",
        memory_types: list[str] | None = None,
        include_forgotten: bool = False,
        include_superseded: bool = False,
        include_audit: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> MemoryEventListResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            return await provider.list_events(
                user_id=user_id,
                query=query,
                memory_types=memory_types,
                include_forgotten=include_forgotten,
                include_superseded=include_superseded,
                include_audit=include_audit,
                limit=limit,
                offset=offset,
            )

    async def list_current_memories(
        self,
        *,
        user_id: UUID,
        query: str = "",
        memory_types: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CurrentMemoryListResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            return await provider.list_current(
                user_id=user_id,
                query=query,
                memory_types=memory_types,
                limit=limit,
                offset=offset,
            )

    async def remember_memory(self, event: MemoryEvent) -> MemoryEvent:
        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            return await provider.remember(event)

    async def revise_memory(
        self,
        *,
        user_id: UUID,
        new_event: MemoryEvent,
        memory_id: UUID | None = None,
        old_value: str = "",
        old_subject: str = "",
        old_type: str = "",
    ) -> MemoryEvent:
        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            return await provider.revise(
                user_id=user_id,
                new_event=new_event,
                memory_id=memory_id,
                old_value=old_value,
                old_subject=old_subject,
                old_type=old_type,
            )

    async def forget_memory(
        self,
        *,
        user_id: UUID,
        memory_id: UUID | None = None,
        subject: str = "",
        value: str = "",
        memory_type: str = "",
        thread_id: UUID | None = None,
        reason: str = "",
    ) -> MemoryForgetResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            return await provider.forget(
                user_id=user_id,
                memory_id=memory_id,
                subject=subject,
                value=value,
                memory_type=memory_type,
                thread_id=thread_id,
                reason=reason,
            )


_memory_orchestrator: MemoryOrchestrator | None = None


def get_memory_orchestrator() -> MemoryOrchestrator:
    global _memory_orchestrator
    if _memory_orchestrator is None:
        _memory_orchestrator = MemoryOrchestrator()
    return _memory_orchestrator
