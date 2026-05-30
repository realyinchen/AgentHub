"""Chat resource group — /chat endpoints.

Aggregates sub-routers for:
    run.py           — POST /chat/invoke + /chat/stream
    conversations.py — /chat/conversations CRUD + title + thinking-mode
    history.py       — GET /chat/history/{thread_id}
    stats.py         — GET /chat/conversations/{id}/stats + /requests/{rid}/stats
"""

from fastapi import APIRouter

from app.api.v1.chat.run import api_router as run_router
from app.api.v1.chat.conversations import api_router as conversations_router
from app.api.v1.chat.history import api_router as history_router
from app.api.v1.chat.stats import api_router as stats_router

api_router = APIRouter(prefix="/chat", tags=["Chat"])

api_router.include_router(run_router)
api_router.include_router(conversations_router)
api_router.include_router(history_router)
api_router.include_router(stats_router)