from __future__ import annotations

from app.schemas.chat import ChatMessage
from app.services.conversation.journal_contracts import ConversationJournalEvent


def project_journal_chat_messages(
    events: list[ConversationJournalEvent],
) -> list[ChatMessage]:
    """Project canonical events into the existing HTTP chat DTO."""

    messages: list[ChatMessage] = []
    for event in sorted(events, key=lambda item: item.sequence_no):
        if event.role == "system":
            continue
        stored = event.metadata.get("chat_message")
        stored_message = stored if isinstance(stored, dict) else {}
        messages.append(
            ChatMessage(
                type="human" if event.role == "user" else "ai",
                content=event.content,
                request_id=(
                    event.request_id
                    if event.role == "assistant"
                    else None
                ),
                response_metadata=(
                    dict(stored_message.get("response_metadata") or {})
                    if isinstance(
                        stored_message.get("response_metadata"),
                        dict,
                    )
                    else {}
                ),
                custom_data=(
                    dict(stored_message.get("custom_data") or {})
                    if isinstance(stored_message.get("custom_data"), dict)
                    else dict(event.metadata.get("custom_data") or {})
                ),
            )
        )
    return messages
