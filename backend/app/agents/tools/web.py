from __future__ import annotations

import json
import logging
import re
from asyncio import timeout as asyncio_timeout
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.infra.config import get_settings
from app.infra.database import get_database
from app.services.provider_config import (
    AppProviderConfig,
    get_provider_config_from_db,
    run_tavily_search_request,
    resolve_provider_api_key,
)
from app.services.tool_admission import (
    ToolPolicyDeclaration,
    get_tool_admission_gate,
)


logger = logging.getLogger(__name__)

_SEARCH_DEPTHS = {"basic", "advanced", "fast", "ultra-fast"}
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
_QUERY_INVALID_MARKERS = ("query is invalid", "invalid query")
_QUERY_REWRITE_TIMEOUT_SECONDS = 12
WEB_SEARCH_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="web_search",
    required_policy_flags=["can_use_web_search"],
    side_effect_scope="external_call",
    external_call=True,
    max_calls_per_turn=3,
    blocked_status="tool_blocked",
)


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query.")
    max_results: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Optional result limit. Defaults to provider settings.",
    )
    search_depth: str | None = Field(
        default=None,
        description="basic, advanced, fast, or ultra-fast.",
    )
    include_answer: bool | None = Field(
        default=None,
        description="Whether Tavily should include a generated answer.",
    )
    include_raw_content: bool | None = Field(
        default=None,
        description="Whether Tavily should include raw result content.",
    )


class _ResolvedTavilyConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    api_base_url: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    status: str = "missing_credentials"
    error: str = ""


def _settings_secret_value(value: Any) -> str:
    if value is None:
        return ""
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return str(get_secret_value() or "").strip()
    return str(value or "").strip()


async def _resolve_tavily_config() -> _ResolvedTavilyConfig:
    """Resolve Tavily config at call time.

    Provider Settings DB config wins when enabled and credentialed. The .env key
    remains a fallback so existing local setups keep working.
    """
    settings = get_settings()
    env_key = _settings_secret_value(getattr(settings, "TAVILY_API_KEY", None))

    provider: AppProviderConfig | None = None
    try:
        db = get_database()
        async with db.session() as session:
            provider = await get_provider_config_from_db(session, "tavily")
    except Exception as exc:  # pragma: no cover - fallback path for startup/degraded DB
        logger.warning("Unable to read Tavily provider config from DB: %s", exc)

    if provider is not None and provider.enabled:
        db_key = resolve_provider_api_key(provider).strip()
        if db_key:
            return _ResolvedTavilyConfig(
                enabled=True,
                api_key=db_key,
                api_base_url=str(provider.settings.get("api_base_url") or "").strip(),
                settings=provider.settings,
                source=provider.credentials_ref or "db:global:tavily",
                status="configured",
            )
        return _ResolvedTavilyConfig(
            enabled=False,
            settings=provider.settings,
            source=provider.credentials_ref,
            status="missing_credentials",
            error="Tavily provider is enabled but API key is not configured.",
        )

    if env_key:
        return _ResolvedTavilyConfig(
            enabled=True,
            api_key=env_key,
            source="env:TAVILY_API_KEY",
            status="configured",
        )

    return _ResolvedTavilyConfig(
        enabled=False,
        source="",
        status="missing_credentials",
        error=(
            "Tavily API key is not configured. Set TAVILY_API_KEY in backend/.env "
            "or save Tavily Search in App Providers."
        ),
    )


def _bool_setting(
    explicit: bool | None,
    settings: dict[str, Any],
    key: str,
    default: bool,
) -> bool:
    if explicit is not None:
        return explicit
    value = settings.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _int_setting(
    explicit: int | None,
    settings: dict[str, Any],
    key: str,
    default: int,
) -> int:
    if explicit is not None:
        return max(1, min(int(explicit), 10))
    try:
        return max(1, min(int(settings.get(key, default)), 10))
    except (TypeError, ValueError):
        return default


def _search_depth(value: str | None, settings: dict[str, Any], default: str) -> str:
    raw = str(value or settings.get("search_depth") or default).strip().lower()
    return raw if raw in _SEARCH_DEPTHS else default


