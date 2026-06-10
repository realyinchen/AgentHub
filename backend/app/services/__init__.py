"""Services layer - business logic orchestration.

This package exposes service classes used by API routes while keeping imports
lazy. Eagerly importing every service here creates circular imports when agent
tools import a single submodule such as ``app.services.book_search``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ChatService",
    "ChatStreamingService",
    "WeixinListener",
    "create_listener",
    "stop_listener",
    "get_listener",
]


def __getattr__(name: str) -> Any:
    """Lazily expose service symbols without package-wide side effects."""
    if name == "ChatService":
        from app.services.chat import ChatService

        return ChatService
    if name == "ChatStreamingService":
        from app.services.streaming import ChatStreamingService

        return ChatStreamingService
    if name in {"WeixinListener", "create_listener", "stop_listener", "get_listener"}:
        from app.services import weixin_listener

        return getattr(weixin_listener, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
