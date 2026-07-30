from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.services.agent_core.contracts import AgentCoreModel
from app.services.conversation.journal_contracts import (
    ConversationShadowEnrollment,
)


class PendingShadowEnrollment(AgentCoreModel):
    """Minimum Journal facts needed to reconstruct one dry-run command."""

    user_id: UUID
    thread_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1)
    journal_sequence_watermark: int = Field(ge=1)
    enrollment: ConversationShadowEnrollment


__all__ = ["PendingShadowEnrollment"]
