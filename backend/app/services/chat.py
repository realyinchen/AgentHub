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
from app.services.agent_runtime import (
    finalize_runtime_receipt,
)
from app.services.agent_runtime.finalizer import receipt_tool_info, receipt_trace_steps
from app.services.agent_runtime.persistence import persist_runtime_finalized_turn
from app.services.agent_runtime.execution_graph import build_execution_graph
from app.services.conversation import ConversationJournalService
from app.services.agent_core.chat_entry import AgentChatEntry
from app.services.agent_core.legacy_chat_runtime import LegacyChatRuntimeBridge
from app.services.agent_core.publication.commit import (
    TurnPublicationCommitter,
)
from app.services.agent_core.shadow_enrollment import (
    is_current_shadow_enrollment,
    prepare_shadow_enrollment,
)


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

    def __init__(
        self,
        agent: CompiledStateGraph,
        *,
        agent_entry: AgentChatEntry | None = None,
        legacy_bridge: LegacyChatRuntimeBridge | None = None,
    ) -> None:
        """Initialize the service with a compiled agent graph.

        Args:
            agent: A compiled LangGraph agent.
        """
        self._agent = agent
        self._agent_entry = agent_entry or AgentChatEntry()
        self._legacy_bridge = legacy_bridge or LegacyChatRuntimeBridge()
        self._streaming = ChatStreamingService(
            agent,
            agent_entry=self._agent_entry,
            legacy_bridge=self._legacy_bridge,
        )

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
        journal = ConversationJournalService()
        settings = get_settings()
        controller_mode = settings.AGENT_CONTROLLER_V1_MODE
        prepared_shadow = prepare_shadow_enrollment(
            user_input,
            mode=controller_mode,
            model_resolver=resolve_model_name,
            source_commit_sha=settings.AGENT_RELEASE_COMMIT_SHA,
        )
        user_input = prepared_shadow.user_input
        initial_model = prepared_shadow.resolved_model_name
        user_event = await journal.record_user_message(
            db,
            user_input,
            shadow_enrollment=prepared_shadow.enrollment,
        )
        # The user event is the authoritative source for every downstream
        # decision and side effect, so it must be durable before any runtime
        # opens an independent transaction.
        await db.commit()
        agent_entry = self._agent_entry
        controller_attempt = None
        run_controller = controller_mode != "off"
        if controller_mode == "shadow" and not is_current_shadow_enrollment(
            user_event.shadow_enrollment,
            source_commit_sha=settings.AGENT_RELEASE_COMMIT_SHA,
        ):
            run_controller = False
            logger.info(
                "[request_id=%s] Shadow skipped: no current durable enrollment",
                user_input.request_id,
            )
        if run_controller:
            requested_model = user_input.model_uuid or user_input.model_name
            initial_model = initial_model or resolve_model_name(
                requested_model
            )
            if not initial_model:
                raise HTTPException(
                    status_code=503,
                    detail="No AI models are currently available.",
                )
            if requested_model:
                await refresh_model_cache_if_missing(initial_model)
            if user_input.model_name != initial_model:
                user_input = user_input.model_copy(
                    update={"model_name": initial_model}
                )
            entry = await agent_entry.run(
                db,
                user_input=user_input,
                model_name=initial_model,
                journal_sequence_watermark=user_event.sequence_no,
                shadow_enrollment=user_event.shadow_enrollment,
            )
            controller_attempt = entry.attempt
            if entry.handled:
                if entry.message is None or entry.answer is None:
                    raise HTTPException(
                        status_code=503,
                        detail="Agent Controller did not produce a safe response.",
                    )
                committed = await TurnPublicationCommitter().commit(
                    db,
                    user_input=user_input,
                    answer=entry.answer,
                    turn=entry.attempt.turn,
                    model_name=initial_model,
                    agent_mode=str(
                        entry.message.custom_data.get(
                            "agent_mode", "controller_v1"
                        )
                    ),
                )
                return committed.message
            logger.info(
                "[request_id=%s] Agent Controller shadow status=%s",
                user_input.request_id,
                entry.attempt.status,
            )

        legacy_result = await self._legacy_bridge.prepare(
            user_input,
            model_name=str(user_input.model_uuid or user_input.model_name or ""),
            agent=self._agent,
        )
        runtime_turn = legacy_result.turn
        if runtime_turn is None:
            requested_model = user_input.model_uuid or user_input.model_name
            initial_model = initial_model or resolve_model_name(requested_model)
            if not initial_model:
                raise HTTPException(
                    status_code=503,
                    detail="No AI models are currently available.",
                )
            if requested_model:
                await refresh_model_cache_if_missing(initial_model)
            if user_input.model_name != initial_model:
                user_input = user_input.model_copy(update={"model_name": initial_model})
            plain_entry = await agent_entry.run_plain(
                db,
                user_input=user_input,
                model_name=initial_model,
                attempt=controller_attempt,
            )
            if plain_entry.answer is None:
                raise HTTPException(
                    status_code=503,
                    detail="Plain chat did not produce a safe response.",
                )
            committed = await TurnPublicationCommitter().commit(
                db,
                user_input=user_input,
                answer=plain_entry.answer,
                turn=None,
                model_name=initial_model,
                agent_mode="plain_chat",
            )
            return committed.message
        if runtime_turn.can_finalize_without_model:
            output = finalize_runtime_receipt(
                runtime_turn.plan,
                runtime_turn.receipt,
            )
            await persist_runtime_finalized_turn(
                agent=self._agent,
                user_input=user_input,
                message=output,
                plan=runtime_turn.plan,
                receipt=runtime_turn.receipt,
                db=db,
            )
            await journal.record_assistant_message(
                db,
                user_input=user_input,
                message=output,
            )
            return output

        # 1. Resolve model (with default → first-active fallback)
        requested_model = user_input.model_uuid or user_input.model_name
        initial_model = initial_model or resolve_model_name(requested_model)
        if not initial_model:
            logger.error("No models available for invoke")
            raise HTTPException(
                status_code=503,
                detail="No AI models are currently available.",
            )
        if requested_model:
            await refresh_model_cache_if_missing(initial_model)
        if not user_input.model_name or user_input.model_name != initial_model:
            user_input = user_input.model_copy(update={"model_name": initial_model})

        # 2. Build agent parameters
        kwargs = await build_agent_kwargs(user_input)
        config = kwargs["config"]
        context = kwargs["context"]
        runtime_tool_steps = receipt_trace_steps(
            runtime_turn.receipt,
            plan=runtime_turn.plan,
        )
        context.action_plan = runtime_turn.plan.model_dump(mode="json")
        context.plan_receipt = runtime_turn.receipt.model_dump(mode="json")

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
                    context=context,
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
            system_tool_steps=runtime_tool_steps,
            system_execution_graph=build_execution_graph(
                runtime_turn.plan,
                runtime_turn.receipt,
            ),
        )

        output.custom_data.update(
            {
                "action_plan": runtime_turn.plan.model_dump(mode="json"),
                "plan_receipt": runtime_turn.receipt.model_dump(mode="json"),
                "runtime_trace": {
                    "request_id": request_id,
                    "plan_id": runtime_turn.plan.plan_id,
                    "route_type": runtime_turn.plan.route_type,
                    "intent": runtime_turn.plan.intent,
                    "planner_used": runtime_turn.plan.planner_used,
                    "receipt_status": runtime_turn.receipt.status,
                    "duration_ms": runtime_turn.receipt.duration_ms,
                },
                "tool_info": receipt_tool_info(
                    runtime_turn.receipt,
                    plan=runtime_turn.plan,
                ),
            }
        )

        await journal.record_assistant_message(
            db,
            user_input=user_input,
            message=output,
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
