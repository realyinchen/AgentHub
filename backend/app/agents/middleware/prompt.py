"""Dynamic system prompt middleware using LangChain v1's @dynamic_prompt.

Architecture
------------

1. **Module-level cache** — TTLCache (5 min) for MD template content
2. **Preload at startup** — Sync preload in lifespan for zero first-request latency
3. **@dynamic_prompt middleware** — Called before each model call

Usage::

    from app.agents.middleware.prompt import preload_templates, supervisor_prompt

    # In lifespan:
    preload_templates()

    # In create_agent:
    agent = create_agent(
        middleware=[supervisor_prompt, ...],
    )
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cachetools import TTLCache
from langchain.agents.middleware import dynamic_prompt, ModelRequest

# ── Constants ───────────────────────────────────────────────────────────────

_CACHE_TTL = 300  # 5 minutes — aligns with LangSmith SDK default
_CACHE_MAXSIZE = 20

# Dynamic path detection: Docker uses /app, local dev uses relative path
_DOCKER_PROMPTS_DIR = Path("/app/agents/prompts")
_LOCAL_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_PROMPTS_DIR = (
    _DOCKER_PROMPTS_DIR if _DOCKER_PROMPTS_DIR.exists() else _LOCAL_PROMPTS_DIR
)

# ── Module-level cache + lock ───────────────────────────────────────────────

_template_cache: TTLCache[str, str] = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL)
_cache_lock = asyncio.Lock()


# ── Public API ──────────────────────────────────────────────────────────────


def preload_templates() -> list[str]:
    """Preload all MD templates at startup (sync, called in lifespan).

    This ensures the first request never hits the filesystem.
    Returns list of loaded agent IDs for logging.
    """
    loaded: list[str] = []

    if not _PROMPTS_DIR.exists():
        return loaded

    for md_file in sorted(_PROMPTS_DIR.glob("*.md")):
        agent_id = md_file.stem
        if agent_id in _template_cache:
            continue
        try:
            _template_cache[agent_id] = md_file.read_text(encoding="utf-8")
            loaded.append(agent_id)
        except Exception:
            pass  # Skip files that can't be read

    return loaded


def clear_cache() -> None:
    """Clear template cache (useful for testing or manual refresh)."""
    _template_cache.clear()


# ── Internal helpers ───────────────────────────────────────────────────────


async def _get_template(agent_id: str) -> str:
    """Get template from cache or load from file.

    Uses asyncio.Lock to prevent concurrent file I/O for the same agent.
    """
    async with _cache_lock:
        if agent_id in _template_cache:
            return _template_cache[agent_id]

        path = _PROMPTS_DIR / f"{agent_id}.md"
        if not path.exists():
            raise KeyError(f"Prompt template not found: {path}")

        content = path.read_text(encoding="utf-8")
        _template_cache[agent_id] = content
        return content


def _build_time_context(timezone: str) -> dict[str, str | int]:
    """Build time context dict for template variable substitution.

    Uses `zoneinfo.ZoneInfo` for IANA timezone-aware datetime conversion.
    Falls back to system local time if the timezone string is invalid.
    """
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
    except (ZoneInfoNotFoundError, KeyError):
        now = datetime.now()

    return {
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_weekday": now.strftime("%A"),
        "iso_time": now.isoformat(),
        "timestamp": int(time.time()),
        "timezone": timezone,
    }


def _inject_runtime_context(
    template: str,
    timezone: str,
    user_id: str = "",
) -> str:
    """Replace runtime placeholders in template."""
    time_ctx = _build_time_context(timezone)
    return template.format(**time_ctx, user_id=user_id)


# ── Dynamic prompt middlewares ──────────────────────────────────────────────


@dynamic_prompt
async def supervisor_prompt(request: ModelRequest) -> str:
    """Dynamic system prompt for supervisor agent.

    Reads timezone from `request.runtime.context` (AgentRuntimeContext dataclass).
    Loads template from MD file with TTLCache (5 min expiry).
    Injects time context variables.
    """
    # Default timezone
    timezone = "Asia/Shanghai"

    # Read from runtime context if available
    if request.runtime and request.runtime.context:
        tz = getattr(request.runtime.context, "timezone", None)
        if tz:
            timezone = tz
        user_id = str(getattr(request.runtime.context, "user_id", "") or "")
    else:
        user_id = ""

    # Get template (from cache or file)
    template = await _get_template("supervisor")

    # Inject runtime context
    return _inject_runtime_context(template, timezone, user_id=user_id)
