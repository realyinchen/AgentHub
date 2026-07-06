"""User memory contract endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.memory import (
    MemoryContractResponse,
    MemoryForgetRequest,
    MemoryRememberRequest,
    MemoryReviseRequest,
)
from app.services.memory import (
    CurrentMemoryListResult,
    MemoryAdmissionError,
    MemoryEvent,
    MemoryEventListResult,
    MemoryForgetResult,
    MemorySearchResult,
    get_memory_orchestrator,
)
from app.services.memory.contracts import (
    INFORMATION_SCOPES,
    MEMORY_ADMISSION_DECISIONS,
    MEMORY_CANDIDATE_SOURCE_KINDS,
    MEMORY_CONFLICT_DECISIONS,
    MEMORY_CONFLICT_SEVERITIES,
    MEMORY_CONFLICT_TYPES,
    MEMORY_POLARITIES,
    MEMORY_SOURCES,
    MEMORY_SUBJECTS,
    MEMORY_TYPES,
)

api_router = APIRouter(prefix="/memory", tags=["Memory"])


@api_router.get("/contract", response_model=MemoryContractResponse)
async def get_memory_contract() -> MemoryContractResponse:
    """Return the app-owned memory contract allowed values."""
    return MemoryContractResponse(
        memory_types=sorted(MEMORY_TYPES),
        subjects=sorted(MEMORY_SUBJECTS),
        polarities=sorted(MEMORY_POLARITIES),
        sources=sorted(MEMORY_SOURCES),
        information_scopes=sorted(INFORMATION_SCOPES),
        candidate_source_kinds=sorted(MEMORY_CANDIDATE_SOURCE_KINDS),
        admission_decisions=sorted(MEMORY_ADMISSION_DECISIONS),
        conflict_types=sorted(MEMORY_CONFLICT_TYPES),
        conflict_severities=sorted(MEMORY_CONFLICT_SEVERITIES),
        conflict_decisions=sorted(MEMORY_CONFLICT_DECISIONS),
    )


@api_router.get("/{user_id}", response_model=MemorySearchResult)
async def search_user_memory(
    user_id: UUID,
    query: str = Query(default=""),
    thread_id: UUID | None = Query(default=None),
    memory_types: list[str] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> MemorySearchResult:
    """Search active app-owned memories for one user."""
    return await get_memory_orchestrator().search_memory(
        user_id=user_id,
        query=query,
        thread_id=thread_id,
        memory_types=memory_types,
        limit=limit,
    )


@api_router.get("/{user_id}/current", response_model=CurrentMemoryListResult)
async def list_current_user_memories(
    user_id: UUID,
    query: str = Query(default=""),
    memory_types: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CurrentMemoryListResult:
    """List current active memories for the default user-facing memory view."""
    return await get_memory_orchestrator().list_current_memories(
        user_id=user_id,
        query=query,
        memory_types=memory_types,
        limit=limit,
        offset=offset,
    )


@api_router.get("/{user_id}/events", response_model=MemoryEventListResult)
async def list_user_memory_events(
    user_id: UUID,
    query: str = Query(default=""),
    memory_types: list[str] | None = Query(default=None),
    include_forgotten: bool = Query(default=False),
    include_superseded: bool = Query(default=False),
    include_audit: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MemoryEventListResult:
    """List user memory events for advanced transparency and audit UI."""
    return await get_memory_orchestrator().list_memory_events(
        user_id=user_id,
        query=query,
        memory_types=memory_types,
        include_forgotten=include_forgotten,
        include_superseded=include_superseded,
        include_audit=include_audit,
        limit=limit,
        offset=offset,
    )


@api_router.post(
    "",
    response_model=MemoryEvent,
    status_code=status.HTTP_201_CREATED,
)
async def remember_user_memory(request: MemoryRememberRequest) -> MemoryEvent:
    """Persist one app-owned memory event."""
    event = MemoryEvent(
        user_id=request.user_id,
        thread_id=request.thread_id,
        type=request.type,
        subject=request.subject,
        value=request.value,
        polarity=request.polarity,
        confidence=request.confidence,
        source=request.source,
        metadata=request.metadata,
    )
    try:
        return await get_memory_orchestrator().remember_memory(
            event,
            scope=request.scope,
            source_text=request.source_text,
            source_kind=request.source_kind,
        )
    except MemoryAdmissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.decision.model_dump(mode="json"),
        ) from exc


@api_router.patch("", response_model=MemoryEvent)
async def revise_user_memory(request: MemoryReviseRequest) -> MemoryEvent:
    """Supersede a prior memory with a corrected event."""
    new_event = MemoryEvent(
        user_id=request.user_id,
        thread_id=request.thread_id,
        type=request.new_type,
        subject=request.new_subject,
        value=request.new_value,
        polarity=request.new_polarity,
        confidence=request.confidence,
        source=request.source,
        metadata=request.metadata,
    )
    try:
        return await get_memory_orchestrator().revise_memory(
            user_id=request.user_id,
            new_event=new_event,
            memory_id=request.memory_id,
            old_value=request.old_value,
            old_subject=request.old_subject,
            old_type=request.old_type,
        )
    except MemoryAdmissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.decision.model_dump(mode="json"),
        ) from exc


@api_router.post("/forget", response_model=MemoryForgetResult)
async def forget_user_memory(request: MemoryForgetRequest) -> MemoryForgetResult:
    """Forget matching current memories."""
    return await get_memory_orchestrator().forget_memory(
        user_id=request.user_id,
        memory_id=request.memory_id,
        subject=request.subject,
        value=request.value,
        memory_type=request.memory_type,
        thread_id=request.thread_id,
        reason=request.reason,
    )
