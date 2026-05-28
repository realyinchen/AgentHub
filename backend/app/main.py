import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.agents import build_supervisor
from app.infra.config import get_settings
from app.infra.llm.model_manager import get_model_manager
from app.api.errors import register_exception_handlers
from app.infra.database import init_all, dispose_all, get_checkpointer, get_store
from app.api.v1.router import api_router
from app.utils.logging import RequestIdFilter


settings = get_settings()

# ── Logging Configuration ──────────────────────────────────────────────
# Register RequestIdFilter on root logger so every log record automatically
# carries the request_id from the current contextvar.
logging.getLogger().addFilter(RequestIdFilter())

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

    store = get_store()
    await build_supervisor(
        checkpointer=get_checkpointer().get_saver(),
        store=store.get_store() if store else None,
    )

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
async def health_check() -> str:
    return "ok"


app.include_router(api_router, prefix=settings.API_V1_STR)
