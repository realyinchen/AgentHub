import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.utils.agent_utils import get_available_agents
from app.core.config import settings
from app.database import (
    adb_manager,
    db_manager,
    get_checkpointer,
    qdrant_manager,
)
from app.api.v1.router import api_router


logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate idiomatic operation IDs for OpenAPI client generation."""
    return route.name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Configurable lifespan that initializes the appropriate database checkpointer and vectorstore
    """
    try:
        await adb_manager.initialize()
        db_manager.initialize()
        qdrant_manager.initialize()
        # Initialize checkpointer (for short-term memory)
        async with get_checkpointer() as checkpointer:
            if hasattr(checkpointer, "setup"):
                await checkpointer.setup()
            # Configure agents with both memory components and async loading
            available_agents = await get_available_agents()
            for agent in available_agents:
                # Set checkpointer for thread-scoped memory (conversation history)
                agent.checkpointer = checkpointer
            yield
            qdrant_manager.dispose()
            db_manager.dispose()
            await adb_manager.dispose()
    except Exception as e:
        logger.error(f"Error during database and vectorstore initialization: {e}")
        raise


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)
app.include_router(api_router, prefix=settings.API_V1_STR)
