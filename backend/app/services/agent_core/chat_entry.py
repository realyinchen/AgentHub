from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_core.gateway import (
    AgentControllerAttempt,
    AgentControllerGateway,
)
from app.services.agent_core.contracts import PublishedAnswer


@dataclass(frozen=True)
class AgentChatEntryResult:
    handled: bool
    attempt: AgentControllerAttempt
    message: ChatMessage | None = None
    answer: PublishedAnswer | None = None


class AgentChatEntry:
    """Enter the single Agent Core execution path."""

    def __init__(
        self,
        *,
        gateway: AgentControllerGateway | None = None,
    ) -> None:
        self._gateway = gateway or AgentControllerGateway()

    async def run(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        model_name: str,
        journal_sequence_watermark: int | None = None,
    ) -> AgentChatEntryResult:
        attempt = await self._gateway.evaluate(
            db,
            user_input=user_input,
            model_name=model_name,
            journal_sequence_watermark=journal_sequence_watermark,
        )
        if attempt.turn is not None:
            answer = attempt.turn.final_answer
            return AgentChatEntryResult(
                handled=True,
                attempt=attempt,
                message=ChatMessage(
                    type="ai",
                    content=answer.content,
                    request_id=user_input.request_id,
                    custom_data={
                        "agent_mode": "controller_v1",
                        "turn_status": attempt.turn.status,
                        "publication_mode": answer.publication_mode,
                        "receipt_backed": answer.receipt_backed,
                        "receipt_refs": list(answer.receipt_refs),
                    },
                ),
                answer=answer,
            )
        answer = PublishedAnswer(
            status="failed",
            content="本轮未能形成可执行结果，请稍后重试。",
            receipt_backed=False,
            publication_mode="direct",
        )
        return AgentChatEntryResult(
            handled=True,
            attempt=attempt,
            message=ChatMessage(
                type="ai",
                content=answer.content,
                request_id=user_input.request_id,
                custom_data={
                    "agent_mode": "controller_v1",
                    "turn_status": "failed",
                    "publication_mode": answer.publication_mode,
                    "receipt_backed": False,
                    "receipt_refs": [],
                },
            ),
            answer=answer,
        )

__all__ = [
    "AgentChatEntry",
    "AgentChatEntryResult",
]
