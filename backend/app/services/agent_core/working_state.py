from __future__ import annotations

from collections import OrderedDict
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_core.contracts import AgentCoreModel
from app.services.conversation.journal_contracts import ConversationJournalEvent
from app.services.conversation.journal_repository import (
    ConversationEventRepository,
)
from app.services.conversation.summary_repository import (
    ConversationSummaryRepository,
)


WORKING_STATE_CONTRACT_VERSION = "thread-working-state-v1"


class PendingClarification(AgentCoreModel):
    exchange_id: UUID
    question: str = Field(min_length=1, max_length=4_000)
    requested_at_sequence: int = Field(ge=1)


class ThreadWorkingState(AgentCoreModel):
    contract_version: Literal[
        "thread-working-state-v1"
    ] = WORKING_STATE_CONTRACT_VERSION
    journal_head_sequence: int = Field(ge=0)
    active_exchange_id: UUID | None = None
    active_goal: str | None = Field(default=None, max_length=4_000)
    pending_clarification: PendingClarification | None = None
    active_task_refs: list[str] = Field(default_factory=list, max_length=64)
    active_plan_refs: list[str] = Field(default_factory=list, max_length=64)
    summary_version_id: UUID | None = None
    recent_exchange_ids: list[UUID] = Field(default_factory=list, max_length=20)
    controller_round: int = Field(default=0, ge=0)
    recovery_cursor: int = Field(ge=0)
    last_turn_status: Literal[
        "empty",
        "incomplete",
        "completed",
        "waiting_clarification",
        "failed",
    ] = "empty"

    def checkpoint_payload(self) -> dict:
        """Serialize only working state; conversation messages are never included."""

        return self.model_dump(mode="json")


class WorkingStateRebuilder:
    """Purely rebuild recoverable working state from authoritative facts."""

    def rebuild(
        self,
        events: list[ConversationJournalEvent],
        *,
        summary_version_id: UUID | None = None,
        summary_to_sequence: int = 0,
        active_goal: str | None = None,
        active_task_refs: list[str] | None = None,
        active_plan_refs: list[str] | None = None,
    ) -> ThreadWorkingState:
        ordered = sorted(events, key=lambda event: event.sequence_no)
        grouped: OrderedDict[UUID, list[ConversationJournalEvent]] = OrderedDict()
        for event in ordered:
            grouped.setdefault(event.exchange_id, []).append(event)

        active_exchange_id = None
        for exchange_id, exchange_events in reversed(grouped.items()):
            if any(event.role == "user" for event in exchange_events) and not any(
                _is_terminal(event) for event in exchange_events
            ):
                active_exchange_id = exchange_id
                break

        last_user_sequence = max(
            (
                event.sequence_no
                for event in ordered
                if event.role == "user"
            ),
            default=0,
        )
        clarification = next(
            (
                event
                for event in reversed(ordered)
                if event.event_type == "clarification_requested"
                and event.sequence_no >= last_user_sequence
            ),
            None,
        )
        pending = (
            PendingClarification(
                exchange_id=clarification.exchange_id,
                question=clarification.content,
                requested_at_sequence=clarification.sequence_no,
            )
            if clarification is not None
            else None
        )
        recent = [
            exchange_id
            for exchange_id, exchange_events in grouped.items()
            if any(
                event.event_type
                in {"assistant_published", "clarification_requested"}
                for event in exchange_events
            )
        ][-20:]
        head = max(
            summary_to_sequence,
            ordered[-1].sequence_no if ordered else 0,
        )
        return ThreadWorkingState(
            journal_head_sequence=head,
            active_exchange_id=active_exchange_id,
            active_goal=active_goal,
            pending_clarification=pending,
            active_task_refs=list(active_task_refs or []),
            active_plan_refs=list(active_plan_refs or []),
            summary_version_id=summary_version_id,
            recent_exchange_ids=recent,
            controller_round=0,
            recovery_cursor=head,
            last_turn_status=_last_status(ordered),
        )


class WorkingStateRecoveryService:
    """Read Journal/Summary and rebuild state without reading old messages checkpoints."""

    def __init__(
        self,
        *,
        events: ConversationEventRepository | None = None,
        summaries: ConversationSummaryRepository | None = None,
        rebuilder: WorkingStateRebuilder | None = None,
    ) -> None:
        self._events = events or ConversationEventRepository()
        self._summaries = summaries or ConversationSummaryRepository()
        self._rebuilder = rebuilder or WorkingStateRebuilder()

    async def rebuild(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        active_goal: str | None = None,
        active_task_refs: list[str] | None = None,
        active_plan_refs: list[str] | None = None,
    ) -> ThreadWorkingState:
        summary = await self._summaries.latest(
            db,
            user_id=user_id,
            thread_id=thread_id,
        )
        cursor = summary.to_sequence if summary is not None else 0
        tail: list[ConversationJournalEvent] = []
        while True:
            page = await self._events.list_events(
                db,
                user_id=user_id,
                thread_id=thread_id,
                after_sequence=cursor,
                limit=500,
            )
            if page.events:
                cursor = page.events[-1].sequence_no
                tail = (tail + page.events)[-200:]
            if not page.has_more:
                break
        return self._rebuilder.rebuild(
            tail,
            summary_version_id=summary.id if summary is not None else None,
            summary_to_sequence=summary.to_sequence if summary is not None else 0,
            active_goal=active_goal,
            active_task_refs=active_task_refs,
            active_plan_refs=active_plan_refs,
        )


def _is_terminal(event: ConversationJournalEvent) -> bool:
    return event.event_type in {
        "assistant_published",
        "clarification_requested",
        "turn_failed",
    }


def _last_status(
    events: list[ConversationJournalEvent],
) -> Literal[
    "empty",
    "incomplete",
    "completed",
    "waiting_clarification",
    "failed",
]:
    if not events:
        return "empty"
    return {
        "user_message": "incomplete",
        "assistant_published": "completed",
        "clarification_requested": "waiting_clarification",
        "turn_failed": "failed",
    }[events[-1].event_type]


__all__ = [
    "WORKING_STATE_CONTRACT_VERSION",
    "PendingClarification",
    "ThreadWorkingState",
    "WorkingStateRebuilder",
    "WorkingStateRecoveryService",
]
