from __future__ import annotations

from uuid import UUID

from app.infra.database import get_database
from app.services.memory.admission import (
    MemoryAdmissionEngine,
    MemoryAdmissionError,
    memory_event_to_candidate,
)
from app.services.memory.conflicts import MemoryConflictResolver
from app.services.memory.contracts import (
    CurrentMemoryListResult,
    MemoryAdmissionDecision,
    MemoryAdmissionResult,
    MemoryCandidate,
    MemoryEvent,
    MemoryEventListResult,
    MemoryForgetResult,
    MemoryRecallProviderRequest,
    MemorySearchResult,
)
from app.services.memory.providers.base import MemoryRecallProvider
from app.services.memory.providers.mem0 import Mem0MemoryProvider
from app.services.memory.providers.postgres import PostgresMemoryProvider
from app.services.provider_config import (
    ProviderRegistry,
    get_provider_registry,
    safe_enabled_provider_configs_from_db,
)


class MemoryOrchestrator:
    """Coordinates memory providers behind the app-owned contract."""

    def __init__(
        self,
        *,
        memory_recall_providers: list[MemoryRecallProvider] | None = None,
        provider_registry: ProviderRegistry | None = None,
    ) -> None:
        self._memory_recall_providers = memory_recall_providers
        self._provider_registry = provider_registry
        self._memory_admission_engine = MemoryAdmissionEngine()
        self._memory_conflict_resolver = MemoryConflictResolver()

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
            result = await provider.search(
                user_id=user_id,
                query=query,
                thread_id=thread_id,
                memory_types=memory_types,
                limit=limit,
            )
            current = await provider.list_current(
                user_id=user_id,
                query="",
                memory_types=memory_types,
                limit=100,
            )
            return await self._augment_with_recall_providers(
                result=result,
                current_memories=current.memories,
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

    async def remember_candidate(
        self,
        candidate: MemoryCandidate,
    ) -> MemoryAdmissionResult:
        try:
            return await self._remember_candidate(candidate)
        except Exception as exc:
            if not self._should_retry_without_thread(candidate, exc):
                raise
            metadata = {
                **candidate.metadata,
                "thread_id_dropped": True,
                "thread_id_drop_reason": "missing_conversation",
                "original_thread_id": str(candidate.thread_id),
            }
            fallback_candidate = candidate.model_copy(
                update={"thread_id": None, "metadata": metadata}
            )
            return await self._remember_candidate(fallback_candidate)

    async def _remember_candidate(
        self,
        candidate: MemoryCandidate,
    ) -> MemoryAdmissionResult:
        decision = self._memory_admission_engine.admit(candidate)
        if decision.decision != "allow":
            return MemoryAdmissionResult(decision=decision)

        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            inactive_decision = await self._reject_inactive_memory_reintroduction(
                provider=provider,
                decision=decision,
            )
            if inactive_decision is not None:
                return MemoryAdmissionResult(decision=inactive_decision)

            current = await provider.list_current(
                user_id=candidate.user_id,
                query="",
                memory_types=None,
                limit=100,
            )
            resolution = self._memory_conflict_resolver.resolve(
                candidate,
                current.memories,
            )
            if resolution.decision == "needs_confirmation":
                return MemoryAdmissionResult(
                    decision=decision.model_copy(
                        update={
                            "decision": "needs_confirmation",
                            "reason": resolution.reason,
                            "target_memory_id": resolution.target_memory_id,
                            "warnings": [
                                conflict.reason for conflict in resolution.conflicts
                            ],
                            "metadata": {
                                **decision.metadata,
                                "conflict_resolution": resolution.model_dump(
                                    mode="json"
                                ),
                            },
                        }
                    ),
                    conflicts=resolution.conflicts,
                    provider_sources=[provider.provider_name],
                )

            if resolution.decision == "skip_duplicate":
                existing = self._memory_by_id(
                    current.memories,
                    resolution.target_memory_id,
                )
                return MemoryAdmissionResult(
                    decision=decision.model_copy(
                        update={
                            "metadata": {
                                **decision.metadata,
                                "conflict_resolution": resolution.model_dump(
                                    mode="json"
                                ),
                            }
                        }
                    ),
                    memory=existing,
                    conflicts=resolution.conflicts,
                    provider_sources=[provider.provider_name],
                )

            if resolution.decision == "revise_existing":
                target = self._memory_by_id(
                    current.memories,
                    resolution.target_memory_id,
                )
                if target is None:
                    return MemoryAdmissionResult(
                        decision=decision.model_copy(
                            update={
                                "decision": "needs_confirmation",
                                "reason": "conflict_target_missing",
                                "metadata": {
                                    **decision.metadata,
                                    "conflict_resolution": resolution.model_dump(
                                        mode="json"
                                    ),
                                },
                            }
                        ),
                        conflicts=resolution.conflicts,
                        provider_sources=[provider.provider_name],
                    )
                saved = await provider.revise(
                    user_id=candidate.user_id,
                    new_event=self._event_with_conflict_resolution(
                        candidate,
                        resolution.model_dump(mode="json"),
                    ),
                    memory_id=target.id,
                    old_value=target.value,
                    old_subject=target.subject,
                    old_type=target.type,
                )
                return MemoryAdmissionResult(
                    decision=decision.model_copy(
                        update={
                            "metadata": {
                                **decision.metadata,
                                "conflict_resolution": resolution.model_dump(
                                    mode="json"
                                ),
                            }
                        }
                    ),
                    memory=saved,
                    conflicts=resolution.conflicts,
                    provider_sources=[provider.provider_name],
                )

            saved = await provider.remember(
                self._event_with_conflict_resolution(
                    candidate,
                    resolution.model_dump(mode="json"),
                )
            )
            return MemoryAdmissionResult(
                decision=decision,
                memory=saved,
                conflicts=resolution.conflicts,
                provider_sources=[provider.provider_name],
            )

    @staticmethod
    def _should_retry_without_thread(candidate: MemoryCandidate, exc: Exception) -> bool:
        if candidate.thread_id is None:
            return False
        text = str(exc)
        return (
            "ForeignKeyViolationError" in text
            and "memory_events_thread_id_fkey" in text
            and "conversations" in text
        )

    async def remember_memory(
        self,
        event: MemoryEvent,
        *,
        scope: str = "long_term_memory",
        source_text: str = "",
        source_kind: str | None = None,
    ) -> MemoryEvent:
        result = await self.remember_candidate(
            memory_event_to_candidate(
                event,
                scope=scope,
                source_text=source_text,
                source_kind=source_kind,
            )
        )
        if result.memory is not None:
            return result.memory
        raise MemoryAdmissionError(result.decision)

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
        decision = self._memory_admission_engine.admit(
            memory_event_to_candidate(
                new_event.model_copy(update={"user_id": user_id}),
            )
        )
        if decision.decision != "allow":
            raise MemoryAdmissionError(decision)

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

    async def _augment_with_recall_providers(
        self,
        *,
        result: MemorySearchResult,
        current_memories: list[MemoryEvent],
        user_id: UUID,
        query: str,
        thread_id: UUID | None,
        memory_types: list[str] | None,
        limit: int,
    ) -> MemorySearchResult:
        recall_providers = await self._get_memory_recall_providers()
        if not recall_providers:
            return result

        provider_sources = list(result.provider_sources)
        telemetry = list(result.provider_telemetry)
        relevant_events = list(result.relevant_events)
        seen_ids = {event.id for event in relevant_events if event.id is not None}
        current_by_id = {
            event.id: event for event in current_memories if event.id is not None
        }

        for recall_provider in recall_providers:
            try:
                provider_result = await recall_provider.search(
                    MemoryRecallProviderRequest(
                        user_id=user_id,
                        thread_id=thread_id,
                        query=query,
                        limit=limit,
                        filters={"memory_types": memory_types or []},
                        current_memories=current_memories,
                        metadata={"provider": {"provider_name": recall_provider.provider_name}},
                    )
                )
            except Exception as exc:
                provider_name = getattr(recall_provider, "provider_name", "unknown")
                telemetry.append(
                    {
                        "provider_name": provider_name,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                if provider_name not in provider_sources:
                    provider_sources.append(provider_name)
                continue

            if provider_result.provider_name not in provider_sources:
                provider_sources.append(provider_result.provider_name)
            telemetry.append(
                {
                    "provider_name": provider_result.provider_name,
                    "status": provider_result.status,
                    "error": provider_result.error,
                    "duration_ms": provider_result.duration_ms,
                    "metadata": provider_result.metadata,
                }
            )
            if provider_result.status != "completed":
                continue

            for candidate in provider_result.memories:
                current = self._match_current_memory(
                    candidate,
                    current_memories=current_memories,
                    current_by_id=current_by_id,
                )
                if current is None or current.id in seen_ids:
                    continue
                relevant_events.append(current)
                if current.id is not None:
                    seen_ids.add(current.id)
                if len(relevant_events) >= max(1, min(limit, 50)):
                    break

        return result.model_copy(
            update={
                "relevant_events": relevant_events[: max(1, min(limit, 50))],
                "provider_sources": provider_sources,
                "provider_telemetry": telemetry,
            }
        )

    async def _reject_inactive_memory_reintroduction(
        self,
        *,
        provider: PostgresMemoryProvider,
        decision: MemoryAdmissionDecision,
    ) -> MemoryAdmissionDecision | None:
        candidate = decision.candidate
        if candidate.metadata.get("explicit_restore") is True:
            return None

        event_list = await provider.list_events(
            user_id=candidate.user_id,
            query=candidate.value,
            memory_types=[candidate.type],
            include_forgotten=True,
            include_superseded=True,
            include_audit=False,
            limit=50,
        )
        candidate_value = candidate.value.strip().lower()
        for event in event_list.events:
            if (
                event.subject == candidate.subject
                and event.value.strip().lower() == candidate_value
                and event.polarity == candidate.polarity
                and (event.forgotten or event.superseded_by is not None)
            ):
                state = "forgotten" if event.forgotten else "superseded"
                return decision.model_copy(
                    update={
                        "decision": "reject",
                        "reason": "inactive_memory_requires_explicit_restore",
                        "target_memory_id": event.id,
                        "warnings": [
                            f"matching_{state}_memory_would_be_reintroduced"
                        ],
                        "metadata": {
                            **decision.metadata,
                            "inactive_memory_state": state,
                        },
                    }
                )
        return None

    def _memory_by_id(
        self,
        memories: list[MemoryEvent],
        memory_id: UUID | None,
    ) -> MemoryEvent | None:
        if memory_id is None:
            return None
        for memory in memories:
            if memory.id == memory_id:
                return memory
        return None

    def _event_with_conflict_resolution(
        self,
        candidate: MemoryCandidate,
        conflict_resolution: dict,
    ) -> MemoryEvent:
        event = candidate.to_memory_event()
        metadata = dict(event.metadata)
        metadata["conflict_resolution"] = conflict_resolution
        precommit = dict(metadata.get("precommit") or {})
        precommit["conflict_checked"] = True
        metadata["precommit"] = precommit
        return event.model_copy(update={"metadata": metadata})

    async def _get_memory_recall_providers(self) -> list[MemoryRecallProvider]:
        if self._memory_recall_providers is not None:
            return self._memory_recall_providers
        if self._provider_registry is not None:
            configs = self._provider_registry.enabled_configs(
                provider_type="memory",
                capability="memory_recall",
            )
        else:
            db = get_database()
            async with db.session() as session:
                configs = await safe_enabled_provider_configs_from_db(
                    session,
                    provider_type="memory",
                    capability="memory_recall",
                )
            if not configs:
                configs = get_provider_registry().enabled_configs(
                    provider_type="memory",
                    capability="memory_recall",
                )
        providers: list[MemoryRecallProvider] = []
        for config in configs:
            if config.provider_key == "mem0":
                providers.append(Mem0MemoryProvider(config))
        return providers

    def _match_current_memory(
        self,
        candidate: MemoryEvent,
        *,
        current_memories: list[MemoryEvent],
        current_by_id: dict[UUID, MemoryEvent],
    ) -> MemoryEvent | None:
        if candidate.forgotten or candidate.superseded_by is not None:
            return None
        if candidate.id is not None:
            return current_by_id.get(candidate.id)
        for current in current_memories:
            if (
                current.type == candidate.type
                and current.subject == candidate.subject
                and current.value.strip().lower() == candidate.value.strip().lower()
                and current.polarity == candidate.polarity
                and not current.forgotten
                and current.superseded_by is None
            ):
                return current
        return None


_memory_orchestrator: MemoryOrchestrator | None = None


def get_memory_orchestrator() -> MemoryOrchestrator:
    global _memory_orchestrator
    if _memory_orchestrator is None:
        _memory_orchestrator = MemoryOrchestrator()
    return _memory_orchestrator
