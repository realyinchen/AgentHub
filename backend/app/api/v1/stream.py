"""SSE Streaming Module for Agent Responses (LangChain v1.3 + stream_events v3)

Streams agent responses as Server-Sent Events using LangChain's typed-projection
API (`astream_events(version="v3")`). Model fallback is handled silently by the
@wrap_model_call middleware (app.agents.middleware.model) — completely transparent
to the user. This module focuses purely on SSE formatting and event consumption.

Architecture:
- _stream_with_model: Core stream consumer using v3 typed projections
  - stream.messages: token-by-token deltas + finalized AI messages + usage
  - stream.tool_calls: tool execution lifecycle
- streaming_message_generator: Thin entry point that wires user_input + agent
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.infra.database import get_database
from app.infra.llm import ModelManager
from app.schemas.chat import UserInput
from app.utils.async_writer import AsyncWriteQueue
from app.utils.request_handler import build_agent_kwargs
from app.utils.message_utils import langchain_to_chat_message
from app.utils.token_utils import extract_usage, accumulate_usage, empty_totals
from app.crud import chat as chat_crud


logger = logging.getLogger(__name__)


# ── SSE Formatting Helpers ──────────────────────────────────────────


def _sse(data: dict) -> str:
    """Format a dict as an SSE data event."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_error(content: str, error_type: str = "error") -> str:
    return _sse({"type": "error", "content": content, "error_type": error_type})


# ── Content Helpers ─────────────────────────────────────────────────


def _has_meaningful_content(output: Any) -> bool:
    """Check if an AI message output has actual text content (not just tool calls)."""
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


# ── Core Streaming Logic ────────────────────────────────────────────


