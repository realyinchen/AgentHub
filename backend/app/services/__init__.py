"""Services layer — business logic orchestration.

This layer handles:
- Chat orchestration (invoke/stream)
- SSE streaming service
- WeChat listener (per-login message loop)

Services are the glue between API layer (routing) and Agent layer (LangGraph).

Notes:
- build_agent_kwargs moved to utils/request.py (pure utility, no business logic).
- persist_agent_trace moved to crud/trace.py (pure CRUD, no orchestration logic).
"""

from app.services.chat import ChatService
from app.services.streaming import ChatStreamingService
from app.services.weixin_listener import (
    WeixinListener,
    create_listener,
    stop_listener,
    get_listener,
)

__all__ = [
    "ChatService",
    "ChatStreamingService",
    "WeixinListener",
    "create_listener",
    "stop_listener",
    "get_listener",
]