def _json_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _tavily_query_invalid(message: str) -> bool:
    normalized = str(message or "").lower()
    return any(marker in normalized for marker in _QUERY_INVALID_MARKERS)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def _clean_rewritten_query(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            text = str(parsed.get("query") or "").strip()
        elif isinstance(parsed, str):
            text = parsed.strip()
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    text = str(parsed.get("query") or "").strip()
            except json.JSONDecodeError:
                pass
    text = " ".join(text.strip("\"'` ").split())
    if len(text) > 180:
        text = text[:180].rsplit(" ", 1)[0].strip() or text[:180].strip()
    return text


async def _rewrite_query_with_model(query: str, error_message: str) -> str:
    if not _contains_cjk(query):
        return ""

    prompt = (
        "You rewrite web-search queries. You do not answer the user and you do "
        "not judge whether the question is well-formed.\n"
        "Task: rewrite the original query into one concise English Tavily "
        "search query.\n"
        "Preserve named entities, locations, dates, and lookup intent. Prefer "
        "searchable keywords over a sentence.\n"
        "For vague address/location questions, keep the place/entity plus the "
        "lookup intent. Example: original='法国巴黎具体地址是什么?' -> "
        "{\"query\":\"Paris France address\"}\n"
        "Return only JSON in this exact shape: {\"query\":\"...\"}. Never return "
        "an error object or explanation.\n\n"
        f"Original query: {query}\n"
        f"Tavily error: {error_message}\n"
    )

    model_errors: list[str] = []
    models: list[tuple[str, Any]] = []

    try:
        from app.infra.llm import get_llm
        from app.infra.llm.manager import get_model_manager

        manager = get_model_manager()
        model_id = manager.default_llm_id or manager.get_first_active_llm_id()
        if not model_id and not getattr(manager, "_initialized", False):
            await manager.refresh()
            model_id = manager.default_llm_id or manager.get_first_active_llm_id()
        if model_id:
            models.append(("runtime_default", get_llm(model_id)))
    except Exception as exc:  # pragma: no cover - degraded model config
        model_errors.append(f"runtime_default: {exc}")

    try:
        from app.infra.llm import get_system_llm

        models.append(("system", get_system_llm()))
    except Exception as exc:  # pragma: no cover - degraded model config
        model_errors.append(f"system: {exc}")

    for model_name, model in models:
        try:
            async with asyncio_timeout(_QUERY_REWRITE_TIMEOUT_SECONDS):
                response = await model.ainvoke(prompt)
            rewritten = _clean_rewritten_query(_message_text(response))
        except TimeoutError:
            model_errors.append(
                f"{model_name}: rewrite timed out after "
                f"{_QUERY_REWRITE_TIMEOUT_SECONDS}s"
            )
            continue
        except Exception as exc:  # pragma: no cover - provider/network failures
            model_errors.append(f"{model_name}: {exc}")
            continue
        if rewritten and rewritten.lower() != query.lower():
            return rewritten

    if model_errors:
        logger.warning("Unable to rewrite Tavily query with model: %s", "; ".join(model_errors))
    return ""


async def _fallback_query_candidates(query: str, error_message: str) -> list[str]:
    if not _contains_cjk(query):
        return []

    candidates: list[str] = []
    rewritten = await _rewrite_query_with_model(query, error_message)
    if rewritten:
        candidates.append(rewritten)

    ascii_only = " ".join(_ASCII_TOKEN_RE.findall(query))
    if ascii_only and ascii_only.lower() not in {item.lower() for item in candidates}:
        candidates.append(ascii_only)

    return candidates


def _tavily_result_error(result: Any) -> str:
    if isinstance(result, dict):
        error = result.get("error")
        if error:
            return str(error or "").strip()
        results = result.get("results")
        if isinstance(results, list):
            for item in results:
                nested = _tavily_result_error(item)
                if nested:
                    return nested
    if isinstance(result, list):
        for item in result:
            nested = _tavily_result_error(item)
            if nested:
                return nested
    return ""


def _tavily_error_type(message: str) -> str:
    normalized = message.lower()
    if "401" in normalized or "unauthorized" in normalized:
        return "unauthorized"
    if "403" in normalized or "forbidden" in normalized:
        return "forbidden"
    if "429" in normalized or "rate" in normalized:
        return "rate_limited"
    return "provider_error"


def _tavily_user_error(message: str) -> str:
    error_type = _tavily_error_type(message)
    if error_type == "unauthorized":
        return f"Configured Tavily API key was rejected: {message}"
    if error_type == "forbidden":
        return f"Configured Tavily API key is not allowed to perform this request: {message}"
    if error_type == "rate_limited":
        return f"Configured Tavily provider is rate limited: {message}"
    return message


def create_web_search(
    max_results: int = 3,
    include_answer: bool = True,
    include_raw_content: bool = False,
    search_depth: str = "basic",
    **_: Any,
) -> BaseTool:
    """Create a dynamic Tavily web search tool.

    The tool is registered even when no key exists. On each call it resolves the
    encrypted DB-backed Tavily provider config first, then falls back to .env.
    """

    @tool(args_schema=WebSearchInput)
    async def web_search(
        query: str,
        max_results: int | None = None,
        search_depth: str | None = None,
        include_answer: bool | None = None,
        include_raw_content: bool | None = None,
    ) -> str:
        """Search the live web through Tavily using server-side credentials."""
        normalized_query = " ".join(str(query or "").split()).strip()
        if not normalized_query:
            return _json_payload(
                {
                    "status": "invalid_request",
                    "provider": "tavily",
                    "error": "query is required",
                }
            )

        admission = get_tool_admission_gate().admit_current_turn(WEB_SEARCH_TOOL_POLICY)
        if not admission.allowed:
            return _json_payload(
                {
                    "status": admission.blocked_status or "tool_blocked",
                    "provider": "tavily",
                    "query": normalized_query,
                    "error": admission.reason,
                    "tool_admission": admission.model_dump(mode="json"),
                }
            )

        config = await _resolve_tavily_config()
        if not config.enabled or not config.api_key:
            return _json_payload(
                {
                    "status": config.status,
                    "provider": "tavily",
                    "query": normalized_query,
                    "error": config.error,
                    "metadata": {
                        "configured_source": config.source,
                        "writes_long_term_memory": False,
                        "writes_research_state": False,
                    },
                }
            )

        settings = config.settings or {}
        tool_max_results = _int_setting(max_results, settings, "max_results", 3)
        tool_search_depth = _search_depth(search_depth, settings, "basic")
        tool_include_answer = _bool_setting(
            include_answer,
            settings,
            "include_answer",
            True,
        )
        tool_include_raw_content = _bool_setting(
            include_raw_content,
            settings,
            "include_raw_content",
            False,
        )
        query_attempts = [normalized_query]
        attempt_index = 0
        while attempt_index < len(query_attempts):
            tavily_query = query_attempts[attempt_index]
            fallback_applied = tavily_query != normalized_query
            try:
                result = await run_tavily_search_request(
                    api_key=config.api_key,
                    query=tavily_query,
                    max_results=tool_max_results,
                    search_depth=tool_search_depth,
                    include_answer=tool_include_answer,
                    include_raw_content=tool_include_raw_content,
                    include_images=False,
                    include_image_descriptions=False,
                    include_favicon=False,
                    topic="general",
                    api_base_url=config.api_base_url,
                )
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                if _tavily_query_invalid(message):
                    for candidate in await _fallback_query_candidates(
                        normalized_query,
                        message,
                    ):
                        if candidate.lower() not in {
                            attempt.lower() for attempt in query_attempts
                        }:
                            query_attempts.append(candidate)
                    if attempt_index + 1 < len(query_attempts):
                        attempt_index += 1
                        continue
                return _json_payload(
                    {
                        "status": "failed",
                        "provider": "tavily",
                        "query": normalized_query,
                        "error_type": _tavily_error_type(message),
                        "error": _tavily_user_error(message),
                        "metadata": {
                            "configured_source": config.source,
                            "search_depth": tool_search_depth,
                            "max_results": tool_max_results,
                            "tavily_query": tavily_query,
                            "fallback_applied": fallback_applied,
                            "fallback_candidates": query_attempts[1:],
                        },
                    }
                )

            result_error = _tavily_result_error(result)
            if result_error:
                if _tavily_query_invalid(result_error):
                    for candidate in await _fallback_query_candidates(
                        normalized_query,
                        result_error,
                    ):
                        if candidate.lower() not in {
                            attempt.lower() for attempt in query_attempts
                        }:
                            query_attempts.append(candidate)
                    if attempt_index + 1 < len(query_attempts):
                        attempt_index += 1
                        continue
                return _json_payload(
                    {
                        "status": "failed",
                        "provider": "tavily",
                        "query": normalized_query,
                        "error_type": _tavily_error_type(result_error),
                        "error": _tavily_user_error(result_error),
                        "metadata": {
                            "configured_source": config.source,
                            "search_depth": tool_search_depth,
                            "max_results": tool_max_results,
                            "tavily_query": tavily_query,
                            "fallback_applied": fallback_applied,
                            "fallback_candidates": query_attempts[1:],
                            "writes_long_term_memory": False,
                            "writes_research_state": False,
                        },
                    }
                )

            return _json_payload(
                {
                    "status": "ok",
                    "provider": "tavily",
                    "query": normalized_query,
                    "result": result,
                    "metadata": {
                        "configured_source": config.source,
                        "search_depth": tool_search_depth,
                        "max_results": tool_max_results,
                        "tavily_query": tavily_query,
                        "fallback_applied": fallback_applied,
                        "fallback_candidates": query_attempts[1:],
                        "writes_long_term_memory": False,
                        "writes_research_state": False,
                    },
                }
            )
            attempt_index += 1

        return _json_payload(
            {
                "status": "failed",
                "provider": "tavily",
                "query": normalized_query,
                "error_type": "provider_error",
                "error": "Tavily query failed and no usable fallback query was available.",
                "metadata": {
                    "configured_source": config.source,
                    "search_depth": tool_search_depth,
                    "max_results": tool_max_results,
                    "fallback_candidates": query_attempts[1:],
                },
            }
        )

    web_search.name = "web_search"
    web_search.description = (
        "Search the live web through Tavily for general current facts, news, "
        "weather, addresses, locations, official websites, contact details, "
        "lookups, and non-book questions. For Chinese or other non-English "
        "lookup questions, pass a concise English search query while preserving "
        "the user's original intent. Configure the API key in App Providers or "
        "backend/.env as TAVILY_API_KEY."
    )
    return web_search
