"""Chat request/response schemas.

This module hosts the Pydantic schemas exposed by the ``/chat/*`` endpoints
(stream, invoke, history, title, conversations, stats). It is intentionally
the single source of truth for the **chat request DTO** (``UserInput``) used
by both the stream and invoke endpoints.

Trace / observability schemas live in ``app.schemas.trace``.
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal, cast, overload
from uuid import UUID
from datetime import datetime, timezone

from langchain_core.messages import BaseMessage
from langchain_core.messages import content as types

from app.schemas.trace import StepOutput


class ToolCall(BaseModel):
    """Tool call information."""

    name: str = Field(description="Tool name")
    args: dict[str, Any] = Field(default={}, description="Tool arguments")
    id: str | None = Field(default=None, description="Tool call ID")


class UserInput(BaseModel):
    """Basic user input for the agent."""

    content: str = Field(
        description="User input to the agent.",
        examples=["What is the weather in Hefei?"],
    )
    user_id: str = Field(
        description="User ID for long-term memory and personalization.",
        examples=["user-123"],
    )
    thread_id: UUID = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )
    request_id: str = Field(
        description="Request ID for end-to-end tracing and idempotency.",
        examples=["req-abc-123"],
    )
    model_name: str | None = Field(
        description="The model name to use for this request. If not provided, uses the default model.",
        default=None,
        examples=["qwen3.5-27b", "glm-4"],
    )
    thinking_mode: bool = Field(
        description="Whether to enable thinking mode for models that support it (e.g., DeepSeek-R1, Qwen3).",
        default=False,
        examples=[True, False],
    )
    timezone: str = Field(
        description="IANA timezone for time-context substitution in prompts (e.g. Asia/Shanghai, America/New_York).",
        default="Asia/Shanghai",
        examples=["Asia/Shanghai", "America/New_York", "Europe/London"],
    )
    custom_data: dict[str, Any] | None = Field(
        description="Custom data to persist with the message (e.g., quoted_message_id, user_content for quote feature).",
        default=None,
        examples=[{"quoted_message_id": "msg-123", "user_content": "My question"}],
    )


class ChatMessage(BaseModel):
    """Message in a chat."""

    type: Literal["human", "ai", "tool", "custom"] = Field(
        description="Role of the message.",
        examples=["human", "ai", "tool", "custom"],
    )
    content: str = Field(
        description="Content of the message.",
        examples=["Hello, world!"],
    )
    tool_calls: list[ToolCall] = Field(
        description="Tool calls in the message.",
        default=[],
    )
    tool_call_id: str | None = Field(
        description="Tool call that this message is responding to.",
        default=None,
        examples=["call_Jja7J89XsjrOLA5r!MEOW!SL"],
    )
    name: str | None = Field(
        description="Name of the tool (for tool messages).",
        default=None,
        examples=["web_search"],
    )
    run_id: str | None = Field(
        description="Run ID of the message.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    response_metadata: dict[str, Any] = Field(
        description="Response metadata. For example: response headers, logprobs, token counts.",
        default={},
    )
    custom_data: dict[str, Any] = Field(
        description="Custom message data.",
        default={},
    )

    def pretty_repr(self) -> str:
        """Get a human-readable representation for debug logging."""
        base_title = self.type.title() + " Message"
        padded = " " + base_title + " "
        sep_len = (80 - len(padded)) // 2
        sep = "=" * sep_len
        second_sep = sep + "=" if len(padded) % 2 else sep
        title = f"{sep}{padded}{second_sep}"
        return f"{title}\n\n{self.content}"


class ChatHistory(BaseModel):
    """Chat history with messages and execution sequence."""

    messages: list[ChatMessage] = Field(
        description="Messages for main chat UI (human and final AI messages)",
    )
    message_sequence: list[StepOutput] = Field(
        description="Complete message sequence for sidebar (tool calls and AI response)",
        default=[],
    )


class ConversationCreate(BaseModel):
    """Schema for creating a conversation.

    user_id comes from query parameter, not request body.
    """

    thread_id: UUID = Field(
        description="The thread ID of the conversation.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )
    title: str = Field(
        description="The title of the conversation",
        examples=["Hello"],
        min_length=1,
        max_length=64,
    )


class Conversation(BaseModel):
    """Full conversation schema for responses."""

    thread_id: UUID = Field(
        description="The thread ID of the conversation.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )
    user_id: str = Field(
        description="The user ID who owns this conversation.",
        examples=["user-123"],
    )
    title: str = Field(
        description="The title of the conversation",
        examples=["Hello"],
        min_length=1,
        max_length=64,
    )


class ConversationUpdate(BaseModel):
    """Schema for updating a conversation. All fields are optional for partial updates."""

    title: str | None = Field(
        default=None,
        description="The title of the conversation",
        examples=["Hello"],
        min_length=1,
        max_length=64,
    )
    is_deleted: bool | None = Field(
        default=None,
        description="Whether the conversation has been deleted.",
        examples=[True],
    )


class ConversationInDB(Conversation):
    created_at: datetime = Field(
        description="The create time of the conversation",
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        description="The update time of the conversation",
        default_factory=lambda: datetime.now(timezone.utc),
    )
    is_deleted: bool | None = Field(
        description="Whether the conversation has been deleted.",
        default=False,
        examples=[True],
    )
    # Token usage fields (cumulative for the conversation)
    input_tokens: int = Field(
        description="Cumulative input tokens used in this conversation",
        default=0,
    )
    output_tokens: int = Field(
        description="Cumulative output tokens used in this conversation",
        default=0,
    )
    total_tokens: int = Field(
        description="Cumulative total tokens used in this conversation",
        default=0,
    )

    model_config = ConfigDict(from_attributes=True)


# ── Conversation info ───────────────────────────────────────────────────────


class ConversationInfoResponse(BaseModel):
    """Response for GET /chat/conversation-info/{thread_id}."""

    model_name: str | None = Field(
        default=None, description="Model name from last trace execution"
    )
    model_fallback: bool = Field(
        default=False,
        description="True when the trace model was inactive and fell back to default",
    )


# ── Daily stats ─────────────────────────────────────────────────────────────


class DailyStatsItem(BaseModel):
    """A single day's conversation + token statistics."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    conversation_count: int = Field(description="Number of conversations that day")
    input_tokens: int = Field(default=0, description="Input tokens consumed")
    output_tokens: int = Field(default=0, description="Output tokens consumed")
    total_tokens: int = Field(default=0, description="Total tokens consumed")


