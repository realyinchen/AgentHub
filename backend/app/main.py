import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.utils.agent_utils import get_available_agents
from app.core.config import settings
from app.core.model_manager import ModelManager
from app.core.rate_limiter import limiter
from app.database import init_all, dispose_all, get_saver
from app.api.v1.router import api_router


logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate idiomatic operation IDs for OpenAPI client generation."""
    return route.name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan: initialize all database components on startup,
    dispose them on shutdown.
    """
    try:
        # Initialize all database components (database + vectorstore + checkpointer)
        await init_all()
        logger.info("All database components initialized successfully")

        # Initialize model manager (preload model configurations)
        await ModelManager.refresh()

        # Get the checkpointer saver for agent configuration
        saver = get_saver()

        # Configure agents with checkpointer for thread-scoped memory
        available_agents = await get_available_agents()
        for agent in available_agents:
            agent.checkpointer = saver

        yield

        # Cleanup all database components
        await dispose_all()
        logger.info("All database components disposed successfully")
    except Exception as e:
        logger.error(f"Error during database initialization: {e}")
        raise


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint for Docker healthcheck."""
    return {"status": "ok"}


# Add rate limiter to app
app.state.limiter = limiter

app.include_router(api_router, prefix=settings.API_V1_STR)
