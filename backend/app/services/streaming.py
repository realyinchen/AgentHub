"""SSE Streaming Service — ChatStreamingService business logic.

This module contains the business logic for streaming agent responses via SSE.
Moved from utils/sse.py to follow layer separation:
- Services layer: business logic (ChatStreamingService)
- Utils layer: helper functions (sse, sse_error, AsyncWriteQueue)

Architecture:
    - **Projection consumers** run as concurrent ``asyncio.Task`` instances,
      each consuming a single projection (``.messages``, ``.tool_calls``,
      ``.values``) and pushing SSE strings into a shared ``asyncio.Queue``.
    - A **drain loop** reads from the queue with zero polling latency
      (sentinel-based signalling).
    - **State** is shared across consumers via a ``TypedDict`` (mutable
      dict — no dataclass copy overhead under concurrent access).

Model fallback is handled transparently by the ``@wrap_model_call``
middleware (``app.agents.middleware.model``) — this service never
retries or swaps models.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator

from langgraph.graph.state import CompiledStateGraph

from app.infra.config import get_settings
from app.infra.database import get_database
from app.infra.llm.resolver import resolve_model_name
from app.schemas.chat import UserInput
from app.utils.sse import (
    AsyncWriteQueue,
    StreamState,
    StreamV3Projection,
    sse,
    sse_error,
    has_meaningful_content,
)
from app.utils.request import build_agent_kwargs
from app.utils.message import (
    empty_totals,
    extract_usage,
    accumulate_usage,
    langchain_to_chat_message,
)


logger = logging.getLogger(__name__)


class ChatStreamingService:
    """SSE streaming service using LangGraph v3 typed projections.

    Encapsulates all projection consumers, queue management, state tracking,
    token accumulation, DAG persistence, and SSE formatting. The agent is
    injected via the constructor so the service can be unit-tested with a
    mock graph.

    Usage::

        supervisor = get_supervisor()
        service = ChatStreamingService(supervisor)
        async for sse_event in service.generate(user_input):
            yield sse_event
    """

    def __init__(self, agent: CompiledStateGraph) -> None:
        self._agent = agent

    # ── Public API ────────────────────────────────────────────────

    async def generate(self, user_input: UserInput) -> AsyncGenerator[str, None]:
        """Generate SSE events from agent execution using LangChain v3 event streaming.

        This is the main entry point called by ``/chat/stream``. Model fallback is
        handled inside the agent graph by ``@wrap_model_call`` middleware, so this
        method does **not** wrap an outer retry loop.

        Args:
            user_input: Validated user input from the request.

        Yields:
            SSE-formatted strings (e.g. ``"data: {...}\\n\\n"``).
        """
        # ── Validate model availability ────────────────────────────
        initial_model = resolve_model_name(user_input.model_name)
        if not initial_model:
            logger.error("No models available for streaming")
            yield sse_error(
                "No AI models are currently available. Please check your configuration.",
                error_type="no_models_available",
            )
            return
        # Pin the chosen model into user_input so build_agent_kwargs + middleware see it
        if not user_input.model_name:
            user_input = user_input.model_copy(update={"model_name": initial_model})

        # ── Build agent invocation kwargs ──────────────────────────
        kwargs = await build_agent_kwargs(user_input)
        config = kwargs["config"]
        context = kwargs["context"]

        # `thread_id` is the only field carried in configurable (checkpointer
        # contract). All other runtime fields live on `context` (AgentRuntimeContext).
        thread_id_str = config.get("configurable", {}).get("thread_id", "")
        user_id = context.user_id or "unknown"
        request_id = context.request_id or "unknown"
        thread_id = (
            uuid.UUID(thread_id_str)
            if isinstance(thread_id_str, str)
            else thread_id_str
        )

        logger.info(
            "[request_id=%s][user_id=%s][thread_id=%s] Starting stream with model=%s",
            request_id,
            user_id,
            thread_id_str,
            initial_model,
        )

        # ── Stream state (mutated by consumer coroutines) ──────────
        state: StreamState = {
            "step_counter": 0,
            "first_chunk_time": None,
            "accumulated_tokens": empty_totals(),
            "final_message": None,
            "final_state_messages": None,
        }
        started_at = time.perf_counter()
        write_queue = AsyncWriteQueue()

        # ── Send SSE prelude to flush through proxies ──────────────
        yield f": {' ' * 2048}\n\n"

        # ── Emit initial human step ────────────────────────────────
        state["step_counter"] += 1
        yield sse(
            {
                "type": "step",
                "step": state["step_counter"],
                "action": "human",
                "content": user_input.content,
            }
        )

        # ── Resolve stream timeout ─────────────────────────────────
        settings = get_settings()
        stream_timeout = (
            settings.AGENT_STREAM_TIMEOUT if settings.AGENT_STREAM_TIMEOUT > 0 else None
        )

        # ── Run stream + consumers concurrently, drained via queue ─
        out_queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()
        consumer_tasks: list[asyncio.Task] = []
        completion_task: asyncio.Task | None = None
        stream = None

        try:
            # Open v3 event stream (with timeout if configured)
            async with asyncio.timeout(stream_timeout):
                stream = await self._agent.astream_events(
                    kwargs["input"],
                    config=config,
                    context=context,
                    version="v3",
                )

                # Launch projection consumers concurrently
                consumer_tasks = [
                    asyncio.create_task(
                        self._consume_messages(stream, out_queue, state)
                    ),
                    asyncio.create_task(
                        self._consume_tool_calls(stream, out_queue, state)
                    ),
                    asyncio.create_task(self._consume_values(stream, out_queue, state)),
                ]

                async def _wait_and_signal():
                    """Wait for all projection consumers, then push sentinel."""
                    try:
                        await asyncio.gather(*consumer_tasks)
                        await out_queue.put(_SENTINEL)
                    except Exception as e:
                        logger.exception("Consumer task failed: %s", e)
                        await out_queue.put(e)

                completion_task = asyncio.create_task(_wait_and_signal())

                # Drain queue with zero polling latency
                while True:
                    item = await out_queue.get()
                    if item is _SENTINEL:
                        break
                    if isinstance(item, Exception):
                        yield sse_error(
                            f"Stream error: {type(item).__name__}: {str(item)[:200]}"
                        )
                        break
                    yield item

        except asyncio.TimeoutError:
            logger.error(
                "Stream timed out after %.0fs: thread_id=%s",
                stream_timeout,
                thread_id_str,
            )
            yield sse_error(
                f"Request timed out after {stream_timeout:.0f}s. Please try again with a simpler query.",
                error_type="timeout",
            )
            return

        except Exception as e:
            logger.exception("Stream setup error: %s", e)
            yield sse_error(f"Stream error: {type(e).__name__}: {str(e)[:200]}")

        finally:
            # Cancel completion task if still running
            if completion_task is not None and not completion_task.done():
                completion_task.cancel()
                try:
                    await completion_task
                except (asyncio.CancelledError, Exception):
                    pass

            # Cancel any consumer tasks that might still be running
            for task in consumer_tasks:
                if not task.done():
                    task.cancel()
            if consumer_tasks:
                try:
                    await asyncio.gather(*consumer_tasks, return_exceptions=True)
                except Exception:
                    pass

            # Drain any remaining queued events
            while True:
                try:
                    item = out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is _SENTINEL or isinstance(item, Exception):
                    continue
                yield item

            # ── Emit final assembled message ───────────────────────
            final_messages = state.get("final_state_messages")
            if final_messages:
                last = final_messages[-1]
                if hasattr(last, "content") and last.content:
                    try:
                        chat_msg = langchain_to_chat_message(last)
                        yield sse({"type": "message", "content": chat_msg.model_dump()})
                    except Exception as e:
                        logger.error("Error converting final message: %s", e)

            # ── Persist tokens and DAG (non-blocking) ──────────────
            tokens = state["accumulated_tokens"]

            async def _persist_tokens_and_dag() -> None:
                """Persist token usage and execution DAG after stream completes."""
                from app.crud.trace import persist_agent_trace

                db = get_database()
                async with db.session() as session:
                    await persist_agent_trace(
                        db=session,
                        agent=self._agent,
                        thread_id=thread_id,
                        request_id=request_id,
                        model_name=initial_model,
                        tokens=tokens,
                    )

            write_queue.add("persist_tokens_and_dag", _persist_tokens_and_dag())

            # ── Performance log ────────────────────────────────────
            if state["first_chunk_time"] is not None:
                logger.info(
                    "Stream completed: first_chunk=%.1fms, total=%.1fms",
                    (state["first_chunk_time"] - started_at) * 1000,
                    (time.perf_counter() - started_at) * 1000,
                )

            yield "data: [DONE]\n\n"

            # Wait for pending DB writes
            await write_queue.wait_all()

    # ── Projection consumers (private) ─────────────────────────────────────

    async def _consume_messages(
        self,
        stream: StreamV3Projection,
        out_queue: asyncio.Queue,
        state: StreamState,
    ) -> None:
        """Consume ``stream.messages`` projection — token deltas + finalized messages.

        Pushes SSE strings into ``out_queue``. Updates ``state`` with:
        - ``step_counter``: incremented when AI emits content
        - ``accumulated_tokens``: usage totals across all model calls
        - ``final_message``: last AI message (for memory extraction)
        - ``first_chunk_time``: timestamp of first emitted token
        """
        async for message in stream.messages:
            # Stream text deltas
            async for delta in message.text:
                if delta:
                    if state["first_chunk_time"] is None:
                        state["first_chunk_time"] = time.perf_counter()
                    await out_queue.put(sse({"type": "token", "content": delta}))

            # Stream reasoning deltas (thinking models)
            async for delta in message.reasoning:
                if delta:
                    await out_queue.put(sse({"type": "reasoning", "content": delta}))

            # Finalized message arrives last
            final = message.output
            if final is None:
                continue

            # Token usage
            usage = extract_usage(final)
            node_name = getattr(message, "node", "") or "model"
            if usage:
                accumulate_usage(state["accumulated_tokens"], usage)
                logger.info(
                    "[%s] Token usage: input=%d, output=%d, total=%d",
                    node_name,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    usage.get("total_tokens", 0),
                )
                await out_queue.put(
                    sse(
                        {
                            "type": "usage",
                            "content": {"node": node_name, "usage": usage},
                        }
                    )
                )

            # Emit ai_thinking step if there's meaningful content
            if has_meaningful_content(final):
                state["step_counter"] += 1
                await out_queue.put(
                    sse(
                        {
                            "type": "step",
                            "step": state["step_counter"],
                            "action": "ai_thinking",
                            "status": "thinking...",
                        }
                    )
                )

            # Track for memory extraction
            state["final_message"] = final

    async def _consume_tool_calls(
        self,
        stream: StreamV3Projection,
        out_queue: asyncio.Queue,
        state: StreamState,
    ) -> None:
        """Consume ``stream.tool_calls`` projection — tool execution lifecycle.

        Each call has: ``.tool_name``, ``.input``, ``.output_deltas``,
        ``.output``, ``.error``.
        """
        async for call in stream.tool_calls:
            tool_name = getattr(call, "tool_name", "unknown")

            # Tool start
            state["step_counter"] += 1
            await out_queue.put(
                sse(
                    {
                        "type": "step",
                        "step": state["step_counter"],
                        "action": "tool_call",
                        "name": tool_name,
                        "status": "calling",
                    }
                )
            )

            # Drain output_deltas if any (most tools don't stream)
            try:
                async for _ in call.output_deltas:
                    pass
            except Exception:
                pass

            # Wait for final output (required to await call completion)
            try:
                await call.output
            except Exception as e:
                logger.warning("Tool %s raised: %s", tool_name, e)

            # Tool end
            await out_queue.put(
                sse(
                    {
                        "type": "step",
                        "step": state["step_counter"],
                        "action": "tool_result",
                        "status": "completed",
                    }
                )
            )

    async def _consume_values(
        self,
        stream: StreamV3Projection,
        out_queue: asyncio.Queue,
        state: StreamState,
    ) -> None:
        """Consume ``stream.values`` to capture final state.messages for SSE message event."""
        async for snapshot in stream.values:
            if isinstance(snapshot, dict):
                # Track latest snapshot — the last one will have the full message list
                messages = snapshot.get("messages")
                if messages:
                    state["final_state_messages"] = messages
