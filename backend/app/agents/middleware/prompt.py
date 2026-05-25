"""Dynamic system prompt middleware using LangChain v1's @dynamic_prompt.

Architecture
------------

This module combines two responsibilities that were previously split across
``prompt/prompt_builder.py`` and ``prompt/prompt_middleware.py``:

1. **PromptService** — Runtime prompt assembly
   - Loads templates from MD files (``app/prompts/<agent_id>.md``)
   - Supports a ``template_provider`` hook (e.g. LangSmith ``pull_prompt()``)
   - Injects time-context variables (``{current_datetime}``, ``{current_date}``, etc.)
   - Caches parsed ``ChatPromptTemplate`` objects (TTLCache, 5 min)

2. **make_dynamic_prompt(agent_id)** — Factory for ``@dynamic_prompt`` middleware
   - Returns a middleware function suitable for ``create_agent(middleware=...)``
   - Reads ``timezone`` from ``request.runtime.context`` (dataclass attribute)
   - Delegates prompt assembly to ``PromptService.build_system_prompt()``

Template resolution priority:
    1. Template provider (e.g. LangSmith ``pull_prompt``)
    2. Local MD file (``app/prompts/<agent_id>.md``)
    3. KeyError — no fallback; prompts MUST be externally provided

Usage::

    from app.agents.middleware.prompt import make_dynamic_prompt

    chatbot_prompt = make_dynamic_prompt("chatbot")
    rag_prompt = make_dynamic_prompt("rag_agent")

    agent = create_agent(
        model=llm,
        tools=tools,
        middleware=[chatbot_prompt, ...],
        context_schema=ChatbotContext,
    )
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cachetools import TTLCache
from langchain.agents.middleware import dynamic_prompt, ModelRequest
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

# ── Type Aliases ────────────────────────────────────────────────────────────

TemplateProviderFn = Callable[[str], ChatPromptTemplate]

# ── Constants ───────────────────────────────────────────────────────────────

_TEMPLATE_CACHE_TTL = 300          # 5 minutes — aligns with LangSmith SDK default
_TEMPLATE_CACHE_MAX_SIZE = 20


# =============================================================================
# PromptService
# =============================================================================

class PromptService:
    """Assembles system prompts at request time.

    Template resolution priority:
        1. Template provider (e.g. LangSmith ``pull_prompt``) — highest
        2. Local MD file (``<prompts_dir>/<agent_id>.md``) — external source
        3. KeyError — no fallback, prompts MUST be externally provided
    """

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._template_provider: Optional[TemplateProviderFn] = None
        self._prompts_dir = prompts_dir or self._resolve_default_prompts_dir()

        # TTLCache for parsed ChatPromptTemplate objects loaded from MD files.
        # We cache the ChatPromptTemplate (not the rendered string) so that each
        # request gets a fresh time context via format_messages().
        self._template_cache: TTLCache[str, ChatPromptTemplate] = TTLCache(
            maxsize=_TEMPLATE_CACHE_MAX_SIZE, ttl=_TEMPLATE_CACHE_TTL
        )
        self._template_lock = asyncio.Lock()

    @staticmethod
    def _resolve_default_prompts_dir() -> Path:
        from app.infra.config import get_settings
        return get_settings().prompts_dir

    # ── Configuration API ──────────────────────────────────────────────────

    def set_template_provider(self, provider: Optional[TemplateProviderFn]) -> None:
        """Install a template provider (e.g. LangSmith ``pull_prompt``).

        Example::

            from langsmith import Client
            client = Client()
            svc.set_template_provider(lambda aid: client.pull_prompt(aid))
        """
        self._template_provider = provider
        if provider is not None:
            logger.info("Template provider installed")

    async def clear_cache(self) -> None:
        """Clear the template cache to force reloading (async-safe)."""
        async with self._template_lock:
            self._template_cache.clear()
        logger.info("Prompt template cache cleared")

    def clear_cache_sync(self) -> None:
        """Clear cache synchronously — for startup scripts."""
        self._template_cache.clear()
        logger.info("Prompt template cache cleared (sync)")

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
                "Preloaded %d MD prompt templates: %s", len(loaded), loaded,
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
                "Invalid timezone '%s' — falling back to system local time", timezone,
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

    def _load_from_md(self, agent_id: str) -> Optional[ChatPromptTemplate]:
        """Load a ChatPromptTemplate from local MD file (with caching)."""
        cached = self._template_cache.get(agent_id)
        if cached is not None:
            logger.debug("Using cached template for %s", agent_id)
            return cached

        md_path = self._prompts_dir / f"{agent_id}.md"
        if not md_path.exists():
            logger.debug("MD prompt file not found: %s", md_path)
            return None

        try:
            template_text = md_path.read_text(encoding="utf-8")
            logger.debug("Loaded MD prompt for %s from %s", agent_id, md_path)
            chat_template = ChatPromptTemplate.from_messages(
                [("system", template_text)]
            )
            self._template_cache[agent_id] = chat_template
            return chat_template
        except Exception as e:
            logger.warning(
                "Failed to parse MD prompt for %s: %s. Falling back to next source.",
                agent_id, e,
            )
            return None

    def _resolve_template(self, agent_id: str) -> ChatPromptTemplate:
        """Resolve a ChatPromptTemplate using the priority chain.

        Priority:
            1. Template provider (e.g. LangSmith pull_prompt)
            2. Local MD file (app/prompts/<agent_id>.md)

        Raises:
            KeyError: If ``agent_id`` has no template in any source.
        """
        if self._template_provider is not None:
            try:
                template = self._template_provider(agent_id)
                if template is not None:
                    logger.debug("Using template provider for agent=%s", agent_id)
                    return template
            except Exception as e:
                logger.warning(
                    "Template provider failed for %s: %s. Falling back to MD file.",
                    agent_id, e,
                )

        md_template = self._load_from_md(agent_id)
        if md_template is not None:
            return md_template

        raise KeyError(
            f"No prompt template found for agent_id='{agent_id}'. "
            f"Ensure a MD file exists at app/prompts/{agent_id}.md "
            f"or configure a template provider."
        )

    # ── Core: prompt assembly ──────────────────────────────────────────────

    def build_system_prompt(
        self,
        agent_id: str,
        timezone: str = "Asia/Shanghai",
    ) -> str:
        """Assemble a system prompt from MD template with time context.

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
        template = self._resolve_template(agent_id)
        time_context = self._build_time_context(timezone)
        messages = template.format_messages(**time_context)
        return str(messages[0].content)


