import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.agents.registry import reload_agents, get_ids
from app.infra.config import get_settings
from app.infra.llm.model_manager import get_model_manager
from app.api.errors import register_exception_handlers
from app.infra.database import init_all, dispose_all
from app.api.v1.router import api_router


settings = get_settings()
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
        await get_model_manager().refresh()

        # Load active agents from DB, compile, store in memory.
        # reload_agents() now reads checkpointer and store from the database
        # factory and passes them directly to each agent factory — no more
        # monkey-patching graph.checkpointer / graph.store after the fact.
        await reload_agents()
        logger.info("Agent registry initialized: %d agents active", len(get_ids()))

        yield

        # Cleanup all database components
        await dispose_all()
        logger.info("All database components disposed successfully")
    except Exception as e:
        logger.error(f"Error during database initialization: {e}")
        raise


app = FastAPI(
    lifespan=lifespan,
    generate_unique_id_function=custom_generate_unique_id,
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
)

# Register exception handlers for centralized error handling
register_exception_handlers(app)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint for Docker healthcheck."""
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.API_V1_STR)
