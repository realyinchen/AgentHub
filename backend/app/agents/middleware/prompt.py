"""Dynamic system prompt middleware using LangChain v1's @dynamic_prompt.

Architecture
------------

1. **PromptService** — Runtime prompt assembly
   - Loads templates from MD files (``app/prompts/<agent_id>.md``)
   - Injects time-context variables (``{current_datetime}``, ``{current_date}``, etc.)
   - Caches parsed ``ChatPromptTemplate`` objects (TTLCache, 5 min)

2. **make_dynamic_prompt(agent_id)** — Factory for ``@dynamic_prompt`` middleware
   - Returns a middleware function suitable for ``create_agent(middleware=...)``
   - Reads ``timezone`` from ``request.runtime.context`` (dataclass attribute)
   - Delegates prompt assembly to ``PromptService.build_system_prompt()``

Usage::

    from app.agents.middleware.prompt import make_dynamic_prompt

    chatbot_prompt = make_dynamic_prompt("chatbot")
    rag_prompt = make_dynamic_prompt("rag_agent")

    agent = create_agent(
        model=llm,
        tools=tools,
        middleware=[chatbot_prompt, ...],
        context_schema=AgentRuntimeContext,
    )
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cachetools import TTLCache
from langchain.agents.middleware import dynamic_prompt, ModelRequest
from langchain_core.prompts import ChatPromptTemplate
from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_TEMPLATE_CACHE_TTL = 300  # 5 minutes — aligns with LangSmith SDK default
_TEMPLATE_CACHE_MAX_SIZE = 20


# =============================================================================
# PromptService
# =============================================================================


# Prompts directory is fixed at /app/agents/prompts
PROMPTS_DIR = Path("/app/agents/prompts")


class PromptService:
    """Assembles system prompts at request time.

    Template resolution priority:
        1. Local MD file (``<prompts_dir>/<agent_id>.md``) — external source
        2. KeyError — no fallback, prompts MUST be externally provided
    """

    def __init__(self) -> None:
        self._prompts_dir = PROMPTS_DIR

        # TTLCache for parsed ChatPromptTemplate objects loaded from MD files.
        # We cache the ChatPromptTemplate (not the rendered string) so that each
        # request gets a fresh time context via format_messages().
        self._template_cache: TTLCache[str, ChatPromptTemplate] = TTLCache(
            maxsize=_TEMPLATE_CACHE_MAX_SIZE, ttl=_TEMPLATE_CACHE_TTL
        )
        self._lock = asyncio.Lock()

    def preload_md_templates(self) -> list[str]:
        """Scan the MD prompt directory and preload all templates into cache.

        Called at startup (lifespan) to eagerly populate the cache so the
        first request never hits the filesystem. Uses synchronous file I/O
        because this runs before the event loop begins serving requests.
        """
        loaded: list[str] = []

        if not self._prompts_dir.exists():
            logger.debug("MD prompt directory not found: %s", self._prompts_dir)
            return loaded

        for md_file in sorted(self._prompts_dir.glob("*.md")):
            agent_id = md_file.stem
            if agent_id in self._template_cache:
                continue

            try:
                template_text = md_file.read_text(encoding="utf-8")
                chat_template = ChatPromptTemplate.from_messages(
                    [("system", template_text)]
                )
                self._template_cache[agent_id] = chat_template
                loaded.append(agent_id)
                logger.info("Preloaded MD prompt: %s", agent_id)
            except Exception as e:
                logger.warning("Failed to preload MD prompt %s: %s", agent_id, e)

        if loaded:
            logger.info(
                "Preloaded %d MD prompt templates: %s",
                len(loaded),
                loaded,
            )
        return loaded

    # ── Internal: time context ─────────────────────────────────────────────

    @staticmethod
    def _build_time_context(timezone: str) -> dict[str, str | int]:
        """Build time context dict for template variable substitution.

        Uses ``zoneinfo.ZoneInfo`` for IANA timezone-aware datetime conversion.
        Falls back to system local time if the timezone string is invalid.
        """
        try:
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
        except (ZoneInfoNotFoundError, KeyError):
            logger.warning(
                "Invalid timezone '%s' — falling back to system local time",
                timezone,
            )
            now = datetime.now()

        return {
            "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "current_date": now.strftime("%Y-%m-%d"),
            "current_weekday": now.strftime("%A"),
            "iso_time": now.isoformat(),
            "timestamp": int(time.time()),
            "timezone": timezone,
        }

    # ── Internal: template resolution ──────────────────────────────────────

    async def _load_template(self, agent_id: str) -> ChatPromptTemplate:
        """Load a ChatPromptTemplate from local MD file (with caching and lock)."""
        async with self._lock:
            if agent_id in self._template_cache:
                return self._template_cache[agent_id]

            md_path = self._prompts_dir / f"{agent_id}.md"
            if not md_path.exists():
                raise KeyError(f"Prompt file not found: {md_path}")

            try:
                template_text = md_path.read_text(encoding="utf-8")
                chat_template = ChatPromptTemplate.from_messages(
                    [("system", template_text)]
                )
                self._template_cache[agent_id] = chat_template
                logger.debug("Loaded prompt: %s", agent_id)
                return chat_template
            except Exception as e:
                raise RuntimeError(f"Failed to load prompt '{agent_id}'") from e

    # ── Core: prompt assembly ──────────────────────────────────────────────

    async def build_system_prompt_async(
        self,
        agent_id: str,
        timezone: str = "Asia/Shanghai",
    ) -> str:
        """Assemble a system prompt from MD template with time context (async version).

        The assembled prompt is::

            [MD template with time context variables rendered]

        Args:
            agent_id: Agent identifier (must have an MD file or template provider).
            timezone: IANA timezone for time-context substitution.

        Returns:
            Fully-assembled system prompt string.

        Raises:
            KeyError: If ``agent_id`` has no template in any source.
        """
        template = await self._load_template(agent_id)
        time_context = self._build_time_context(timezone)
        messages = template.format_messages(**time_context)
        return str(messages[0].content)

    def build_system_prompt(
        self,
        agent_id: str,
        timezone: str = "Asia/Shanghai",
    ) -> str:
        """Assemble a system prompt from MD template with time context (sync version).

        Note: This method uses the cached template directly (no async I/O).
        Templates must be preloaded via ``preload_md_templates()`` during startup.

        Args:
            agent_id: Agent identifier (must have an MD file in cache).
            timezone: IANA timezone for time-context substitution.

        Returns:
            Fully-assembled system prompt string.

        Raises:
            KeyError: If ``agent_id`` has no template in cache.
        """
        if agent_id not in self._template_cache:
            raise KeyError(
                f"Prompt '{agent_id}' not in cache. "
                f"Call preload_md_templates() during startup or use build_system_prompt_async()."
            )
        template = self._template_cache[agent_id]
        time_context = self._build_time_context(timezone)
        messages = template.format_messages(**time_context)
        return str(messages[0].content)


# ── Module-level singleton ──────────────────────────────────────────────────

_service_instance: Optional[PromptService] = None


def get_prompt_service() -> PromptService:
    """Get the module-level PromptService singleton.

    On first call, initializes the service and preloads all MD prompt
    templates from ``app/prompts/`` into the in-memory cache.

    Calling ``init_prompt_service()`` from the application lifespan
    **before** the event loop starts serving requests is the recommended
    pattern — it avoids lazy-init during the first request entirely.
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = PromptService()
        _service_instance.preload_md_templates()
        logger.info(
            "PromptService initialized (prompt dir: %s)",
            _service_instance._prompts_dir,
        )
    return _service_instance


