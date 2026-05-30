import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.agents import init_supervisor
from app.infra.config import get_settings
from app.infra.llm.model_manager import get_model_manager
from app.api.errors import register_exception_handlers
from app.infra.database import init_all, dispose_all, get_checkpointer, get_store
from app.api.v1 import api_router


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

    store = get_store()
    await init_supervisor(
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

# Configure CORS middleware
# Allow all methods and headers for development. Credentials are not allowed
# when origins include "*" so we use the configured CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register exception handlers for centralized error handling
register_exception_handlers(app)


@app.get("/health", tags=["Health"])
async def health_check() -> str:
    return "ok"


app.include_router(api_router, prefix=settings.API_V1_STR)
