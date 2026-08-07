import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.infra.config import get_settings
from app.utils.logging import JsonFormatter, RequestIdFilter
from app.infra.llm.manager import get_model_manager
from app.infra.llm.system_llm import init_system_llm
from app.infra.llm.embedding import (
    initialize_embedding_runtime,
    probe_embedding_runtime,
)
from app.api.errors import register_exception_handlers
from app.infra.database import (
    init_database_connection,
    init_database_components,
    dispose_database,
)
from app.api.v1 import api_router


settings = get_settings()


def _configure_logging() -> None:
    """Configure application-wide logging.

    This is called at module import time to ensure logging is configured
    regardless of how the application is started (direct run or uvicorn --reload).
    """
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    # Remove any pre-existing handlers (basicConfig adds a StreamHandler)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.LOG_LEVEL)

    # Register RequestIdFilter on the handler so %(request_id)s works
    # in format strings. Filters must be on handlers, not loggers,
    # because child-logger records propagate to parent handlers but
    # NOT through parent logger filters.
    handler.addFilter(RequestIdFilter())

    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
        )

    root.addHandler(handler)

    # Set app logger level
    logging.getLogger("app").setLevel(settings.LOG_LEVEL)

    # Suppress noisy third-party libraries
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)


# Configure logging at module import time
_configure_logging()

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
    try:
        # ── Startup ──────────────────────────────────────────────────────
        # System LLM is environment-owned and has no database dependency.
        init_system_llm()
        logger.info("System LLM initialized")

        # Canonical order: DB -> ModelManager -> EmbeddingClient -> consumers.
        await init_database_connection()
        logger.info("Database connection initialized")
        await get_model_manager().refresh()
        logger.info("Model manager initialized")

        embedding_config = initialize_embedding_runtime()
        if embedding_config is not None:
            embedding_probe = await probe_embedding_runtime(
                embedding_config,
                timeout_seconds=1.5,
            )
            if embedding_probe.probe_ok:
                logger.info(
                    "Embedding runtime probe succeeded: model=%s dimensions=%d "
                    "elapsed_ms=%.1f",
                    embedding_config.model,
                    embedding_probe.embedding_dimensions,
                    embedding_probe.elapsed_ms,
                )
            else:
                logger.warning(
                    "Embedding runtime probe failed open: model=%s category=%s "
                    "message=%s elapsed_ms=%.1f",
                    embedding_config.model,
                    embedding_probe.error_category,
                    embedding_probe.message,
                    embedding_probe.elapsed_ms,
                )

        await init_database_components()
        logger.info("All database components initialized successfully")

        from app.services.routing import schedule_routing_semantic_warmup

        schedule_routing_semantic_warmup()
        logger.info("Routing semantic index warmup scheduled")

        # WeChat listener is now per-login, started in WebSocket endpoint
    except Exception as e:
        logger.critical("Application startup failed, exiting: %s", e)
        sys.exit(1)

    try:
        yield
    finally:
        # ── Shutdown ──────────────────────────────────────────────────
        # WeChat listeners are stopped individually when WebSocket disconnects
        await dispose_database()
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
