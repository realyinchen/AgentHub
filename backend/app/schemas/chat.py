from langchain.messages import ToolCall
from pydantic import BaseModel, Field
from typing import Any, Literal
from uuid import UUID
from datetime import datetime, timezone


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
    messages: list[ChatMessage]


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
        examples=["chatbot", "agentic_rag"],
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
