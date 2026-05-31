"""SSE Streaming — LangGraph v3 typed-projection consumer (private module).

Wraps the agent's ``astream_events(version="v3")`` output in a
service class that yields Server-Sent Events (SSE) for the
``/chat/stream`` endpoint.

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

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable
from typing import Protocol, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.state import CompiledStateGraph

from app.infra.config import get_settings
from app.infra.database import get_database
from app.schemas.chat import UserInput
from app.services import AgentExecutionService
from app.utils.request_handler import build_agent_kwargs
from app.utils.message_utils import langchain_to_chat_message
from app.utils.stream_helpers import (
    resolve_model_name,
    empty_totals, extract_usage, accumulate_usage,
    log_routing_decision,
)

logger = logging.getLogger(__name__)


# ── Protocols & shared state ────────────────────────────────────────────────


class StreamV3Projection(Protocol):
    """Protocol for LangGraph v3 stream event projections.

    LangGraph's ``astream_events(version="v3")`` returns a typed proxy that
    exposes per-projection async iterators (``.messages``, ``.tool_calls``,
    ``.values``). This Protocol captures the subset used by our consumers.
    """

    @property
    def messages(self) -> AsyncIterator: ...

    @property
    def tool_calls(self) -> AsyncIterator: ...

    @property
    def values(self) -> AsyncIterator: ...


class StreamState(TypedDict):
    """Mutable state shared across projection consumer coroutines."""

    step_counter: int
    first_chunk_time: float | None
    accumulated_tokens: dict[str, int]
    final_message: BaseMessage | None
    final_state_messages: list[BaseMessage] | None


# ── SSE formatting helpers (inlined from app.utils.stream_events) ────────────

import json as _json


def sse(data: object) -> str:
    """Format data as a Server-Sent Event message."""
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"


def sse_error(content: str, error_type: str = "error") -> str:
    """Format an error as a Server-Sent Event message."""
    return sse({"type": "error", "content": content, "error_type": error_type})


def has_meaningful_content(output: object) -> bool:
    """Return whether a LangChain message output contains user-visible text."""
    if output is None:
        return False
    content = getattr(output, "content", "")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                if block.get("text", "").strip():
                    return True
    return False


# ── AsyncWriteQueue (inlined from app.utils.async_writer) ────────────────────


class AsyncWriteQueue:
    """Safe async write queue for SSE streaming — eliminates first-token jitter.

    Writes (e.g. DB persistence) are fire-and-forget during streaming, then
    awaited at the end. Concurrency is capped via a semaphore; retries use
    exponential backoff.

    Usage::

        queue = AsyncWriteQueue()
        queue.add("persist", _persist_tokens())
        # ... yield SSE events ...
        await queue.wait_all()
    """

    def __init__(self, max_concurrent: int = 8, timeout: float | None = None) -> None:
        self._tasks: list[asyncio.Task] = []
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._default_timeout = timeout

    def add(self, name: str, coro: Awaitable, max_retries: int = 3) -> None:
        async def _task():
            async with self._semaphore:
                for attempt in range(max_retries):
                    try:
                        return await coro
                    except Exception as exc:
                        if attempt < max_retries - 1:
                            backoff = 0.1 * (2 ** attempt)
                            logger.warning(
                                "[AsyncWriteQueue] Retry [%s] %d/%d: %s",
                                name, attempt + 1, max_retries, exc,
                            )
                            await asyncio.sleep(backoff)
                        else:
                            logger.error(
                                "[AsyncWriteQueue] Failed [%s] (exhausted): %s",
                                name, exc,
                            )
                            return None

        self._tasks.append(asyncio.create_task(_task()))

    async def wait_all(self, timeout: float | None = None) -> None:
        if not self._tasks:
            return
        actual_timeout = timeout or self._default_timeout
        try:
            if actual_timeout:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=actual_timeout,
                )
            else:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            logger.debug("[AsyncWriteQueue] Completed %d writes", len(self._tasks))
        except asyncio.TimeoutError:
            logger.warning(
                "[AsyncWriteQueue] Timeout (%ss), writes continue in background",
                actual_timeout,
            )
        finally:
            self._tasks.clear()

    async def __aenter__(self) -> "AsyncWriteQueue":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool:
        await self.wait_all()
        return False


# ── Service ─────────────────────────────────────────────────────────────────


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

    # ── Public API ────────────────────────────────────────────────────────

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
        # ── Validate model availability ────────────────────────────────
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

        # ── Build agent invocation kwargs ──────────────────────────────
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

        # ── Stream state (mutated by consumer coroutines) ──────────────
        state: StreamState = {
            "step_counter": 0,
            "first_chunk_time": None,
            "accumulated_tokens": empty_totals(),
            "final_message": None,
            "final_state_messages": None,
        }
        started_at = time.perf_counter()
        write_queue = AsyncWriteQueue()

        # ── Send SSE prelude to flush through proxies ──────────────────
        yield f": {' ' * 2048}\n\n"

        # ── Emit initial human step ────────────────────────────────────
        state["step_counter"] += 1
        yield sse(
            {
                "type": "step",
                "step": state["step_counter"],
                "action": "human",
                "content": user_input.content,
            }
        )

        # ── Resolve stream timeout ────────────────────────────────────
        settings = get_settings()
        stream_timeout = (
            settings.AGENT_STREAM_TIMEOUT
            if settings.AGENT_STREAM_TIMEOUT > 0
            else None
        )

        # ── Run stream + consumers concurrently, drained via queue ─────
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
                    asyncio.create_task(
                        self._consume_values(stream, out_queue, state)
                    ),
                ]

                async def _wait_and_signal():
                    """Wait for all projection consumers, then push sentinel."""
                    try:
                        await asyncio.gather(*consumer_tasks)
                        await out_queue.put(_SENTINEL)
                    except Exception as e:
                        logger.exception(f"Consumer task failed: {e}")
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
            logger.exception(f"Stream setup error: {e}")
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

            # ── Emit final assembled message ───────────────────────────
            final_messages = state.get("final_state_messages")
            if final_messages:
                last = final_messages[-1]
                if hasattr(last, "content") and last.content:
                    try:
                        chat_msg = langchain_to_chat_message(last)
                        yield sse(
                            {"type": "message", "content": chat_msg.model_dump()}
                        )
                    except Exception as e:
                        logger.error(f"Error converting final message: {e}")

            # Unified token + DAG persistence (non-blocking) via service
            tokens = state["accumulated_tokens"]
            execution_service = AgentExecutionService(self._agent)

            async def _persist_tokens_and_dag() -> None:
                db = get_database()
                async with db.session() as session:
                    await execution_service.persist(
                        db=session,
                        thread_id=thread_id,
                        request_id=str(request_id),
                        model_name=initial_model,
                        tokens=tokens,
                    )

            write_queue.add("persist_tokens_and_dag", _persist_tokens_and_dag())

            # ── Performance log ────────────────────────────────────────
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
                    await out_queue.put(
                        sse({"type": "reasoning", "content": delta})
                    )

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
                    f"[{node_name}] Token usage: input={usage.get('input_tokens', 0)}, "
                    f"output={usage.get('output_tokens', 0)}, total={usage.get('total_tokens', 0)}"
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
                logger.warning(f"Tool {tool_name} raised: {e}")

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
        """Consume ``stream.values`` to capture final state.messages for SSE message event.

        Also logs any ``structured_response`` (Stage 0 T03) for routing observability.
        """
        async for snapshot in stream.values:
            if isinstance(snapshot, dict):
                # Stage 0 T03: Log structured routing decision when available
                log_routing_decision(snapshot.get("structured_response"), prefix="Stream ")

                # Track latest snapshot — the last one will have the full message list
                messages = snapshot.get("messages")
                if messages:
                    state["final_state_messages"] = messages