# ── Title schemas ───────────────────────────────────────────────────────────


class TitleGenerateRequest(BaseModel):
    """Request for generating a conversation title."""

    user_message: str = Field(
        description="The user's message to generate title from",
        examples=["What is the weather in Beijing?"],
    )
    ai_response: str | None = Field(
        default=None,
        description="The AI's response (optional, for better context)",
        examples=["The weather in Beijing is sunny, 25°C."],
    )


class TitleGenerateResponse(BaseModel):
    """Response for title generation."""

    title: str = Field(
        description="The generated title",
        examples=["Beijing Weather Inquiry"],
    )


# ── Human-in-the-Loop Interrupt Message ───────────────────────────────────────


class InterruptMessage(BaseMessage):
    """Message in an interrupt of Human In The Loop."""

    action_requests: list[dict] = []
    """
    The list of tool actions the Agent intends to execute but that have been paused for human review.
    """

    review_configs: list[dict] = []
    """
    The configuration that defines which decision types (approve, edit, reject) are allowed for each corresponding action request.
    """

    type: Literal["interrupt"] = "interrupt"
    """The type of the message (used for deserialization)."""

    @overload
    def __init__(
        self,
        content: str | list[str | dict],
        **kwargs: Any,
    ) -> None: ...

    @overload
    def __init__(
        self,
        content: str | list[str | dict] | None = None,
        content_blocks: list[types.ContentBlock] | None = None,
        **kwargs: Any,
    ) -> None: ...

    def __init__(
        self,
        content: str | list[str | dict] | None = None,
        content_blocks: list[types.ContentBlock] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize an `InterruptMessage`.

        Specify `content` as positional arg or `content_blocks` for typing.

        Args:
            content: The content of the message.
            content_blocks: Typed standard content.
            **kwargs: Additional arguments to pass to the parent class.
        """
        if content_blocks is not None:
            super().__init__(
                content=cast("str | list[str | dict]", content_blocks),
                **kwargs,
            )
        else:
            super().__init__(content=content, **kwargs)
