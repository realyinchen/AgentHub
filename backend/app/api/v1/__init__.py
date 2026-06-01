"""V1 API router — aggregates all /chat, /models, and /traces resource routers."""

from fastapi import APIRouter

from app.api.v1.chat import api_router as chat_router
from app.api.v1.models import api_router as models_router
from app.api.v1.traces import api_router as traces_router

api_router = APIRouter()

api_router.include_router(chat_router)
api_router.include_router(models_router)
api_router.include_router(traces_router)
