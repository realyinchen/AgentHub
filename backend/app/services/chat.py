"""Single-entry chat orchestration for Agent Core.

The service records the user event, delegates every decision to Agent Core,
and commits only a trusted publication.  It has no dependency on the retired
planner/runtime stack.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import get_settings
from app.infra.llm import resolve_model_name
from app.infra.llm.resolver import refresh_model_cache_if_missing
from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_core.chat_entry import (
    AgentChatEntry,
    AgentChatEntryResult,
)
from app.services.agent_core.publication.commit import (
    TurnPublicationCommitter,
)
from app.services.agent_core.shadow_enrollment import (
    is_current_shadow_enrollment,
    prepare_shadow_enrollment,
)
from app.services.conversation import ConversationJournalService


logger = logging.getLogger(__name__)


class ChatService:
    """Invoke Agent Core without any legacy runtime fallback."""

    def __init__(
        self,
        *,
        agent_entry: AgentChatEntry | None = None,
        committer: TurnPublicationCommitter | None = None,
    ) -> None:
        self._agent_entry = agent_entry or AgentChatEntry()
        self._committer = committer or TurnPublicationCommitter()

    async def invoke(
        self,
        db: AsyncSession,
        user_input: UserInput,
    ) -> ChatMessage:
        """Run one committed Agent Core turn.

        Off and Shadow modes use the isolated no-tool responder after their
        respective control decision.  They never invoke the retired runtime.
        """

        journal = ConversationJournalService()
        settings = get_settings()
        controller_mode = settings.AGENT_CONTROLLER_V1_MODE
        prepared = prepare_shadow_enrollment(
            user_input,
            mode=controller_mode,
            model_resolver=resolve_model_name,
            source_commit_sha=settings.AGENT_RELEASE_COMMIT_SHA,
        )
        user_input = prepared.user_input
        user_event = await journal.record_user_message(
            db,
            user_input,
            shadow_enrollment=prepared.enrollment,
        )
        await db.commit()

        requested_model = user_input.model_uuid or user_input.model_name
        model_name = prepared.resolved_model_name or resolve_model_name(
            requested_model
        )
        if not model_name:
            raise HTTPException(
                status_code=503,
                detail="No AI models are currently available.",
            )
        if requested_model:
            await refresh_model_cache_if_missing(model_name)
        if user_input.model_name != model_name:
            user_input = user_input.model_copy(
                update={"model_name": model_name}
            )

        entry = await self._evaluate_entry(
            db,
            user_input=user_input,
            model_name=model_name,
            journal_sequence_watermark=user_event.sequence_no,
            shadow_enrollment=user_event.shadow_enrollment,
        )
        if not entry.handled:
            entry = await self._agent_entry.run_plain(
                db,
                user_input=user_input,
                model_name=model_name,
                attempt=entry.attempt,
            )
        if entry.message is None or entry.answer is None:
            raise HTTPException(
                status_code=503,
                detail="Agent Core did not produce a safe response.",
            )

        committed = await self._committer.commit(
            db,
            user_input=user_input,
            answer=entry.answer,
            turn=entry.attempt.turn,
            model_name=model_name,
            agent_mode=str(
                entry.message.custom_data.get(
                    "agent_mode", "controller_v1"
                )
            ),
        )
        return committed.message

    async def _evaluate_entry(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        model_name: str,
        journal_sequence_watermark: int,
        shadow_enrollment,
    ) -> AgentChatEntryResult:
        settings = get_settings()
        if settings.AGENT_CONTROLLER_V1_MODE == "shadow" and not (
            is_current_shadow_enrollment(
                shadow_enrollment,
                source_commit_sha=settings.AGENT_RELEASE_COMMIT_SHA or "",
            )
        ):
            logger.info(
                "[request_id=%s] Shadow skipped: no current durable enrollment",
                user_input.request_id,
            )
            return await self._agent_entry.run_plain(
                db,
                user_input=user_input,
                model_name=model_name,
            )
        return await self._agent_entry.run(
            db,
            user_input=user_input,
            model_name=model_name,
            journal_sequence_watermark=journal_sequence_watermark,
            shadow_enrollment=shadow_enrollment,
        )

    async def stream(
        self,
        user_input: UserInput,
    ) -> AsyncGenerator[str, None]:
        """Delegate SSE publication to the Agent Core stream adapter."""

        from app.services.streaming import ChatStreamingService

        async for event in ChatStreamingService().generate(user_input):
            yield event


__all__ = ["ChatService"]
