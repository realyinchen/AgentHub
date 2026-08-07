"""SSE adapter for the single Agent Core chat path."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from app.schemas.chat import UserInput
from app.services.agent_core.trusted_stream import TrustedControllerStream


class ChatStreamingService:
    """Publish Agent Core events without loading the retired runtime."""

    def __init__(
        self,
        *,
        trusted_stream: TrustedControllerStream | None = None,
    ) -> None:
        self._trusted_stream = trusted_stream or TrustedControllerStream()

    async def generate(
        self,
        user_input: UserInput,
    ) -> AsyncGenerator[str, None]:
        """Generate trusted events from the production Agent Core."""

        yield f": {' ' * 2048}\n\n"
        async for event in self._trusted_stream.generate(user_input):
            yield event


__all__ = ["ChatStreamingService"]
