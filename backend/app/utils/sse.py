"""SSE Streaming Utilities — helper functions and types.

This module contains pure utilities with no business logic:
- SSE formatting helpers (sse, sse_error)
- AsyncWriteQueue for non-blocking writes
- StreamState TypedDict for shared state
- StreamV3Projection Protocol for LangGraph v3

Business logic (ChatStreamingService) moved to services/streaming.py.
"""

import asyncio
import json as _json
import logging
from collections.abc import AsyncIterator, Awaitable
from typing import Protocol, TypedDict

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


# ── SSE formatting helpers ────────────────────────────────────────────────────


def sse(data: object) -> str:
    """Format data as a Server-Sent Event message."""
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"


def sse_error(content: str, error_type: str = "error") -> str:
    """Format an error as a Server-Sent Event message."""
    return sse({"type": "error", "content": content, "error_type": error_type})


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
    accumulated_reasoning: str  # Current accumulated reasoning (resets per LLM call)
    last_reasoning: str  # Most recent AI reasoning for the final message event
    reasoning_segments: dict[str, str]  # reasoning content keyed by message_id
    ai_reasoning_index: int  # AI message order used as a stable DAG fallback key
    final_message: BaseMessage | None
    final_state_messages: list[BaseMessage] | None


# ── AsyncWriteQueue ───────────────────────────────────────────────────────────


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
                            backoff = 0.1 * (2**attempt)
                            logger.warning(
                                "[AsyncWriteQueue] Retry [%s] %d/%d: %s",
                                name,
                                attempt + 1,
                                max_retries,
                                exc,
                            )
                            await asyncio.sleep(backoff)
                        else:
                            logger.error(
                                "[AsyncWriteQueue] Failed [%s] (exhausted): %s",
                                name,
                                exc,
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

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> bool:
        await self.wait_all()
        return False


__all__ = [
    "AsyncWriteQueue",
    "StreamState",
    "StreamV3Projection",
    "sse",
    "sse_error",
]
