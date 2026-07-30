from __future__ import annotations

import math
import re
from collections import OrderedDict
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ConversationContextTurn,
    TrustedConversationSummary,
    TrustedMemoryContext,
    TrustedReceiptContext,
    TrustedTaskContext,
    TrustedWorkingStateContext,
)
from app.services.conversation.journal_contracts import ConversationJournalEvent
from app.services.conversation.journal_repository import (
    ConversationEventRepository,
)
from app.services.conversation.summary_contracts import ConversationSummary
from app.services.conversation.summary_repository import (
    ConversationSummaryRepository,
)


class ContextAssemblyError(ValueError):
    """Base error for bounded Controller context construction."""


class ContextCompressionRequired(ContextAssemblyError):
    def __init__(self, through_sequence: int) -> None:
        self.through_sequence = through_sequence
        super().__init__(
            f"conversation summary required through sequence {through_sequence}"
        )


class ContextBudgetExceeded(ContextAssemblyError):
    pass


class ConversationContextMaterial(AgentCoreModel):
    summary: ConversationSummary | None = None
    events: list[ConversationJournalEvent] = Field(default_factory=list)
    has_more: bool = False


class ContextAssemblyResult(AgentCoreModel):
    snapshot: ControllerContextSnapshot
    estimated_tokens: int = Field(ge=0)
    token_budget: int = Field(ge=1)
    exact_exchange_count: int = Field(ge=0)
    summary_used: bool = False
    journal_head_sequence: int = Field(ge=0)


class ConversationContextLoader:
    """Load authoritative context material; it performs no projection."""

    def __init__(
        self,
        *,
        events: ConversationEventRepository | None = None,
        summaries: ConversationSummaryRepository | None = None,
    ) -> None:
        self._events = events or ConversationEventRepository()
        self._summaries = summaries or ConversationSummaryRepository()

    async def load(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_request_id: str,
        through_sequence: int | None = None,
    ) -> ConversationContextMaterial:
        summary = await self._summaries.latest(
            db,
            user_id=user_id,
            thread_id=thread_id,
            through_sequence=through_sequence,
        )
        page = await self._events.list_events(
            db,
            user_id=user_id,
            thread_id=thread_id,
            after_sequence=summary.to_sequence if summary else 0,
            limit=500,
            exclude_request_id=exclude_request_id,
            through_sequence=through_sequence,
        )
        return ConversationContextMaterial(
            summary=summary,
            events=page.events,
            has_more=page.has_more,
        )


class ContextAssembler:
    """Purely combine summary and exact Journal events under a token budget."""

    def __init__(
        self,
        *,
        recent_exchange_limit: int = 20,
        token_budget: int = 12_000,
    ) -> None:
        if recent_exchange_limit < 1:
            raise ValueError("recent_exchange_limit must be positive")
        if token_budget < 256:
            raise ValueError("token_budget is too small")
        self._recent_exchange_limit = recent_exchange_limit
        self._token_budget = token_budget

    def assemble(
        self,
        material: ConversationContextMaterial,
        *,
        current_user_message: str,
        memories: list[TrustedMemoryContext] | None = None,
        receipts: list[TrustedReceiptContext] | None = None,
        working_state: TrustedWorkingStateContext | None = None,
        task: TrustedTaskContext | None = None,
    ) -> ContextAssemblyResult:
        ordered = sorted(material.events, key=lambda event: event.sequence_no)
        exchanges = _group_exchanges(ordered)
        if material.has_more or len(exchanges) > self._recent_exchange_limit:
            cutoff = _compression_cutoff(
                exchanges,
                keep=self._recent_exchange_limit,
            )
            raise ContextCompressionRequired(cutoff)

        snapshot = ControllerContextSnapshot(
            conversation_summary=(
                _summary_context(material.summary)
                if material.summary is not None
                else None
            ),
            conversation=[
                ConversationContextTurn(
                    role=event.role,
                    content=event.content,
                )
                for exchange in exchanges
                for event in exchange
                if event.role in {"user", "assistant"}
            ],
            memories=list(memories or []),
            receipts=list(receipts or []),
            working_state=working_state,
            task=task,
        )
        estimated_tokens = estimate_controller_tokens(
            snapshot,
            current_user_message=current_user_message,
        )
        if estimated_tokens > self._token_budget:
            if exchanges:
                cutoff = _compression_cutoff(
                    exchanges,
                    keep=max(0, len(exchanges) - 1),
                )
                raise ContextCompressionRequired(cutoff)
            raise ContextBudgetExceeded(
                "current input and trusted context exceed the token budget"
            )
        return ContextAssemblyResult(
            snapshot=snapshot,
            estimated_tokens=estimated_tokens,
            token_budget=self._token_budget,
            exact_exchange_count=len(exchanges),
            summary_used=material.summary is not None,
            journal_head_sequence=(
                ordered[-1].sequence_no
                if ordered
                else (
                    material.summary.to_sequence
                    if material.summary is not None
                    else 0
                )
            ),
        )


def estimate_controller_tokens(
    snapshot: ControllerContextSnapshot,
    *,
    current_user_message: str,
) -> int:
    text = snapshot.model_dump_json() + current_user_message
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    other = max(0, len(text) - cjk)
    return cjk + math.ceil(other / 4) + 64


def _group_exchanges(
    events: list[ConversationJournalEvent],
) -> list[list[ConversationJournalEvent]]:
    grouped: OrderedDict[UUID, list[ConversationJournalEvent]] = OrderedDict()
    for event in events:
        grouped.setdefault(event.exchange_id, []).append(event)
    return list(grouped.values())


def _compression_cutoff(
    exchanges: list[list[ConversationJournalEvent]],
    *,
    keep: int,
) -> int:
    prefix = exchanges[: max(0, len(exchanges) - keep)]
    if not prefix:
        raise ContextBudgetExceeded(
            "no completed older exchange is available for compression"
        )
    for exchange in reversed(prefix):
        for event in reversed(exchange):
            if event.role == "assistant":
                return event.sequence_no
    raise ContextBudgetExceeded(
        "older context has no published assistant boundary for compression"
    )


def _summary_context(
    summary: ConversationSummary,
) -> TrustedConversationSummary:
    content = summary.structured_content
    return TrustedConversationSummary(
        user_requests=[item.text for item in content.user_requests],
        user_statements=[item.text for item in content.user_statements],
        decisions=[item.text for item in content.decisions],
        corrections=[item.text for item in content.corrections],
        unresolved=[item.text for item in content.unresolved],
        active_tasks=[item.text for item in content.active_tasks],
        receipt_refs=list(content.receipt_refs),
    )


__all__ = [
    "ContextAssembler",
    "ContextAssemblyError",
    "ContextAssemblyResult",
    "ContextBudgetExceeded",
    "ContextCompressionRequired",
    "ConversationContextLoader",
    "ConversationContextMaterial",
    "estimate_controller_tokens",
]
