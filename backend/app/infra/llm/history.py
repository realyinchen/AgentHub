"""Pure projection of stored LangChain messages into model-safe history."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage


_REASONING_HISTORY_KEYS = frozenset(
    {
        "reasoning_content",
        "reasoning_details",
        "thinking",
    }
)


class ModelHistoryProjector:
    """Remove provider-only reasoning data from assistant history copies.

    The original messages remain authoritative for persistence and display.
    Only the transient sequence sent back to a model is projected.
    """

    def project(
        self,
        messages: Sequence[BaseMessage],
    ) -> tuple[BaseMessage, ...]:
        return tuple(self.project_message(message) for message in messages)

    def project_message(self, message: BaseMessage) -> BaseMessage:
        if not isinstance(message, AIMessage):
            return message

        additional_kwargs = {
            key: value
            for key, value in message.additional_kwargs.items()
            if key not in _REASONING_HISTORY_KEYS
        }
        if (
            isinstance(message.content, str)
            and additional_kwargs == message.additional_kwargs
        ):
            return message

        return message.model_copy(
            update={
                "content": _assistant_visible_text(message.content),
                "additional_kwargs": additional_kwargs,
            }
        )


def _assistant_visible_text(content: str | list[str | dict]) -> str:
    if isinstance(content, str):
        return content
    visible: list[str] = []
    for block in content:
        if isinstance(block, str):
            visible.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                visible.append(text)
    return "".join(visible)


model_history_projector = ModelHistoryProjector()


__all__ = ["ModelHistoryProjector", "model_history_projector"]
