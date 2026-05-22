from fastapi import APIRouter

from app.api.v1 import (
    agent,
    chat,
    chat_session,
    chat_title,
    model,
    provider,
    trace,
)


api_router = APIRouter()


api_router.include_router(agent.api_router)
api_router.include_router(chat.api_router)
api_router.include_router(chat_title.api_router)
api_router.include_router(chat_session.api_router)
api_router.include_router(model.api_router)
api_router.include_router(provider.api_router)
api_router.include_router(trace.api_router)
