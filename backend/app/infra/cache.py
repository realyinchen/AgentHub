"""Cache infrastructure — vector search cache and cache statistics.

Slim CacheManager that owns only the vector_search_cache (the only
infrastructure-level cache not managed by ModelManager).

Model/provider/default LLM caches were previously duplicated between
CacheManager and ModelManager. That redundancy has been eliminated:
ModelManager is now the single source of truth for model-related caches.

For the generic @cached decorator (TTL + Thundering Herd protection),
see `app.utils.cache`.
"""

import logging
import threading
from typing import Any, Optional

from cachetools import TTLCache

logger = logging.getLogger(__name__)


class CacheManager:
    """Unified cache manager for AgentHub infrastructure caches.

    Currently manages:
        - vector_search_cache: TTLCache for expensive vector search results

    Model/provider/default LLM caches are managed by ModelManager directly.
    """

    _instance: Optional["CacheManager"] = None

    def __new__(cls) -> "CacheManager":
        """Singleton pattern — one CacheManager per process."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_caches()
        return cls._instance

    def _init_caches(self) -> None:
        # Vector search results cache (10 minutes TTL — expensive to compute)
        # Cache key: hash(query + filters) -> search results
        self._vector_search_cache = TTLCache(maxsize=500, ttl=600)
        self._vector_search_lock = threading.Lock()

    # =========================================================================
    # Vector Search Cache Operations
    # =========================================================================

    def get_vector_search(self, key: str) -> Optional[Any]:
        """Get vector search result from cache (thread-safe)."""
        with self._vector_search_lock:
            return self._vector_search_cache.get(key)

    def set_vector_search(self, key: str, value: Any) -> None:
        """Set vector search result in cache (thread-safe)."""
        with self._vector_search_lock:
            self._vector_search_cache[key] = value

    def invalidate_vector_search(self, key: Optional[str] = None) -> None:
        """Invalidate vector search cache. If key is None, clear all."""
        with self._vector_search_lock:
            if key:
                self._vector_search_cache.pop(key, None)
                logger.info(f"Cache invalidated for vector search: {key}")
            else:
                self._vector_search_cache.clear()
                logger.info("All vector search cache invalidated")

    # =========================================================================
    # Cache Management
    # =========================================================================

    def clear_all(self) -> None:
        """Clear all caches (thread-safe)."""
        with self._vector_search_lock:
            self._vector_search_cache.clear()
        logger.info("All caches cleared")

    def get_cache_stats(self) -> dict:
        """Get cache statistics for monitoring (thread-safe)."""
        with self._vector_search_lock:
            vector_search_stats = {
                "size": len(self._vector_search_cache),
                "maxsize": self._vector_search_cache.maxsize,
                "ttl": self._vector_search_cache.ttl,
            }

        return {
            "vector_search_cache": vector_search_stats,
        }

    # =========================================================================
    # Cache Accessors for Custom Caching
    # =========================================================================

    @property
    def vector_search_cache(self) -> TTLCache:
        """Access to vector search cache for @cached decorator usage."""
        return self._vector_search_cache


# Module-level default instance
_cache_manager = CacheManager()

# Convenience accessors
get_cache_stats = _cache_manager.get_cache_stats
