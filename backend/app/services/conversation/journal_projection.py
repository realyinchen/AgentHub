from __future__ import annotations

from app.services.conversation.contracts import ConversationTurn, ConversationWindow
from app.services.conversation.journal_contracts import ConversationJournalEvent


def project_journal_window(
    events: list[ConversationJournalEvent],
) -> ConversationWindow:
    """Project the latest events into the identity-free runtime window."""

    ordered = [
        event
        for event in sorted(events, key=lambda item: item.sequence_no)
        if event.role in {"user", "assistant"}
    ][-16:]
    offset_start = -len(ordered)
    return ConversationWindow(
        turns=[
            ConversationTurn(
                role=event.role,
                content=event.content,
                turn_offset=offset_start + index,
            )
            for index, event in enumerate(ordered)
        ]
    )
