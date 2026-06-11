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
from app.infra.llm.resolver import refresh_model_cache_if_missing, resolve_model_name
from app.schemas.chat import UserInput
from app.utils.sse import (
    AsyncWriteQueue,
    StreamState,
    StreamV3Projection,
    sse,
    sse_error,
)
from app.utils.request import build_agent_kwargs
from app.utils.message import (
    empty_totals,
    accumulate_usage,
    extract_usage,
    extract_thinking,
    langchain_to_chat_message,
)


logger = logging.getLogger(__name__)


def _should_use_non_streaming_agent_path(model_name: str, thinking_mode: bool) -> bool:
    """Return True when provider reasoning is not available through streaming."""
    if not thinking_mode:
        return False

    from app.infra.llm.manager import get_model_manager
    from app.infra.llm.provider_adapters import get_provider_adapter

    manager = get_model_manager()
    model_config = manager.get_model(model_name)
    if model_config is None and "/" in model_name:
        model_config = manager.get_model(model_name.split("/", 1)[1])
    if model_config is None:
        return False

    adapter = get_provider_adapter(str(model_config.provider))
    return not adapter.streaming_enabled(thinking_mode)


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
        if user_input.model_name:
            await refresh_model_cache_if_missing(initial_model)
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

        # ── Get state BEFORE execution for per-turn DAG construction ──────────
        before_checkpoint_id: str | None = None
        before_message_count: int = 0
        try:
            before_state = await self._agent.aget_state(config)
            configurable = before_state.config.get("configurable")
            before_checkpoint_id = (
                configurable.get("checkpoint_id") if configurable else None
            )
            before_message_count = len(before_state.values.get("messages", []))
            # Log full state for debugging
            logger.debug(
                "Before execution: checkpoint_id=%s, message_count=%d, state_values_keys=%s",
                before_checkpoint_id,
                before_message_count,
                list(before_state.values.keys()) if before_state.values else [],
            )
        except Exception as e:
            logger.warning("Failed to get state before execution: %s", e)

        # ── Stream state (mutated by consumer coroutines) ──────────
        state: StreamState = {
            "step_counter": 0,
            "first_chunk_time": None,
            "accumulated_tokens": empty_totals(),
            "accumulated_reasoning": "",  # Current accumulated reasoning (resets per LLM call)
            "last_reasoning": "",  # Most recent AI reasoning for final SSE message
            "reasoning_segments": {},  # reasoning content keyed by message_id
            "ai_reasoning_index": 0,  # Stable AI-message order for DAG injection
            "final_message": None,
            "final_state_messages": None,
        }
        started_at = time.perf_counter()
        write_queue = AsyncWriteQueue()

        # ── Send SSE prelude to flush through proxies ──────────────
        yield f": {' ' * 2048}\n\n"

        # ── Emit request_start event with request_id ───────────────
        yield sse({"type": "request_start", "request_id": request_id})

        # ── Emit initial human step ─────────────────────────────────
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
        if _should_use_non_streaming_agent_path(
            initial_model,
            user_input.thinking_mode,
        ):
            async for event in self._generate_non_streaming_sse(
                kwargs=kwargs,
                config=config,
                context=context,
                thread_id=thread_id,
                request_id=request_id,
                model_name=initial_model,
                timeout=stream_timeout,
                before_checkpoint_id=before_checkpoint_id,
                before_message_count=before_message_count,
            ):
                yield event
            return

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
                        self._consume_messages(stream, out_queue, state, started_at)
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
                # Force flush after each yield to ensure real-time streaming
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
                    # Force flush: yield control to event loop AND give the ASGI
                    # transport enough time to actually write to the socket.
                    # asyncio.sleep(0) only yields to the event loop but the
                    # transport may coalesce multiple write() calls in the same
                    # tick into a single TCP packet (writev batching).
                    # A 1ms sleep ensures the transport flushes before the next
                    # item is yielded, giving true per-event streaming at the
                    # cost of ~1ms/event overhead — negligible for UX.
                    await asyncio.sleep(0.001)

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
            accumulated_reasoning = state.get("last_reasoning", "") or state.get(
                "accumulated_reasoning", ""
            )

            if final_messages:
                # Find the last AIMessage (skip ToolMessage, HumanMessage, etc.)
                # ToolMessage contains tool results which should not be shown as AI response
                last_ai_msg = None
                for msg in reversed(final_messages):
                    # Check if this is an AIMessage (has type='ai' or is AIMessage class)
                    msg_type = getattr(msg, "type", None)
                    if msg_type == "ai":
                        last_ai_msg = msg
                        break

                if (
                    last_ai_msg
                    and hasattr(last_ai_msg, "content")
                    and last_ai_msg.content
                ):
                    try:
                        # Store thinking in additional_kwargs for immediate frontend display
                        # Note: This modification is in-memory only and won't persist to checkpointer
                        # The thinking content is passed via custom_data below for frontend display
                        if accumulated_reasoning and hasattr(
                            last_ai_msg, "additional_kwargs"
                        ):
                            last_ai_msg.additional_kwargs["thinking"] = (
                                accumulated_reasoning
                            )

                        chat_msg = langchain_to_chat_message(last_ai_msg)
                        # Include request_id for DAG viewing
                        chat_msg.request_id = request_id
                        # Include accumulated reasoning in custom_data for frontend display
                        # This enables "View reasoning" expandable section after streaming ends
                        if accumulated_reasoning:
                            if chat_msg.custom_data is None:
                                chat_msg.custom_data = {}
                            chat_msg.custom_data["thinking"] = accumulated_reasoning
                        yield sse({"type": "message", "content": chat_msg.model_dump()})
                    except Exception as e:
                        logger.error("Error converting final message: %s", e)

            # ── Persist tokens and DAG (non-blocking) ──────────────
            tokens = state["accumulated_tokens"]
            # Pass reasoning_segments to persist_agent_trace for DAG reconstruction
            # This maps each AI message to its corresponding reasoning content
            reasoning_segments = state.get("reasoning_segments", {})
            if user_input.thinking_mode and not reasoning_segments:
                reasoning_segments = {"__thinking_status__": "requested_no_text"}

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
                        before_checkpoint_id=before_checkpoint_id,
                        before_message_count=before_message_count,
                        reasoning_segments=reasoning_segments,
                    )

            write_queue.add("persist_tokens_and_dag", _persist_tokens_and_dag())

            # Wait for pending DB writes BEFORE sending [DONE]
            # This ensures trace data is persisted before the frontend queries for steps
            await write_queue.wait_all()

            # ── Performance log ────────────────────────────────────
            if state["first_chunk_time"] is not None:
                logger.info(
                    "Stream completed: first_chunk=%.1fms, total=%.1fms",
                    (state["first_chunk_time"] - started_at) * 1000,
                    (time.perf_counter() - started_at) * 1000,
                )

            yield "data: [DONE]\n\n"

    # ── Projection consumers (private) ─────────────────────────────────────

    async def _generate_non_streaming_sse(
        self,
        *,
        kwargs: dict,
        config: dict,
        context: object,
        thread_id,
        request_id: str,
        model_name: str,
        timeout: float | None,
        before_checkpoint_id: str | None,
        before_message_count: int,
    ) -> AsyncGenerator[str, None]:
        """Use agent.ainvoke when provider reasoning is only available non-streaming."""
        yield sse({"type": "step", "step": 2, "action": "ai_thinking"})

        try:
            async with asyncio.timeout(timeout):
                result = await self._agent.ainvoke(
                    kwargs["input"],
                    config=config,
                    context=context,
                )
        except asyncio.TimeoutError:
            yield sse_error(
                f"Request timed out after {timeout:.0f}s. Please try again with a simpler query.",
                error_type="timeout",
            )
            return
        except Exception as exc:
            logger.exception("Non-streaming agent fallback failed: %s", exc)
            yield sse_error(
                f"Stream error: {type(exc).__name__}: {str(exc)[:200]}",
            )
            return

        messages = result.get("messages", []) if isinstance(result, dict) else []
        new_messages = messages[before_message_count:]
        last_ai_msg = None
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "ai":
                last_ai_msg = msg
                break

        if last_ai_msg is None:
            yield sse_error("Agent invocation returned no AI message")
            return

        thinking = extract_thinking(last_ai_msg)
        if thinking:
            yield sse({"type": "reasoning", "content": thinking})

        chat_msg = langchain_to_chat_message(last_ai_msg)
        chat_msg.request_id = request_id
        if thinking:
            chat_msg.custom_data["thinking"] = thinking

        if chat_msg.content:
            yield sse({"type": "token", "content": chat_msg.content})
        yield sse({"type": "message", "content": chat_msg.model_dump()})

        tokens = empty_totals()
        for msg in new_messages:
            if getattr(msg, "type", None) != "ai":
                continue
            usage = extract_usage(msg)
            if usage:
                accumulate_usage(tokens, usage)

        reasoning_segments: dict[str, str] = {}
        if thinking:
            msg_id = getattr(last_ai_msg, "id", None) or str(id(last_ai_msg))
            ai_messages = [
                msg for msg in new_messages if getattr(msg, "type", None) == "ai"
            ]
            ai_index = max(0, len(ai_messages) - 1)
            reasoning_segments[msg_id] = thinking
            reasoning_segments[f"__ai_index_{ai_index}"] = thinking
            reasoning_segments["__latest__"] = thinking
        else:
            reasoning_segments["__thinking_status__"] = "requested_no_text"

        try:
            from app.crud.trace import persist_agent_trace

            db = get_database()
            async with db.session() as session:
                await persist_agent_trace(
                    db=session,
                    agent=self._agent,
                    thread_id=thread_id,
                    request_id=request_id,
                    model_name=model_name,
                    tokens=tokens,
                    before_checkpoint_id=before_checkpoint_id,
                    before_message_count=before_message_count,
                    reasoning_segments=reasoning_segments,
                )
        except Exception:
            logger.exception("Failed to persist non-streaming DAG for %s", request_id)

        yield "data: [DONE]\n\n"

    async def _consume_messages(
        self,
        stream: StreamV3Projection,
        out_queue: asyncio.Queue,
        state: StreamState,
        started_at: float,
    ) -> None:
        """Consume ``stream.messages`` projection — token deltas + finalized messages.

        Pushes SSE strings into ``out_queue``. Updates ``state`` with:
        - ``step_counter``: incremented when AI emits content
        - ``accumulated_tokens``: usage totals across all model calls
        - ``final_message``: last AI message (for memory extraction)
        - ``first_chunk_time``: timestamp of first emitted token

        DashScope (Qwen) thinking mode:
        - When enable_thinking=True, model returns reasoning_content in response
        - LangChain v3 normalizes this to message.reasoning projection
        - Token usage in usage_metadata or response_metadata.token_usage
        """
        async for message in stream.messages:
            # Log incoming message structure for debugging
            node_name = getattr(message, "node", "") or "model"

            # ── CRITICAL: Iterate deltas BEFORE accessing message.output ──
            # Per LangChain v3 docs, the correct pattern is:
            #   for delta in message.text:    # stream deltas in real-time
            #       print(delta)
            #   final = message.output         # access output AFTER deltas
            #
            # Previously we accessed message.output FIRST, which blocked until
            # the message was fully generated — defeating the purpose of streaming.
            # This caused all deltas to be buffered and delivered in one batch.

            # 0️⃣ Emit ai_thinking step BEFORE deltas (so frontend shows "thinking..." immediately)
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

            # 1️⃣ Stream reasoning deltas FIRST (real-time, before output is ready)
            # LangChain v3 normalizes provider-specific thinking/reasoning to message.reasoning
            # DashScope Qwen with enable_thinking=True emits reasoning_content
            reasoning_delta_count = 0
            async for delta in message.reasoning:
                if delta:
                    if (
                        not state["accumulated_reasoning"]
                        and not str(delta).strip()
                    ):
                        continue
                    reasoning_delta_count += 1
                    # Accumulate reasoning content for later inclusion in final message
                    state["accumulated_reasoning"] += delta
                    await out_queue.put(sse({"type": "reasoning", "content": delta}))

            # 2️⃣ Stream text deltas AFTER reasoning (real-time)
            # Only emit token events for model node — tool node content is
            # tool execution results, not AI-generated response tokens.
            text_delta_count = 0
            if node_name == "model":
                async for delta in message.text:
                    if delta:
                        text_delta_count += 1
                        if state["first_chunk_time"] is None:
                            state["first_chunk_time"] = time.perf_counter()
                        await out_queue.put(sse({"type": "token", "content": delta}))
            else:
                # Drain text deltas for non-model nodes without emitting
                async for _ in message.text:
                    pass

            # 3️⃣ AFTER delta iteration, access message.output for finalized message
            # At this point the message is complete and output is guaranteed available.
            final = message.output
            if final is None:
                logger.debug(
                    "[%s] message.output is None after delta iteration", node_name
                )
                continue

            # Handle AsyncProjection (some providers wrap output in awaitable)
            if hasattr(final, "__await__"):
                try:
                    final = await final
                except Exception as e:
                    logger.warning(
                        "[%s] Error awaiting message.output: %s", node_name, e
                    )
                    continue

            # Check message type - only process AIMessage for post-processing
            msg_type = getattr(final, "type", None)
            if msg_type != "ai":
                logger.debug(
                    "[%s] Skipping non-AI message type: %s", node_name, msg_type
                )
                continue

            # ── Track reasoning per message for DAG reconstruction ──────────
            # When an AIMessage is finalized, save the accumulated reasoning
            # to reasoning_segments keyed by message_id, then reset for next LLM call.
            # This ensures each AI node in the DAG gets its corresponding reasoning.
            if not state["accumulated_reasoning"]:
                final_reasoning = extract_thinking(final)
                if final_reasoning:
                    state["accumulated_reasoning"] = final_reasoning
                    await out_queue.put(
                        sse({"type": "reasoning", "content": final_reasoning})
                    )

            msg_id = getattr(final, "id", None) or str(id(final))
            accumulated = state["accumulated_reasoning"]
            ai_reasoning_index = state["ai_reasoning_index"]
            if accumulated:
                state["last_reasoning"] = accumulated
                state["reasoning_segments"][msg_id] = accumulated
                state["reasoning_segments"][f"__ai_index_{ai_reasoning_index}"] = (
                    accumulated
                )
                state["reasoning_segments"]["__latest__"] = accumulated
                # Reset accumulated reasoning for next LLM call
                state["accumulated_reasoning"] = ""
            state["ai_reasoning_index"] = ai_reasoning_index + 1

            node_name = getattr(message, "node", "") or "model"

            # Token usage extraction
            usage = None

            # 1. Try message.output.usage_metadata (official v3 API)
            if hasattr(final, "usage_metadata") and final.usage_metadata:
                usage = final.usage_metadata

            # 2. Try message.output.response_metadata.token_usage
            if not usage and hasattr(final, "response_metadata"):
                resp_meta = final.response_metadata
                if resp_meta and "token_usage" in resp_meta:
                    token_usage = resp_meta["token_usage"]
                    usage = {
                        "input_tokens": token_usage.get("prompt_tokens", 0),
                        "output_tokens": token_usage.get("completion_tokens", 0),
                        "total_tokens": token_usage.get("total_tokens", 0),
                    }

                # 2b. Try response_metadata.usage (LiteLLM style)
                if not usage and resp_meta and "usage" in resp_meta:
                    usage_obj = resp_meta["usage"]
                    if isinstance(usage_obj, dict):
                        usage = {
                            "input_tokens": usage_obj.get("prompt_tokens", 0),
                            "output_tokens": usage_obj.get("completion_tokens", 0),
                            "total_tokens": usage_obj.get("total_tokens", 0),
                        }

            # 3. Try message itself (in case usage is on the projection object)
            if (
                not usage
                and hasattr(message, "usage_metadata")
                and message.usage_metadata
            ):
                usage = message.usage_metadata

            # 4. Try additional_kwargs.usage
            if not usage and hasattr(final, "additional_kwargs"):
                add_kwargs = final.additional_kwargs
                if (
                    add_kwargs
                    and isinstance(add_kwargs, dict)
                    and "usage" in add_kwargs
                ):
                    usage_obj = add_kwargs["usage"]
                    if isinstance(usage_obj, dict):
                        usage = {
                            "input_tokens": usage_obj.get("prompt_tokens", 0),
                            "output_tokens": usage_obj.get("completion_tokens", 0),
                            "total_tokens": usage_obj.get("total_tokens", 0),
                        }

            if usage:
                accumulate_usage(state["accumulated_tokens"], usage)

                await out_queue.put(
                    sse(
                        {
                            "type": "usage",
                            "content": {
                                "node": node_name,
                                "usage": {
                                    "input_tokens": usage.get("input_tokens", 0),
                                    "output_tokens": usage.get("output_tokens", 0),
                                    "total_tokens": usage.get("total_tokens", 0),
                                },
                            },
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

        Emits SSE events in format expected by frontend:
        - ``type: "tool"`` when tool starts calling
        - ``type: "tool_result"`` when tool completes

        First tool event triggers frontend to stop loading animation.
        """
        tool_call_count = 0
        async for call in stream.tool_calls:
            tool_call_count += 1
            tool_name = getattr(call, "tool_name", "unknown")
            tool_id = (
                getattr(call, "id", None)
                or getattr(call, "callId", None)
                or str(uuid.uuid4())
            )
            tool_args = getattr(call, "input", {}) or getattr(call, "args", {}) or {}

            # Tool start - emit event for frontend to show "calling" state
            # First tool event stops loading animation
            state["step_counter"] += 1
            await out_queue.put(
                sse(
                    {
                        "type": "tool",
                        "content": {
                            "name": tool_name,
                            "tool_id": tool_id,
                            "args": tool_args if isinstance(tool_args, dict) else {},
                        },
                    }
                )
            )

            # Drain output_deltas if any (most tools don't stream)
            try:
                async for _ in call.output_deltas:
                    pass
            except Exception:
                pass

            # Get final output - in Python v3 streaming, call.output is direct access (not awaitable)
            # Per LangChain docs: "print(call.output, call.error)" - direct property access
            output = None
            error = None
            try:
                # call.output may be a ToolMessage object or string
                raw_output = call.output
                if raw_output is not None:
                    # Extract content from ToolMessage if needed
                    if hasattr(raw_output, "content"):
                        output = raw_output.content
                    else:
                        output = str(raw_output)
                # Check for error
                if call.error is not None:
                    error = str(call.error)[:500]
            except Exception as e:
                logger.warning("Tool %s raised: %s", tool_name, e)
                error = str(e)[:500]

            # Tool end - emit event for frontend to show "completed" state
            await out_queue.put(
                sse(
                    {
                        "type": "tool_result",
                        "content": {
                            "id": tool_id,
                            "name": tool_name,
                            "output": str(output)[:500] if output else None,
                            "error": error,
                        },
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
