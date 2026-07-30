from __future__ import annotations

import asyncio
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import get_settings
from app.infra.llm.factory import get_llm
from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_core.gateway import (
    AgentControllerAttempt,
    AgentControllerGateway,
    AgentControllerMode,
)
from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
    ShadowDispatchReceipt,
    get_shadow_observation_dispatcher,
)
from app.services.conversation.journal_contracts import (
    ConversationShadowEnrollment,
    StoredConversationShadowEnrollment,
)
from app.services.conversation.journal_repository import (
    ConversationEventRepository,
)
from app.utils.message import convert_message_content_to_string


PLAIN_CHAT_SYSTEM_PROMPT = """\
You are in plain chat mode because Agent capabilities are not admitted.
Answer from the supplied conversation only. Do not call tools, claim external
lookups, or claim that memory/task state was changed.
"""


@dataclass(frozen=True)
class AgentChatEntryResult:
    handled: bool
    attempt: AgentControllerAttempt
    message: ChatMessage | None = None


class PlainChatClient:
    """Fail-closed chat adapter with no bound tools or business side effects."""

    def __init__(self, *, model_factory=None) -> None:
        self._model_factory = model_factory or _default_model_factory
        self._events = ConversationEventRepository()

    async def answer(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        model_name: str,
    ) -> ChatMessage:
        events = []
        cursor = 0
        while True:
            page = await self._events.list_events(
                db,
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                after_sequence=cursor,
                limit=500,
            )
            if page.events:
                cursor = page.events[-1].sequence_no
                events = (events + page.events)[-50:]
            if not page.has_more:
                break
        messages = [SystemMessage(content=PLAIN_CHAT_SYSTEM_PROMPT)]
        for event in events:
            if event.request_id == user_input.request_id:
                continue
            if event.role == "user":
                messages.append(HumanMessage(content=event.content))
            elif event.role == "assistant":
                messages.append(AIMessage(content=event.content))
        messages.append(HumanMessage(content=user_input.content))
        model = self._model_factory(
            model_name,
            thinking_mode=user_input.thinking_mode,
        )
        configured_timeout = get_settings().LLM_REQUEST_TIMEOUT
        response = await asyncio.wait_for(
            model.ainvoke(messages),
            timeout=(
                configured_timeout
                if configured_timeout > 0
                else None
            ),
        )
        if not isinstance(response, AIMessage):
            raise RuntimeError("plain chat model returned a non-AI message")
        content = convert_message_content_to_string(response.content).strip()
        if not content:
            raise RuntimeError("plain chat model returned empty content")
        return ChatMessage(
            type="ai",
            content=content,
            request_id=user_input.request_id,
            custom_data={"agent_mode": "plain_chat"},
        )


class AgentChatEntry:
    """Choose shadow/live/plain behavior before the legacy runtime path."""

    def __init__(
        self,
        *,
        gateway: AgentControllerGateway | None = None,
        plain_chat: PlainChatClient | None = None,
        shadow_dispatcher=None,
    ) -> None:
        self._gateway = gateway or AgentControllerGateway()
        self._plain_chat = plain_chat or PlainChatClient()
        self._shadow_dispatcher = shadow_dispatcher

    async def run(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        model_name: str,
        mode: AgentControllerMode | None = None,
        journal_sequence_watermark: int | None = None,
        shadow_enrollment: (
            StoredConversationShadowEnrollment | None
        ) = None,
    ) -> AgentChatEntryResult:
        selected_mode = (
            mode or get_settings().AGENT_CONTROLLER_V1_MODE
        )
        if selected_mode == "off":
            return AgentChatEntryResult(
                handled=False,
                attempt=AgentControllerAttempt(
                    mode="off",
                    status="off",
                ),
            )
        if selected_mode == "shadow":
            if (
                journal_sequence_watermark is None
                or journal_sequence_watermark < 1
            ):
                raise ValueError(
                    "Shadow entry requires a positive Journal watermark"
                )
            if not isinstance(
                shadow_enrollment,
                ConversationShadowEnrollment,
            ):
                raise ValueError(
                    "Shadow entry requires a current durable enrollment"
                )
            enrolled_input = user_input.model_copy(
                update={
                    "model_name": shadow_enrollment.model_name,
                    "model_uuid": str(shadow_enrollment.model_id),
                    "timezone": shadow_enrollment.timezone,
                }
            )
            receipt = self._dispatch_shadow(
                ShadowControllerCommand(
                    user_input=enrolled_input,
                    model_name=shadow_enrollment.model_name,
                    journal_sequence_watermark=(
                        journal_sequence_watermark
                    ),
                    controller_fingerprint=(
                        shadow_enrollment.controller_fingerprint
                    ),
                    source_commit_sha=(
                        shadow_enrollment.source_commit_sha
                    ),
                )
            )
            return AgentChatEntryResult(
                handled=False,
                attempt=AgentControllerAttempt(
                    mode="shadow",
                    status=(
                        "shadow_queued"
                        if receipt.status == "queued"
                        else "shadow_dropped"
                    ),
                    reason=receipt.reason,
                ),
            )

        attempt = await self._gateway.evaluate(
            db,
            user_input=user_input,
            model_name=model_name,
            mode=selected_mode,
        )
        if attempt.status == "off":
            return AgentChatEntryResult(
                handled=False,
                attempt=attempt,
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
                        "receipt_backed": answer.receipt_backed,
                        "receipt_refs": list(answer.receipt_refs),
                    },
                ),
            )
        message = await self._plain_chat.answer(
            db,
            user_input=user_input,
            model_name=model_name,
        )
        return AgentChatEntryResult(
            handled=True,
            attempt=attempt,
            message=message,
        )

    def _dispatch_shadow(
        self,
        command: ShadowControllerCommand,
    ) -> ShadowDispatchReceipt:
        try:
            dispatcher = (
                self._shadow_dispatcher
                or get_shadow_observation_dispatcher()
            )
        except RuntimeError:
            return ShadowDispatchReceipt(
                status="dropped",
                reason="not_started",
            )
        return dispatcher.submit(command)


def _default_model_factory(model_name: str, *, thinking_mode: bool):
    return get_llm(model_name, thinking_mode=thinking_mode)


__all__ = [
    "AgentChatEntry",
    "AgentChatEntryResult",
    "PLAIN_CHAT_SYSTEM_PROMPT",
    "PlainChatClient",
]
