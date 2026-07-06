"""Per-turn context shared with agent tools.

The agent may transform a user request into tool arguments, but tools still need
access to the original user message for admission checks. Keep that turn-level
data in contextvars so async tool calls inherit it without changing every tool
signature.
"""

from __future__ import annotations

import contextvars
from typing import Any

_current_user_message_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_user_message", default=""
)


class CurrentUserMessageContext:
    @staticmethod
    def set(message: str) -> contextvars.Token:
        return _current_user_message_ctx.set(message)

    @staticmethod
    def get() -> str:
        return _current_user_message_ctx.get()

    @staticmethod
    def reset(token: contextvars.Token) -> None:
        _current_user_message_ctx.reset(token)


current_user_message_context = CurrentUserMessageContext()


def get_current_user_message() -> str:
    return current_user_message_context.get()


class user_message_scope:
    """Context manager for tests and direct tool verification scripts."""

    def __init__(self, message: str) -> None:
        self._message = message
        self._token: contextvars.Token | None = None

    def __enter__(self) -> "user_message_scope":
        self._token = current_user_message_context.set(self._message)
        return self

    def __exit__(self, *args: Any) -> None:
        if self._token is not None:
            current_user_message_context.reset(self._token)
        return None
