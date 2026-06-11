"""Model resolution utilities.

Handles default → first-active fallback chain for model selection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _get_model_manager():
    """Lazy import to avoid circular imports."""
    from app.infra.llm.manager import get_model_manager

    return get_model_manager()


def resolve_model_name(user_model: str | None) -> str | None:
    """Resolve a model name with default → first-active fallback chain.

    Args:
        user_model: Explicitly requested model name (may be *None* if the
            user hasn't selected a specific model from the frontend).

    Returns:
        The resolved model name, or *None* when **no** models are active
        in the system (caller should decide whether that is a hard error).
    """
    if user_model:
        return user_model
    manager = _get_model_manager()
    return manager.default_llm_id or manager.get_first_active_llm_id()


async def refresh_model_cache_if_missing(model_name: str | None) -> None:
    """Refresh the DB-backed model cache once when an explicit model is missing.

    Model configuration can be edited while the backend is already running. The
    chat path uses ModelManager's in-memory cache, so a model inserted outside
    the model CRUD endpoints can otherwise be visible in `/models` while still
    failing in runtime model selection.
    """
    if not model_name:
        return

    manager = _get_model_manager()
    if manager.get_model(model_name):
        return
    if "/" in model_name and manager.get_model(model_name.split("/", 1)[1]):
        return

    await manager.refresh()
