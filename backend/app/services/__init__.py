"""Services layer — business logic orchestration.

This layer handles:
- Chat orchestration (invoke/stream)
- SSE streaming service

Services are the glue between API layer (routing) and Agent layer (LangGraph).

Notes:
- build_agent_kwargs moved to utils/request.py (pure utility, no business logic).
- persist_agent_trace moved to crud/trace.py (pure CRUD, no orchestration logic).
"""

from app.services.chat import ChatService
from app.services.streaming import ChatStreamingService

__all__ = [
    "ChatService",
    "ChatStreamingService",
]
