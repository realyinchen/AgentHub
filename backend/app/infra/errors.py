"""Domain-specific error hierarchy for AgentHub.

These exceptions enable the API layer to map error causes to appropriate
HTTP status codes and user-facing messages, rather than returning a
generic 500 for every failure.

Usage::

    from app.infra.errors import AgentTimeoutError, ToolError

    try:
        ...
    except asyncio.TimeoutError:
        raise AgentTimeoutError(timeout_seconds=120, context="agent.ainvoke")
    except SomeToolError:
        raise ToolError(tool_name="search", original_error=e)
"""

from typing import Any


# =============================================================================
# Base Error
# =============================================================================


class AgentHubError(Exception):
    """Base exception for all AgentHub domain errors.

    All custom exceptions MUST inherit from this class so the API-level
    exception handler can catch them with a single ``except AgentHubError``
    clause.
    """

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.detail = detail or {}


# =============================================================================
# Timeout Errors
# =============================================================================


class AgentTimeoutError(AgentHubError):
    """Raised when an agent operation exceeds its configured time limit.

    Attributes:
        timeout_seconds: The timeout value that was exceeded.
        context: What was being executed (e.g. "agent.ainvoke", "stream").
    """

    def __init__(
        self,
        timeout_seconds: float,
        *,
        context: str = "agent",
        detail: dict[str, Any] | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.context = context
        super().__init__(
            f"Agent operation timed out after {timeout_seconds:.0f}s (context: {context})",
            detail=detail,
        )


# =============================================================================
# LLM Errors
# =============================================================================


class LLMError(AgentHubError):
    """Raised when an LLM provider call fails.

    This covers provider-side errors (rate limits, authentication failures,
    model overloaded, etc.) as well as client-side network errors during
    LLM invocation.
    """

    def __init__(
        self,
        message: str,
        *,
        model_name: str = "",
        provider: str = "",
        detail: dict[str, Any] | None = None,
    ):
        self.model_name = model_name
        self.provider = provider
        super().__init__(message, detail=detail)


# =============================================================================
# Tool Errors
# =============================================================================


class ToolError(AgentHubError):
    """Raised when a tool call fails (network error, timeout, invalid input).

    Tool errors SHOULD NOT crash the entire agent invocation — the agent
    can decide to retry or degrade gracefully. This exception is primarily
    for observability and structured error reporting.
    """

    def __init__(
        self,
        tool_name: str,
        *,
        original_error: Exception | None = None,
        detail: dict[str, Any] | None = None,
    ):
        self.tool_name = tool_name
        self.original_error = original_error
        msg = f"Tool '{tool_name}' failed"
        if original_error:
            msg += f": {original_error}"
        super().__init__(msg, detail=detail)


# =============================================================================
# Agent Errors (generic agent-level failures)
# =============================================================================


class AgentError(AgentHubError):
    """Raised for agent-level failures not covered by more specific types.

    Examples: agent compilation errors, invalid state transitions,
    checkpoint loading failures, etc.
    """

    def __init__(
        self,
        message: str,
        *,
        agent_name: str = "",
        detail: dict[str, Any] | None = None,
    ):
        self.agent_name = agent_name
        super().__init__(message, detail=detail)


# =============================================================================
# Database Errors
# =============================================================================


class DatabaseError(AgentHubError):
    """Raised for database connection or operation failures.

    Covers SQLAlchemy engine/session errors, connection pool exhaustion,
    and general relational database issues.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str = "",
        detail: dict[str, Any] | None = None,
    ):
        self.operation = operation
        super().__init__(message, detail=detail)


class VectorStoreError(AgentHubError):
    """Raised for vector store operation failures.

    Covers embedding generation failures, vector search errors,
    and document indexing issues in PGVector.
    """

    def __init__(
        self,
        message: str,
        *,
        collection_name: str = "",
        operation: str = "",
        detail: dict[str, Any] | None = None,
    ):
        self.collection_name = collection_name
        self.operation = operation
        super().__init__(message, detail=detail)


class CheckpointerError(AgentHubError):
    """Raised for LangGraph checkpointer operation failures.

    Covers checkpoint save/load errors, thread state persistence issues,
    and AsyncPostgresSaver connection failures.
    """

    def __init__(
        self,
        message: str,
        *,
        thread_id: str = "",
        operation: str = "",
        detail: dict[str, Any] | None = None,
    ):
        self.thread_id = thread_id
        self.operation = operation
        super().__init__(message, detail=detail)


class StoreError(AgentHubError):
    """Raised for LangGraph Store (long-term memory) operation failures.

    Covers cross-session memory persistence errors, vector index issues,
    and AsyncPostgresStore connection failures.
    """

    def __init__(
        self,
        message: str,
        *,
        namespace: tuple[str, ...] | None = None,
        key: str = "",
        operation: str = "",
        detail: dict[str, Any] | None = None,
    ):
        self.namespace = namespace
        self.key = key
        self.operation = operation
        super().__init__(message, detail=detail)
