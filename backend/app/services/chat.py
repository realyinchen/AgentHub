"""Chat orchestration service.

Main entry point for both invoke and stream operations.
Handles model resolution, parameter building, agent execution,
and result persistence.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import get_settings
from app.infra.llm import resolve_model_name
from app.infra.llm.resolver import refresh_model_cache_if_missing
from app.schemas.chat import ChatMessage, UserInput
from app.crud.trace import persist_agent_trace
from app.utils.request import build_agent_kwargs
from app.utils.message import langchain_to_chat_message
from app.services.streaming import ChatStreamingService


logger = logging.getLogger(__name__)


class ChatService:
    """Chat orchestration service.

    Handles the complete flow:
    1. Model resolution (default → first-active fallback)
    2. Agent parameter building
    3. Agent execution (invoke or stream)
    4. Result persistence (tokens + DAG)

    Usage (invoke)::
        supervisor = get_supervisor()
        service = ChatService(supervisor)
        response = await service.invoke(db, user_input)

    Usage (stream)::
        supervisor = get_supervisor()
        service = ChatService(supervisor)
        async for event in service.stream(user_input):
            yield event
    """

    def __init__(self, agent: CompiledStateGraph) -> None:
        """Initialize the service with a compiled agent graph.

        Args:
            agent: A compiled LangGraph agent.
        """
        self._agent = agent
        self._streaming = ChatStreamingService(agent)

    async def invoke(
        self,
        db: AsyncSession,
        user_input: UserInput,
    ) -> ChatMessage:
        """Invoke the agent synchronously and return the final response.

        Args:
            db: Database session for persistence.
            user_input: Validated user input.

        Returns:
            The final ChatMessage from the agent.

        Raises:
            HTTPException: If no models available or agent returns no events.
        """
        # 1. Resolve model (with default → first-active fallback)
        initial_model = resolve_model_name(user_input.model_name)
        if not initial_model:
            logger.error("No models available for invoke")
            raise HTTPException(
                status_code=503,
                detail="No AI models are currently available.",
            )
        if user_input.model_name:
            await refresh_model_cache_if_missing(initial_model)

        # 2. Build agent parameters
        kwargs = await build_agent_kwargs(user_input)
        config = kwargs["config"]
        context = kwargs["context"]

        thread_id_str = config.get("configurable", {}).get("thread_id", "")
        thread_id = (
            UUID(thread_id_str) if isinstance(thread_id_str, str) else thread_id_str
        )
        request_id = context.request_id or "unknown"

        logger.info(
            "[request_id=%s][thread_id=%s] Invoke with model=%s",
            request_id,
            thread_id_str,
            initial_model,
        )

        # 2.5 Get state BEFORE execution for per-turn DAG construction
        before_checkpoint_id: str | None = None
        before_message_count: int = 0
        try:
            before_state = await self._agent.aget_state(config)
            configurable = before_state.config.get("configurable")
            before_checkpoint_id = (
                configurable.get("checkpoint_id") if configurable else None
            )
            before_message_count = len(before_state.values.get("messages", []))
            logger.debug(
                "Before execution: checkpoint_id=%s, message_count=%d",
                before_checkpoint_id,
                before_message_count,
            )
        except Exception as e:
            logger.warning("Failed to get state before execution: %s", e)

        # 3. Execute agent with timeout
        settings = get_settings()
        timeout = (
            settings.AGENT_INVOKE_TIMEOUT if settings.AGENT_INVOKE_TIMEOUT > 0 else None
        )

        try:
            response_events: list[tuple[str, Any]] = []
            async with asyncio.timeout(timeout):
                async for mode, chunk in self._agent.astream(
                    kwargs["input"],
                    config=config,
                    stream_mode=["updates", "values"],
                ):
                    response_events.append((mode, chunk))
        except TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=f"Agent invocation timed out after {timeout:.0f}s.",
            )

        if not response_events:
            raise HTTPException(
                status_code=500,
                detail="Agent invocation returned no events",
            )

        # 4. Parse response
        response_type, response = response_events[-1]

        if response_type == "values":
            output = langchain_to_chat_message(response["messages"][-1])
        elif response_type == "updates" and "__interrupt__" in response:
            output = langchain_to_chat_message(
                AIMessage(content=response["__interrupt__"][0].value)
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected response type: {response_type}",
            )

        # 5. Accumulate token usage
        tokens = self._accumulate_tokens_from_events(response_events)

        # 6. Persist tokens + DAG
        await persist_agent_trace(
            db=db,
            agent=self._agent,
            thread_id=thread_id,
            request_id=request_id,
            model_name=initial_model,
            tokens=tokens,
            before_checkpoint_id=before_checkpoint_id,
            before_message_count=before_message_count,
        )

        return output

    async def stream(
        self,
        user_input: UserInput,
    ) -> AsyncGenerator[str, None]:
        """Stream the agent response via SSE.

        Token accumulation and persistence happen inside the streaming service.
        The API layer calls this generator directly and wraps it in StreamingResponse.

        Args:
            user_input: Validated user input.

        Yields:
            SSE-formatted strings.
        """
        # Delegate to ChatStreamingService which handles:
        # 1. Model resolution
        # 2. Agent parameter building
        # 3. SSE projection
        # 4. Persistence in finally block
        async for event in self._streaming.generate(user_input):
            yield event

    def _accumulate_tokens_from_events(
        self,
        events: list[tuple[str, object]],
    ) -> dict[str, int]:
        """Accumulate token usage from agent response events.

        Args:
            events: List of (mode, chunk) tuples from agent.astream.

        Returns:
            Token totals dict with keys: input_tokens, output_tokens, total_tokens.
        """
        from app.utils.message import extract_usage, accumulate_usage, empty_totals

        totals = empty_totals()
        for event_type, event in events:
            if event_type == "values" and isinstance(event, dict):
                messages = event.get("messages", [])
                for msg in messages:
                    if isinstance(msg, AIMessage):
                        usage = extract_usage(msg)
                        if usage:
                            accumulate_usage(totals, usage)
        return totals
