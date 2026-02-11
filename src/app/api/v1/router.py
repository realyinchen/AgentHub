from fastapi import APIRouter
from app.api.v1 import agent, chat


api_router = APIRouter()


api_router.include_router(agent.api_router)
api_router.include_router(chat.api_router)
