"""SSE adapter for the single Agent Core chat path."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from app.infra.config import get_settings
from app.infra.database import get_database
from app.schemas.chat import UserInput
from app.services.agent_core.trusted_stream import TrustedControllerStream
from app.services.chat import ChatService
from app.utils.sse import sse, sse_error


logger = logging.getLogger(__name__)


class ChatStreamingService:
    """Publish Agent Core events without loading the retired runtime."""

    def __init__(
        self,
        *,
        trusted_stream: TrustedControllerStream | None = None,
        chat_service: ChatService | None = None,
        database_factory=None,
    ) -> None:
        self._trusted_stream = trusted_stream or TrustedControllerStream()
        self._chat_service = chat_service or ChatService()
        self._database_factory = database_factory or get_database

    async def generate(
        self,
        user_input: UserInput,
    ) -> AsyncGenerator[str, None]:
        """Generate Live trusted events or a no-tool non-Live response."""

        yield f": {' ' * 2048}\n\n"
        if get_settings().AGENT_CONTROLLER_V1_MODE == "live":
            async for event in self._trusted_stream.generate(user_input):
                yield event
            return

        try:
            database = self._database_factory()
            async with database.session() as session:
                message = await self._chat_service.invoke(
                    session,
                    user_input,
                )
        except Exception:
            logger.exception("Agent Core non-Live stream failed")
            yield sse_error(
                "Agent Core could not form a safe response.",
                error_type="agent_core_unavailable",
            )
            yield "data: [DONE]\n\n"
            return

        yield sse(
            {
                "type": "request_start",
                "request_id": user_input.request_id,
            }
        )
        yield sse(
            {
                "type": "step",
                "step": 1,
                "action": "human",
                "content": user_input.content,
            }
        )
        yield sse(
            {
                "type": "step",
                "step": 2,
                "action": "agent_core_plain",
                "content": {"side_effects": 0},
            }
        )
        yield sse({"type": "message", "content": message.model_dump()})
        yield "data: [DONE]\n\n"


__all__ = ["ChatStreamingService"]
