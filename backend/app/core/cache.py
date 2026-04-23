"""
In-Memory caching utilities for AgentHub.

Provides TTL-based caching without external dependencies like Redis.
Uses cachetools for efficient in-memory caching with automatic expiration.
"""

import hashlib
import json
import logging
from functools import wraps
from typing import Any, Callable, TypeVar, Optional, Union
from cachetools import TTLCache

logger = logging.getLogger(__name__)

T = TypeVar("T")

# =============================================================================
# Cache Instances
# =============================================================================

# Model configurations cache (5 minutes TTL)
# Cache key: model_id -> Model configuration
_models_cache = TTLCache(maxsize=100, ttl=300)

# Providers cache (5 minutes TTL)
# Cache key: provider_name -> Provider configuration
_providers_cache = TTLCache(maxsize=50, ttl=300)

# Conversations list cache (1 minute TTL - short because data changes frequently)
# Cache key: (user_id, limit, offset) -> conversation list
_conversations_cache = TTLCache(maxsize=200, ttl=60)

# Vector search results cache (10 minutes TTL - expensive to compute)
# Cache key: hash(query + filters) -> search results
_vector_search_cache = TTLCache(maxsize=500, ttl=600)

# Default LLM ID cache (1 minute TTL)
_default_llm_cache = TTLCache(maxsize=10, ttl=60)


# =============================================================================
# Cache Decorator
# =============================================================================


def cached(
    cache_instance: Optional[TTLCache] = None,
    ttl: int = 300,
    maxsize: int = 100,
    key_func: Optional[Callable] = None,
):
    """
    Decorator to cache function results with TTL.
    """
    cache = cache_instance or TTLCache(maxsize=maxsize, ttl=ttl)

    def decorator(func: Callable[..., T]):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = _generate_cache_key(func.__name__, *args, **kwargs)

            if cache_key in cache:
                logger.debug(f"Cache hit for {func.__name__}: {cache_key}")
                return cache[cache_key]

            result = await func(*args, **kwargs)
            cache[cache_key] = result
            logger.debug(f"Cache set for {func.__name__}: {cache_key}")
            return result

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = _generate_cache_key(func.__name__, *args, **kwargs)

            if cache_key in cache:
                logger.debug(f"Cache hit for {func.__name__}: {cache_key}")
                return cache[cache_key]

            result = func(*args, **kwargs)
            cache[cache_key] = result
            logger.debug(f"Cache set for {func.__name__}: {cache_key}")
            return result

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def _generate_cache_key(func_name: str, *args, **kwargs) -> str:
    """Generate a cache key from function name and arguments."""
    key_data = {
        "func": func_name,
        "args": [str(arg) for arg in args],
        "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
    }
    key_string = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(key_string.encode()).hexdigest()


# =============================================================================
# Cache Management Functions
# =============================================================================


def clear_cache(cache_instance: Optional[TTLCache] = None) -> None:
    """Clear all caches or a specific cache instance."""
    if cache_instance:
        cache_instance.clear()
    else:
        _models_cache.clear()
        _providers_cache.clear()
        _conversations_cache.clear()
        _vector_search_cache.clear()
        _default_llm_cache.clear()
    logger.info("Cache cleared")


def get_cache_stats() -> dict:
    """Get cache statistics for monitoring."""
    return {
        "models_cache": {
            "size": len(_models_cache),
            "maxsize": _models_cache.maxsize,
            "ttl": _models_cache.ttl,
        },
        "providers_cache": {
            "size": len(_providers_cache),
            "maxsize": _providers_cache.maxsize,
            "ttl": _providers_cache.ttl,
        },
        "conversations_cache": {
            "size": len(_conversations_cache),
            "maxsize": _conversations_cache.maxsize,
            "ttl": _conversations_cache.ttl,
        },
        "vector_search_cache": {
            "size": len(_vector_search_cache),
            "maxsize": _vector_search_cache.maxsize,
            "ttl": _vector_search_cache.ttl,
        },
        "default_llm_cache": {
            "size": len(_default_llm_cache),
            "maxsize": _default_llm_cache.maxsize,
            "ttl": _default_llm_cache.ttl,
        },
    }


# =============================================================================
# Cache Access Functions for Model Manager
# =============================================================================


def get_cached_model(model_id: str) -> Optional[Any]:
    """Get model from cache."""
    return _models_cache.get(model_id)


def set_cached_model(model_id: str, model: Any) -> None:
    """Set model in cache."""
    _models_cache[model_id] = model


def get_cached_provider(provider_name: str) -> Optional[Any]:
    """Get provider from cache."""
    return _providers_cache.get(provider_name)


def set_cached_provider(provider_name: str, provider: Any) -> None:
    """Set provider in cache."""
    _providers_cache[provider_name] = provider


def get_cached_default_llm() -> Optional[str]:
    """Get default LLM from cache."""
    return _default_llm_cache.get("default")


def set_cached_default_llm(model_id: str) -> None:
    """Set default LLM in cache."""
    _default_llm_cache["default"] = model_id


def invalidate_model_cache(model_id: Optional[str] = None) -> None:
    """Invalidate model cache. If model_id is None, clear all model cache."""
    if model_id:
        _models_cache.pop(model_id, None)
        logger.info(f"Cache invalidated for model: {model_id}")
    else:
        _models_cache.clear()
        logger.info("All model cache invalidated")


def invalidate_provider_cache(provider_name: Optional[str] = None) -> None:
    """Invalidate provider cache. If provider_name is None, clear all provider cache."""
    if provider_name:
        _providers_cache.pop(provider_name, None)
        logger.info(f"Cache invalidated for provider: {provider_name}")
    else:
        _providers_cache.clear()
        logger.info("All provider cache invalidated")