async def _consume_messages_projection(
    stream: Any,
    out_queue: asyncio.Queue,
    state: dict,
) -> None:
    """Consume `stream.messages` projection — token deltas + finalized messages.

    Pushes SSE strings into `out_queue`. Updates `state` with:
    - step_counter: incremented when AI emits content
    - accumulated_tokens: usage totals across all model calls
    - final_message: last AI message (for memory extraction)
    - first_chunk_time: timestamp of first emitted token
    """
    async for message in stream.messages:
        # message has: .node, .text (deltas), .reasoning (deltas), .tool_calls, .output (final)

        # Stream text deltas
        async for delta in message.text:
            if delta:
                if state["first_chunk_time"] is None:
                    state["first_chunk_time"] = time.perf_counter()
                await out_queue.put(_sse({"type": "token", "content": delta}))

        # Stream reasoning deltas (thinking models)
        async for delta in message.reasoning:
            if delta:
                await out_queue.put(_sse({"type": "reasoning", "content": delta}))

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
                _sse({"type": "usage", "content": {"node": node_name, "usage": usage}})
            )

        # Emit ai_thinking step if there's meaningful content
        if _has_meaningful_content(final):
            state["step_counter"] += 1
            await out_queue.put(
                _sse(
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


async def _consume_tool_calls_projection(
    stream: Any,
    out_queue: asyncio.Queue,
    state: dict,
) -> None:
    """Consume `stream.tool_calls` projection — tool execution lifecycle.

    Each call has: .tool_name, .input, .output_deltas, .output, .error
    """
    async for call in stream.tool_calls:
        tool_name = getattr(call, "tool_name", "unknown")

        # Tool start
        state["step_counter"] += 1
        await out_queue.put(
            _sse(
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

        # Wait for final output (this is required to await call completion)
        try:
            await call.output
        except Exception as e:
            logger.warning(f"Tool {tool_name} raised: {e}")

        # Tool end
        await out_queue.put(
            _sse(
                {
                    "type": "step",
                    "step": state["step_counter"],
                    "action": "tool_result",
                    "status": "completed",
                }
            )
        )


async def _consume_values_projection(
    stream: Any,
    out_queue: asyncio.Queue,
    state: dict,
) -> None:
    """Consume `stream.values` to capture final state.messages for SSE message event."""
    async for snapshot in stream.values:
        # Track latest snapshot — the last one will have the full message list
        messages = snapshot.get("messages") if isinstance(snapshot, dict) else None
        if messages:
            state["final_state_messages"] = messages


async def streaming_message_generator(
    user_input: UserInput, agent: CompiledStateGraph
) -> AsyncGenerator[str, None]:
    """Generate SSE events from agent execution using LangChain v3 event streaming.

    This is the main entry point called by /chat/stream. Model fallback is
    handled inside the agent graph by @wrap_model_call middleware, so this
    function does NOT need to wrap an outer retry loop.

    Args:
        user_input: Validated user input from the request
        agent: Compiled state graph (created via create_agent + middleware)

    Yields:
        SSE-formatted strings (e.g. "data: {...}\\n\\n")
    """
    # ── Validate model availability ────────────────────────────────
    initial_model = user_input.model_name
    if not initial_model:
        initial_model = (
            ModelManager.get_default_llm_id()
            or ModelManager.get_first_active_llm_id()
        )
        if not initial_model:
            logger.error("No models available for streaming")
            yield _sse_error(
                "No AI models are currently available. Please check your configuration.",
                error_type="no_models_available",
            )
            return
        # Pin the chosen model into user_input so build_agent_kwargs + middleware see it
        user_input = user_input.model_copy(update={"model_name": initial_model})

    # ── Build agent invocation kwargs ──────────────────────────────
    kwargs = await build_agent_kwargs(user_input)
    config = kwargs["config"]
    context = kwargs["context"]

    # `thread_id` is the only field carried in configurable (checkpointer
    # contract). All other runtime fields live on `context` (ChatbotContext).
    thread_id_str = config["configurable"]["thread_id"]
    user_id = context.user_id or "unknown"
    request_id = context.request_id or "unknown"
    thread_id = (
        uuid.UUID(thread_id_str) if isinstance(thread_id_str, str) else thread_id_str
    )

    logger.info(
        "[request_id=%s][user_id=%s][thread_id=%s] Starting stream with model=%s",
        request_id,
        user_id,
        thread_id_str,
        initial_model,
    )

    # ── Stream state (mutated by consumer coroutines) ──────────────
    state = {
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
    yield _sse(
        {
            "type": "step",
            "step": state["step_counter"],
            "action": "human",
            "content": user_input.content,
        }
    )

    # ── Run stream + consumers concurrently, drained via queue ─────
    # Event-driven pattern (no polling): use a sentinel to signal completion,
    # ensuring zero latency on token delivery.
    out_queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()  # signals "all consumers finished" to the drain loop
    consumer_tasks: list[asyncio.Task] = []
    completion_task: asyncio.Task | None = None
    stream = None

    try:
        # Open v3 event stream
        stream = await agent.astream_events(
            kwargs["input"],
            config=config,
            context=context,
            version="v3",
        )

        # Launch projection consumers concurrently
        consumer_tasks = [
            asyncio.create_task(_consume_messages_projection(stream, out_queue, state)),
            asyncio.create_task(
                _consume_tool_calls_projection(stream, out_queue, state)
            ),
            asyncio.create_task(_consume_values_projection(stream, out_queue, state)),
        ]

        async def _wait_and_signal():
            """Wait for all projection consumers, then push sentinel to unblock the drain loop.

            Surfaces consumer exceptions via the sentinel value (Exception instance).
            """
            try:
                await asyncio.gather(*consumer_tasks)
                await out_queue.put(_SENTINEL)
            except Exception as e:
                logger.exception(f"Consumer task failed: {e}")
                # Push the exception so the drain loop can re-raise / format
                await out_queue.put(e)

        completion_task = asyncio.create_task(_wait_and_signal())

        # Drain queue with zero polling latency
        while True:
            item = await out_queue.get()
            if item is _SENTINEL:
                # All consumers finished cleanly
                break
            if isinstance(item, Exception):
                # Consumer raised — emit error and exit
                yield _sse_error(
                    f"Stream error: {type(item).__name__}: {str(item)[:200]}"
                )
                break
            yield item

    except Exception as e:
        logger.exception(f"Stream setup error: {e}")
        yield _sse_error(f"Stream error: {type(e).__name__}: {str(e)[:200]}")

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
                    yield _sse({"type": "message", "content": chat_msg.model_dump()})
                except Exception as e:
                    logger.error(f"Error converting final message: {e}")

        # ── Persist token usage (non-blocking) ─────────────────────
        tokens = state["accumulated_tokens"]
        if tokens["total_tokens"] > 0:
            db = get_database()

            async def _update_tokens() -> None:
                async with db.session() as session:
                    await chat_crud.update_conversation_tokens(
                        db=session,
                        thread_id=thread_id,
                        input_tokens=tokens["input_tokens"],
                        cache_read=tokens["cache_read"],
                        output_tokens=tokens["output_tokens"],
                        reasoning=tokens["reasoning"],
                        total_tokens=tokens["total_tokens"],
                    )

            write_queue.add("update_conversation_tokens", _update_tokens())

        # ── Build and persist execution DAG (non-blocking) ─────────
        try:
            from app.observability import DagBuilder
            from app.crud import trace as trace_crud

            tokens = state["accumulated_tokens"]

            async def _persist_dag() -> None:
                db = get_database()
                dag_builder = DagBuilder(agent)
                dag = await dag_builder.get_execution_dag(thread_id_str)
                async with db.session() as session:
                    await trace_crud.upsert_trace(
                        db=session,
                        thread_id=thread_id,
                        agent_id=user_input.agent_id,
                        request_id=str(request_id),
                        dag_data=dag.model_dump(),
                        total_steps=len(dag.steps),
                        model_name=initial_model,
                        input_tokens=tokens["input_tokens"],
                        cache_read=tokens["cache_read"],
                        output_tokens=tokens["output_tokens"],
                        reasoning=tokens["reasoning"],
                        total_tokens=tokens["total_tokens"],
                    )

            write_queue.add("persist_dag", _persist_dag())
        except Exception:
            logger.exception(
                "Failed to build/persist DAG for thread %s", thread_id_str
            )

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