# =============================================================================
# make_dynamic_prompt — @dynamic_prompt middleware factory
# =============================================================================


def make_dynamic_prompt(
    agent_id: str,
    default_timezone: str | None = None,
    store: BaseStore | None = None,
):
    """Create a ``@dynamic_prompt`` middleware for the given agent.

    This factory generates a function that:
    1. Reads ``timezone`` from ``request.runtime.context``
    2. Calls ``PromptService.build_system_prompt()`` which:
       - Loads the MD template from ``app/prompts/<agent_id>.md``
       - Renders time-context variables
    3. If ``store`` is provided (supervisor only), queries long-term
       memories for the current user and appends them to the prompt.

    The resulting function is decorated with ``@dynamic_prompt`` so
    LangChain's agent runtime calls it before each model call.

    Args:
        agent_id: Agent identifier — must match an MD file or template provider.
        default_timezone: Fallback IANA timezone. If None, reads from settings.
        store: LangGraph BaseStore for long-term memory (supervisor only).

    Returns:
        A ``@dynamic_prompt``-decorated function, ready for ``middleware=`` list.

    Example::

        chatbot_prompt = make_dynamic_prompt("chatbot")
        supervisor_prompt = make_dynamic_prompt("supervisor", store=store)
    """

    @dynamic_prompt
    async def _dynamic_prompt(request: ModelRequest) -> str:
        """Generate system prompt before each model call."""
        svc = get_prompt_service()

        timezone = default_timezone
        if timezone is None:
            from app.infra.config import get_settings

            timezone = get_settings().DEFAULT_TIMEZONE

        user_id = ""
        if request.runtime is not None and request.runtime.context is not None:
            tz = getattr(request.runtime.context, "timezone", None)
            if tz:
                timezone = tz
            user_id = getattr(request.runtime.context, "user_id", "")

        base_prompt = svc.build_system_prompt(
            agent_id=agent_id,
            timezone=timezone,
        )

        # Supervisor-only: inject long-term memories
        if store is not None and user_id:
            try:
                memories = store.search((user_id, "memories"))
                if memories:
                    memory_lines = [
                        f"- {m.value.get('content', str(m))}" for m in memories
                    ]
                    memory_text = "\n## Long-Term Memory\n" + "\n".join(memory_lines)
                    base_prompt = base_prompt + memory_text
            except Exception:
                logger.debug("No memories loaded for user %s", user_id)

        return base_prompt

    return _dynamic_prompt
