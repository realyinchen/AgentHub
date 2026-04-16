from pydantic import BaseModel, Field
from typing import Any, Literal
from uuid import UUID
from datetime import datetime, timezone


class ToolCall(BaseModel):
    """Tool call information."""
    name: str = Field(description="Tool name")
    args: dict[str, Any] = Field(default={}, description="Tool arguments")
    id: str | None = Field(default=None, description="Tool call ID")


class MessageStep(BaseModel):
    """Single step in the agent execution sequence for sidebar display.
    
    Each step represents a message in the conversation flow.
    Steps are numbered sequentially (Step 1, Step 2, etc.)
    
    Types:
    - human: User message with content
    - ai: AI message with thinking, content, and optional tool_calls
    - tool: Tool execution with name, args, and output
    """
    step_number: int = Field(
        description="Step number (1-indexed)",
        examples=[1, 2, 3],
    )
    message_type: Literal["human", "ai", "tool"] = Field(
        description="Type of the step: human, ai, or tool",
        examples=["human", "ai", "tool"],
    )
    # Content field (for human and ai types)
    content: str | None = Field(
        description="Message content (for human and ai types)",
        default=None,
        examples=["What's the weather in Beijing?"],
    )
    # AI message fields
    thinking: str | None = Field(
        description="Thinking/reasoning content (for ai type)",
        default=None,
        examples=["用户想了解北京天气..."],
    )
    tool_calls: list[ToolCall] | None = Field(
        description="Tool calls from AI message (for ai type with tool calls)",
        default=None,
    )
    # Tool fields (for tool type)
    tool_name: str | None = Field(
        description="Tool name (for tool type)",
        default=None,
        examples=["get_weather", "search_web"],
    )
    tool_args: dict[str, Any] | None = Field(
        description="Tool call arguments (for tool type)",
        default=None,
        examples=[{"city": "Beijing"}],
    )
    tool_output: str | None = Field(
        description="Tool execution result (for tool type)",
        default=None,
        examples=["晴天, 25°C"],
    )
    tool_call_id: str | None = Field(
        description="Tool call ID for matching (for tool type)",
        default=None,
    )


class UserInput(BaseModel):
    """Basic user input for the agent."""

    content: str = Field(
        description="User input to the agent.",
        examples=["What is the weather in Hefei?"],
    )
    agent_id: str | None = Field(
        description="The agent the user wants to use.",
        default=None,
        examples=["chatbot"],
    )
    thread_id: UUID | None = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        default=None,
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
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
        """Get a pretty representation of the message."""
        base_title = self.type.title() + " Message"
        padded = " " + base_title + " "
        sep_len = (80 - len(padded)) // 2
        sep = "=" * sep_len
        second_sep = sep + "=" if len(padded) % 2 else sep
        title = f"{sep}{padded}{second_sep}"
        return f"{title}\n\n{self.content}"

    def pretty_print(self) -> None:
        print(self.pretty_repr())  # noqa: T201


class ChatHistory(BaseModel):
    """Chat history with messages and execution sequence."""
    
    messages: list[ChatMessage] = Field(
        description="Messages for main chat UI (human and final AI messages)",
    )
    message_sequence: list[MessageStep] = Field(
        description="Complete message sequence for sidebar (tool calls and AI response)",
        default=[],
    )


class Conversation(BaseModel):
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
    agent_id: str | None = Field(
        description="The agent ID used in this conversation.",
        default="chatbot",
        examples=["chatbot", "navigator"],
    )


class ConversationCreate(Conversation):
    created_at: datetime = Field(
        description="The create time of the conversation",
        default=datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        description="The update time of the conversation",
        default=datetime.now(timezone.utc),
    )
    is_deleted: bool | None = Field(
        description="Whether the conversation is been deleted.",
        default=False,
        examples=[True],
    )


class ConversationUpdate(Conversation):
    updated_at: datetime = Field(
        description="The update time of the conversation",
        default=datetime.now(timezone.utc),
    )
    is_deleted: bool | None = Field(
        description="Whether the conversation is been deleted.",
        default=False,
        examples=[True],
    )


class ConversationInDB(Conversation):
    created_at: datetime = Field(
        description="The create time of the conversation",
        default=datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        description="The update time of the conversation",
        default=datetime.now(timezone.utc),
    )
    is_deleted: bool | None = Field(
        description="Whether the conversation is been deleted.",
        default=False,
        examples=[True],
    )

    class Config:
        from_attributes = True