from __future__ import annotations

from collections import OrderedDict

from app.services.conversation.contracts import (
    ConversationExchange,
    ConversationReadRequest,
    ConversationReadResult,
    ConversationTurn,
    ConversationWindow,
)
from app.services.conversation.journal_contracts import ConversationJournalEvent
from app.services.conversation.recall import read_conversation


def read_journal_events(
    events: list[ConversationJournalEvent],
    request: ConversationReadRequest,
) -> ConversationReadResult:
    """Read exact exchanges using journal-owned exchange identifiers."""

    ordered = sorted(events, key=lambda item: item.sequence_no)
    offsets = {
        event.id: index - len(ordered)
        for index, event in enumerate(ordered)
    }
    grouped: OrderedDict[str, dict[str, ConversationTurn]] = OrderedDict()
    for event in ordered:
        if event.role not in {"user", "assistant"}:
            continue
        turns = grouped.setdefault(str(event.exchange_id), {})
        turns[event.role] = ConversationTurn(
            role=event.role,
            turn_offset=offsets[event.id],
            content=event.content,
        )

    exchanges = [
        ConversationExchange(
            user=pair["user"],
            assistant=pair.get("assistant"),
            status=(
                "completed"
                if pair.get("assistant") is not None
                else "incomplete"
            ),
        )
        for pair in grouped.values()
        if "user" in pair
    ]
    available = (
        [item for item in exchanges if item.assistant is not None]
        if request.target in {"assistant", "exchange"}
        else exchanges
    )
    requested = 1 if request.selection == "latest" else request.count
    selected = available[-requested:]
    projected_turns: list[ConversationTurn] = []
    for exchange in selected:
        projected_turns.append(exchange.user)
        if exchange.assistant is not None:
            projected_turns.append(exchange.assistant)
    return read_conversation(
        ConversationWindow(turns=projected_turns),
        ConversationReadRequest(
            target=request.target,
            selection="last_n",
            count=requested,
        ),
    )
