from langchain_core.messages import BaseMessage
from langchain_core.messages import content as types
from typing import Any, Literal, cast, overload


class InterruptMessage(BaseMessage):
    """Message in a interrupt of Human In The Loop."""

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
