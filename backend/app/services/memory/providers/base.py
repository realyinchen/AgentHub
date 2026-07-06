from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.services.memory.contracts import (
    CurrentMemoryListResult,
    MemoryEvent,
    MemoryEventListResult,
    MemoryForgetResult,
    MemoryRecallProviderRequest,
    MemoryRecallProviderResult,
    MemorySearchResult,
)


class MemoryProvider(ABC):
    """Storage provider interface for app-owned memory operations."""

    provider_name: str

    @abstractmethod
    async def search(
        self,
        *,
        user_id: UUID,
        query: str = "",
        thread_id: UUID | None = None,
        memory_types: list[str] | None = None,
        limit: int = 10,
    ) -> MemorySearchResult:
        """Search relevant active memories for one user."""

    @abstractmethod
    async def list_events(
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
        """List memory audit events for advanced history."""

    @abstractmethod
    async def list_current(
        self,
        *,
        user_id: UUID,
        query: str = "",
        memory_types: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CurrentMemoryListResult:
        """List active current memories for the default user-facing view."""

    @abstractmethod
    async def remember(self, event: MemoryEvent) -> MemoryEvent:
        """Persist a new memory event."""

    @abstractmethod
    async def revise(
        self,
        *,
        user_id: UUID,
        new_event: MemoryEvent,
        memory_id: UUID | None = None,
        old_value: str = "",
        old_subject: str = "",
        old_type: str = "",
    ) -> MemoryEvent:
        """Supersede an existing memory and persist the corrected event."""

    @abstractmethod
    async def forget(
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
        """Forget matching current memories for a user."""


class MemoryRecallProvider(ABC):
    """Recall-only provider interface for external memory enhancers."""

    provider_name: str

    @abstractmethod
    async def search(
        self,
        request: MemoryRecallProviderRequest,
    ) -> MemoryRecallProviderResult:
        """Return candidate current memories through app-owned fields."""
