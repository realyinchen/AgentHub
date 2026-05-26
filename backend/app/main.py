import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from sqlalchemy import text

from app.agents.registry import reload_agents, get_ids
from app.infra.config import get_settings
from app.infra.llm.model_manager import get_model_manager
from app.api.errors import register_exception_handlers
from app.infra.database import init_all, dispose_all, get_database
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

    Startup failures propagate immediately (fail-fast).  Shutdown cleanup
    runs in ``finally`` so it always executes, even when startup raises.
    """
    # ── Startup ──────────────────────────────────────────────────────
    # Initialize all infrastructure components sequentially:
    # database → vectorstore → checkpointer → store.
    # Database is initialized first so checkpointer (which may depend
    # on the DB connection pool) can safely follow.
    await init_all()
    logger.info("All database components initialized successfully")

    # Preload model configurations from DB and build the LiteLLM Router.
    # refresh() ends by pre-building the Router so get_router_sync() works
    # immediately for synchronous callers (e.g. @wrap_model_call middleware).
    await get_model_manager().refresh()
    logger.info("Model manager initialized")

    # Load active agents from DB, compile them with checkpointer + store,
    # atomically replace the registry snapshot.  On subsequent requests,
    # get_graph() is a zero-overhead dict lookup on the frozen snapshot.
    await reload_agents()
    logger.info("Agent registry initialized: %d agents active", len(get_ids()))

    try:
        yield
    finally:
        # ── Shutdown ──────────────────────────────────────────────────
        # Always run cleanup, even if the app crashes during startup.
        await dispose_all()
        logger.info("All database components disposed successfully")


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
    """Health check endpoint for Docker healthcheck / K8s liveness probe.

    Verifies basic database connectivity with a lightweight ``SELECT 1``
    query. Returns 503 if the database is unreachable, otherwise 200.
    """
    try:
        db = get_database()
        async with db.session_readonly() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="database_unhealthy")


app.include_router(api_router, prefix=settings.API_V1_STR)
