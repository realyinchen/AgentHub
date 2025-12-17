from langchain.messages import ToolCall
from pydantic import BaseModel, Field
from typing import Any, Literal


class ChatMessage(BaseModel):
    """Message in a chat."""

    type: Literal["human", "ai", "tool", "interrupt"] = Field(
        description="Role of the message.",
        examples=["human", "ai", "tool", "interrupt"],
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
    response_metadata: dict[str, Any] = Field(
        description="Response metadata. For example: response headers, logprobs, token counts.",
        default={},
    )
    action_requests: list[dict] = Field(
        description="The list of tool actions the Agent intends to execute but that have been paused for human review.",
        default=[],
    )
    review_configs: list[dict] = Field(
        description="The configuration that defines which decision types (approve, edit, reject) are allowed for each corresponding action request.",
        default=[],
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


class ChatHistoryInput(BaseModel):
    """Input for retrieving chat history."""

    thread_id: str = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )


class ChatHistory(BaseModel):
    messages: list[ChatMessage]