# ── Module-level singleton ──────────────────────────────────────────────────

_service_instance: Optional[PromptService] = None


def get_prompt_service() -> PromptService:
    """Get the module-level PromptService singleton.

    On first call, initializes the service and preloads all MD prompt
    templates from ``app/prompts/`` into the in-memory cache.
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = PromptService()
        _service_instance.preload_md_templates()
        logger.info(
            "PromptService initialized (prompt dir: %s)", _service_instance._prompts_dir,
        )
    return _service_instance


# =============================================================================
# make_dynamic_prompt — @dynamic_prompt middleware factory
# =============================================================================

def make_dynamic_prompt(
    agent_id: str,
    default_timezone: str = "Asia/Shanghai",
):
    """Create a ``@dynamic_prompt`` middleware for the given agent.

    This factory generates a function that:
    1. Reads ``timezone`` from ``request.runtime.context``
    2. Calls ``PromptService.build_system_prompt()`` which:
       - Loads the MD template from ``app/prompts/<agent_id>.md``
       - Renders time-context variables

    The resulting function is decorated with ``@dynamic_prompt`` so
    LangChain's agent runtime calls it before each model call.

    Args:
        agent_id: Agent identifier — must match an MD file or template provider.
        default_timezone: Fallback IANA timezone (default: ``"Asia/Shanghai"``).

    Returns:
        A ``@dynamic_prompt``-decorated function, ready for ``middleware=`` list.

    Example::

        chatbot_prompt = make_dynamic_prompt("chatbot")
        rag_prompt = make_dynamic_prompt("rag_agent", default_timezone="UTC")
    """

    @dynamic_prompt
    def _dynamic_prompt(request: ModelRequest) -> str:
        """Generate system prompt before each model call."""
        svc = get_prompt_service()

        timezone = default_timezone
        if request.runtime is not None and request.runtime.context is not None:
            tz = getattr(request.runtime.context, "timezone", None)
            if tz:
                timezone = tz

        return svc.build_system_prompt(
            agent_id=agent_id,
            timezone=timezone,
        )

    return _dynamic_prompt