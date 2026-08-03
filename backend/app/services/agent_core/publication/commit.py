from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_core.contracts import PublishedAnswer
from app.services.agent_core.publication.contracts import (
    CommittedPublication,
)
from app.services.agent_core.publication.graph import (
    build_turn_execution_graph,
)
from app.services.agent_core.publication.trace import (
    persist_publication_trace,
)
from app.services.agent_core.turn_contracts import TurnReceipt
from app.services.conversation import ConversationJournalService


class TurnPublicationCommitter:
    """Atomically persist one terminal Journal event and its graph trace."""

    def __init__(self, *, journal=None, trace_writer=None) -> None:
        self._journal = journal or ConversationJournalService()
        self._trace_writer = trace_writer or persist_publication_trace

    async def commit(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        answer: PublishedAnswer,
        turn: TurnReceipt | None,
        model_name: str,
        agent_mode: str = "controller_v1",
    ) -> CommittedPublication:
        message = ChatMessage(
            type="ai",
            content=answer.content,
            request_id=user_input.request_id,
            custom_data={
                "agent_mode": agent_mode,
                "turn_status": (
                    turn.status if turn is not None else answer.status
                ),
                "publication_mode": answer.publication_mode,
                "receipt_backed": answer.receipt_backed,
                "receipt_refs": list(answer.receipt_refs),
            },
        )
        graph = build_turn_execution_graph(
            turn,
            request_id=user_input.request_id,
        )
        if answer.status == "completed":
            event = await self._journal.record_assistant_message(
                db,
                user_input=user_input,
                message=message,
            )
        elif answer.status == "clarification_required":
            event = await self._journal.record_clarification(
                db,
                user_input=user_input,
                question=answer.content,
                receipt_refs=list(answer.receipt_refs),
            )
        else:
            event = await self._journal.record_turn_failed(
                db,
                user_input=user_input,
                failure_code="trusted_publication_failed",
            )
        await self._trace_writer(
            db,
            user_input=user_input,
            message=message,
            graph=graph,
            model_name=model_name,
        )
        await db.commit()
        return CommittedPublication(
            message=message,
            journal_event=event,
            execution_graph=graph,
        )


__all__ = ["TurnPublicationCommitter"]
