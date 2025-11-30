import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.agents import rag_agent
from app.core.config import settings
from app.database import (
    initialize_database,
    initialize_qdrant_client,
    close_qdrant_client,
)
from app.api.routes import api_router


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
        # Initialize vectorstore client
        initialize_qdrant_client()
        # Initialize checkpointer (for short-term memory)
        async with initialize_database() as saver:
            if hasattr(saver, "setup"):
                await saver.setup()

            logger.info("✅ PostgreSQL checkpointer pool ready")
            # Set checkpointer for thread-scoped memory (conversation history)
            rag_agent.checkpointer = saver
            yield
            close_qdrant_client()
    except Exception as e:
        logger.error(f"Error during database and vectorstore initialization: {e}")
        raise


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)
app.include_router(api_router, prefix=settings.API_V1_STR)
