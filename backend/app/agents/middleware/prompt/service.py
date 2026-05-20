"""Runtime prompt assembly service.

Composes a final system prompt by combining:

1. A ChatPromptTemplate (from template provider or MD file)
2. Time / locale context (always, via template variable substitution)

Architecture
------------

Template resolution follows a priority chain, each step returning a
``ChatPromptTemplate`` — the same type LangSmith's ``pull_prompt()`` returns::

    template_provider  →  MD file  →  KeyError

There is NO built-in fallback. All agent prompts MUST come from either:
- A template provider (e.g. LangSmith Hub)
- A local MD file (``app/prompts/<agent_id>.md``)

This ensures prompts are always externally managed and never hardcoded.

Template Provider
    A ``Callable[[str], ChatPromptTemplate]`` that receives an ``agent_id``
    and returns a ``ChatPromptTemplate``.  When set, it is the highest-
    priority template source.

    **LangSmith migration example**::

        from langsmith import Client
        client = Client()
        svc.set_template_provider(lambda aid: client.pull_prompt(aid))

    Both the provider and MD-file loader return ``ChatPromptTemplate``, so
    ``.format_messages()`` works identically regardless of the source.

MD File Loading
    Local ``app/prompts/<agent_id>.md`` files act as a mock external
    source.  Changes take effect after cache TTL (5 min) expires; use
    ``clear_cache()`` for immediate effect.

LangSmith SDK Cache Compatibility
    LangSmith SDK (>= 0.7.0) includes built-in in-memory caching with
    stale-while-revalidate:

    - Default TTL: 300 seconds (same as our TTLCache)
    - Default max_size: 100

    When using ``pull_prompt()`` via a template provider, the SDK cache
    handles caching automatically — the local ``_template_cache`` can be
    removed or kept as an additional layer.

Time Context
    ``_build_time_context`` uses ``zoneinfo.ZoneInfo`` (Python 3.9+ stdlib)
    for IANA timezone-aware datetime conversion. No external dependency
    needed.  Fallback: if the timezone string is invalid, falls back to
    system local time with a warning log.
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cachetools import TTLCache
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

# ── Type Aliases ─────────────────────────────────────────────────────

# Template provider: agent_id -> ChatPromptTemplate
# Same return type as langsmith.Client.pull_prompt(), enabling drop-in replacement.
TemplateProviderFn = Callable[[str], ChatPromptTemplate]


# ── Constants ────────────────────────────────────────────────────────

# Backend app root (4 levels up from this file: backend/app/agents/middleware/prompt/service.py)
_APP_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Local MD prompt directory — each agent's prompt stored as app/prompts/<agent_id>.md
_MD_PROMPT_DIR = _APP_ROOT / "prompts"

# Template cache TTL in seconds (5 minutes) — aligns with LangSmith SDK default
_TEMPLATE_CACHE_TTL = 300

# Template cache capacity
_TEMPLATE_CACHE_MAX_SIZE = 20


class PromptService:
    """Assembles system prompts at request time.

    Template resolution priority:
        1. Template provider (e.g. LangSmith ``pull_prompt``) — highest priority
        2. Local MD file (``app/prompts/<agent_id>.md``) — external source
        3. KeyError — no fallback, prompts MUST be externally provided

    Both sources return the same type (``ChatPromptTemplate``), so
    ``.format_messages()`` works identically regardless of source.
    """

    def __init__(self) -> None:
        self._template_provider: Optional[TemplateProviderFn] = None

        # Thread-safe cache for parsed ChatPromptTemplate objects loaded from MD files.
        # We cache the ChatPromptTemplate (not the rendered string) so that each
        # request gets a fresh time context via format_messages(). Caching rendered
        # strings would serve stale timestamps within the TTL window.
        self._template_cache: TTLCache[str, ChatPromptTemplate] = TTLCache(
            maxsize=_TEMPLATE_CACHE_MAX_SIZE, ttl=_TEMPLATE_CACHE_TTL
        )
        # asyncio.Lock for cache write protection in async context.
        # Unlike threading.Lock, this does NOT block the event loop.
        self._template_lock = asyncio.Lock()

    # ── Configuration API ───────────────────────────────────────────

    def set_template_provider(self, provider: Optional[TemplateProviderFn]) -> None:
        """Install a template provider for external prompt sources.

        The provider receives an ``agent_id`` and returns a
        ``ChatPromptTemplate`` — the same type as
        ``langsmith.Client.pull_prompt()``.

        **Example — LangSmith Hub**::

            from langsmith import Client
            client = Client()
            svc.set_template_provider(lambda aid: client.pull_prompt(aid))

        **Example — custom database source**::

            def load_from_db(agent_id: str) -> ChatPromptTemplate:
                text = db.get_prompt(agent_id)
                return ChatPromptTemplate.from_messages([("system", text)])

            svc.set_template_provider(load_from_db)

        Args:
            provider: A callable ``(agent_id) -> ChatPromptTemplate``,
                or ``None`` to remove the provider.
        """
        self._template_provider = provider
        if provider is not None:
            logger.info("Template provider installed")

    async def clear_cache(self) -> None:
        """Clear the template cache to force reloading.

        Useful for development or when MD file changes need to take effect
        before the cache TTL expires.
        """
        async with self._template_lock:
            self._template_cache.clear()
        logger.info("Prompt template cache cleared")

    def clear_cache_sync(self) -> None:
        """Synchronous cache clear — for use in __init__ / startup scripts."""
        self._template_cache.clear()
        logger.info("Prompt template cache cleared (sync)")

    def preload_md_templates(self) -> list[str]:
        """Scan the MD prompt directory and preload all templates into cache.

        Called at startup to eagerly populate the cache so that the first
        request never hits the filesystem.  Returns a list of agent_ids
        that were successfully loaded.

        This is a one-time cost — after preloading, templates are served
        from cache until TTL expires.

        Uses synchronous file I/O because this runs at startup (lifespan)
        before the async event loop begins serving requests.
        """
        loaded: list[str] = []

        if not _MD_PROMPT_DIR.exists():
            logger.debug("MD prompt directory not found: %s", _MD_PROMPT_DIR)
            return loaded

        for md_file in sorted(_MD_PROMPT_DIR.glob("*.md")):
            agent_id = md_file.stem
            if agent_id in self._template_cache:
                continue  # already cached

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

    # ── Internal: time context ──────────────────────────────────────

    @staticmethod
    def _build_time_context(timezone: str) -> dict[str, str | int]:
        """Build time context dict for template variable substitution.

        Uses ``zoneinfo.ZoneInfo`` for IANA timezone-aware datetime conversion.
        Falls back to system local time if the timezone string is invalid.

        Returns a dict with keys: current_datetime, current_date,
        current_weekday, iso_time, timestamp, timezone.
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

    # ── Internal: template resolution ───────────────────────────────

    def _load_from_md(self, agent_id: str) -> Optional[ChatPromptTemplate]:
        """Load a ChatPromptTemplate from local MD file.

        The MD file is treated as a mock external source, following the
        same pattern as LangSmith's ``pull_prompt()`` — both return
        ``ChatPromptTemplate`` objects with ``{variable}`` placeholders.

        NOTE: This method performs synchronous file I/O. Template cache
        reads are lock-free (TTLCache supports concurrent reads). Cache
        writes happen at startup (preload) or on TTL expiry, which is
        acceptable for production workloads. For extremely high concurrency
        (>10K QPS), consider making this async with aiofiles.

        Returns:
            ``ChatPromptTemplate`` if the MD file exists and parses,
            ``None`` otherwise.
        """
        # Check cache first (no lock — TTLCache supports concurrent reads)
        cached = self._template_cache.get(agent_id)
        if cached is not None:
            logger.debug("Using cached template for %s", agent_id)
            return cached

        # Cache miss — read and parse MD file
        md_path = _MD_PROMPT_DIR / f"{agent_id}.md"
        if not md_path.exists():
            logger.debug("MD prompt file not found: %s", md_path)
            return None

        try:
            template_text = md_path.read_text(encoding="utf-8")
            logger.debug("Loaded MD prompt for %s from %s", agent_id, md_path)

            # Parse into ChatPromptTemplate — same type as pull_prompt() output
            chat_template = ChatPromptTemplate.from_messages(
                [("system", template_text)]
            )

            # Cache the parsed template (NOT the rendered string).
            # TTLCache set is safe without external lock for concurrent reads;
            # worst case: two threads parse the same file, last write wins.
            self._template_cache[agent_id] = chat_template

            return chat_template

        except Exception as e:
            logger.warning(
                "Failed to parse MD prompt for %s: %s. Falling back to next source.",
                agent_id,
                e,
            )
            return None

    def _resolve_template(self, agent_id: str) -> ChatPromptTemplate:
        """Resolve a ChatPromptTemplate using the priority chain.

        Priority:
            1. Template provider (e.g. LangSmith pull_prompt)
            2. Local MD file (app/prompts/<agent_id>.md)

        Returns:
            A ``ChatPromptTemplate`` ready for ``.format_messages()``.

        Raises:
            KeyError: If ``agent_id`` has no template in any source.
        """
        # 1. Template provider (highest priority — e.g. LangSmith Hub)
        if self._template_provider is not None:
            try:
                template = self._template_provider(agent_id)
                if template is not None:
                    logger.debug("Using template provider for agent=%s", agent_id)
                    return template
            except Exception as e:
                logger.warning(
                    "Template provider failed for %s: %s. Falling back to MD file.",
                    agent_id,
                    e,
                )

        # 2. Local MD file (external source)
        md_template = self._load_from_md(agent_id)
        if md_template is not None:
            return md_template

        raise KeyError(
            f"No prompt template found for agent_id='{agent_id}'. "
            f"Ensure a MD file exists at app/prompts/{agent_id}.md "
            f"or configure a template provider."
        )

    # ── Core: prompt assembly ───────────────────────────────────────

    def build_system_prompt(
        self,
        agent_id: str,
        timezone: str = "Asia/Shanghai",
    ) -> str:
        """Assemble a system prompt from MD template with time context.

        This is the primary method for use with LangChain v1's
        ``@dynamic_prompt`` middleware.

        The assembled prompt is::

            [MD template with time context rendered]

        The time context uses ``zoneinfo.ZoneInfo`` for true IANA timezone
        conversion (not just a string placeholder). If the timezone is
        invalid, falls back to system local time.

        Args:
            agent_id: Agent identifier (must have an MD file or template provider)
            timezone: IANA timezone for time-context substitution

        Returns:
            The fully-assembled system prompt string.

        Raises:
            KeyError: If ``agent_id`` has no template in any source.
        """
        template = self._resolve_template(agent_id)
        time_context = self._build_time_context(timezone)

        messages = template.format_messages(**time_context)
        return str(messages[0].content)


# ── Module-level singleton ──────────────────────────────────────────

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
        logger.info("PromptService initialized (prompt dir: %s)", _MD_PROMPT_DIR)
    return _service_instance
