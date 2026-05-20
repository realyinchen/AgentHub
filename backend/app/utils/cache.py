"""In-Memory caching utilities for AgentHub.

Provides TTL-based caching without external dependencies like Redis.
Uses cachetools for efficient in-memory caching with automatic expiration.

Key features:
    - Thread-safe caching via cachetools.cached (built-in lock)
    - SHA256 cache keys for better collision resistance
    - Thundering Herd protection for async functions
    - Robust parameter serialization (Pydantic v2 compatible)

┌─────────────────────────────────────────────────────────────────────┐
│ 🔒 CONCURRENCY RISK ASSESSMENT (2026-05-19)                        │
├─────────────────────────────────────────────────────────────────────┤
│ 🟢 ASYNC BRANCH (@cached decorator) - FIXED                         │
│ - Changed: threading.Lock → asyncio.Lock (line ~158)                │
│ - Reason: Async functions can hold locks during long-running await   │
│ - Risk before: ❌ HIGH - Event loop blocked during cache miss + DB  │
│ - Risk now:    ✅ LOW - Non-blocking async lock                      │
│                                                                      │
│ 🟢 SYNC BRANCH - cachetools.cached with threading.Lock              │
│ - Only protects microsecond dict operations (get/set/pop)            │
│ - Risk: ✅ VERY LOW - No long-running operations under lock          │
├─────────────────────────────────────────────────────────────────────┤
│ 📌 KEY DIFFERENCE:                                                   │
│ - BAD: threading.Lock during await func(...)                        │
│ - OK:  threading.Lock during dict.get() / dict[key] = value         │
└─────────────────────────────────────────────────────────────────────┘

Future extensions:
    - CacheProtocol abstraction for Redis/Memcached integration
    - Cache value size monitoring for memory usage tracking
"""

import asyncio
import hashlib
import inspect
import json
import logging
import threading
from functools import wraps
from typing import Any, Callable, TypeVar, Optional, cast
from typing import Coroutine

from cachetools import TTLCache
from cachetools import cached as cachetools_cached

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _make_hashable(obj: Any) -> Any:
    """Convert an object to a hashable representation for cache key generation.

    Handles:
    - Primitive types (str, int, float, bool, bytes)
    - Pydantic v2 models (using model_dump)
    - Pydantic v1 models (using dict)
    - Lists, tuples, dicts, sets
    - Other objects (fallback to repr() for deterministic serialization)

    Returns a JSON-serializable representation suitable for cache key hashing.
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool, bytes)):
        return obj
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):  # Pydantic v1 compatibility
        return obj.dict()
    if isinstance(obj, (list, tuple)):
        return [_make_hashable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _make_hashable(v) for k, v in sorted(obj.items())}
    if isinstance(obj, set):
        return sorted([_make_hashable(item) for item in obj])
    # Fallback: use repr() instead of str() - more deterministic for custom objects
    return repr(obj)


def _generate_cache_key(func_name: str, *args, **kwargs) -> str:
    """Generate a cache key from function name and arguments.

    Uses SHA256 for better collision resistance than MD5.
    Returns first 16 hex chars (64 bits) as a reasonable balance between
    collision resistance and key length.

    Args:
        func_name: Qualified name of the function (to prevent cross-function key collision)
        *args: Positional arguments
        **kwargs: Keyword arguments
    """
    key_data = {
        "func": func_name,
        "args": [_make_hashable(arg) for arg in args],
        "kwargs": {k: _make_hashable(v) for k, v in sorted(kwargs.items())},
    }
    key_string = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.sha256(key_string.encode()).hexdigest()[:16]


def cached(
    cache_instance: Optional[TTLCache] = None,
    ttl: int = 300,
    maxsize: int = 100,
    key_func: Optional[Callable] = None,
    lock: Optional[threading.Lock] = None,
):
    """
    Decorator to cache function results with TTL.

    Uses cachetools.cached internally which provides thread safety via
    built-in threading.Lock. Supports both sync and async functions.

    Features:
    - Thundering Herd protection for async functions (only one concurrent execution per key)
    - Automatic function name inclusion in cache key (prevents cross-function collision)
    - Robust parameter serialization (Pydantic v2 compatible)

    Args:
        cache_instance: Optional existing TTLCache to use
        ttl: Time-to-live in seconds for new cache (default 5 minutes)
        maxsize: Maximum cache size for new cache (default 100)
        key_func: Optional custom key generation function
        lock: Optional shared lock for sync functions (useful when sharing cache across decorators)

    Returns:
        Decorated function with caching enabled
    """
    cache = cache_instance or TTLCache(maxsize=maxsize, ttl=ttl)
    _sync_lock = lock or threading.Lock()

    def decorator(func: Callable[..., T]):
        # Build key function that includes the function's qualified name
        # This prevents cache key collision between different functions
        if key_func is None:

            def _key_func(*args, **kwargs):
                return _generate_cache_key(func.__qualname__, *args, **kwargs)
        else:
            # Narrow type to Callable for Pylance (closed over in def below)
            _resolved_key_func = key_func

            # User provided custom key_func - wrap it to include function name for safety
            def _key_func(*args, **kwargs):
                return _generate_cache_key(
                    func.__qualname__ + ":" + _resolved_key_func(*args, **kwargs),
                    *args,
                    **kwargs,
                )

        if inspect.iscoroutinefunction(func):
            _lock = asyncio.Lock()
            # Track pending computations for Thundering Herd prevention
            _pending_keys: dict[str, asyncio.Event] = {}

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                cache_key = _key_func(*args, **kwargs)

                # Fast path: check cache first (outside lock)
                if cache_key in cache:
                    logger.debug(f"Cache hit for {func.__qualname__}: {cache_key}")
                    return cache[cache_key]

                # Check cache under lock and handle pending computations
                pending_event = None
                async with _lock:
                    if cache_key in cache:
                        logger.debug(
                            f"Cache hit (locked) for {func.__qualname__}: {cache_key}"
                        )
                        return cache[cache_key]
                    if cache_key in _pending_keys:
                        # Another coroutine is already computing this key
                        pending_event = _pending_keys[cache_key]
                if pending_event is not None:
                    # Wait for the pending computation to complete
                    await pending_event.wait()
                    async with _lock:
                        return cache.get(cache_key)

                # We're the first to compute this key
                event = asyncio.Event()
                async with _lock:
                    _pending_keys[cache_key] = event

                try:
                    result = await cast(Coroutine[Any, Any, Any], func(*args, **kwargs))

                    async with _lock:
                        cache[cache_key] = result
                        logger.debug(f"Cache set for {func.__qualname__}: {cache_key}")

                    return result
                finally:
                    async with _lock:
                        _pending_keys.pop(cache_key, None)
                    event.set()

            return async_wrapper
        else:
            # For sync functions, use cachetools.cached directly
            # Share the lock across all functions using this cache instance
            return cachetools_cached(cache, key=_key_func, lock=_sync_lock)(func)

    return decorator
