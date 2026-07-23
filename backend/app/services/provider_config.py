from __future__ import annotations

import json
import os
import time
from asyncio import timeout as asyncio_timeout
from asyncio import to_thread as asyncio_to_thread
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import requests
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import app_provider_config as app_provider_config_crud
from app.infra.config import get_settings
from app.models.app_provider_config import AppProviderConfigRecord


APP_PROVIDER_TYPES = frozenset({"memory", "research_observation", "web_search"})
APP_PROVIDER_SCOPES = frozenset({"global", "workspace", "user"})
APP_PROVIDER_CAPABILITIES = frozenset(
    {
        "memory_recall",
        "research_observation",
        "web_search",
        "source_visit",
        "semantic_search",
    }
)
APP_PROVIDER_CREDENTIAL_STATUSES = frozenset({"none", "configured", "missing"})
APP_PROVIDER_HEALTH_STATUSES = frozenset(
    {"unknown", "disabled", "ok", "missing_credentials", "timeout", "failed"}
)
_submitted_provider_secrets: dict[str, str] = {}


def _normalize_provider_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _db_credentials_ref(provider_key: str, scope: str = "global") -> str:
    return f"db:{scope}:{provider_key}"


def _db_secret_key_from_ref(credentials_ref: str) -> str:
    ref = credentials_ref.strip()
    if not ref.startswith("db:"):
        return ""
    return ref.removeprefix("db:").strip()


class AppProviderConfig(BaseModel):
    """App-owned provider configuration contract.

    Providers adapt to this shape. Provider-native fields must stay inside
    settings/metadata and cannot redefine memory or research contracts.
    """

    provider_key: str
    provider_type: str
    scope: str = "global"
    enabled: bool = False
    display_name: str = ""
    capabilities: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    credentials_ref: str = ""
    credential_status: str = "none"
    health: "AppProviderHealth" = Field(default_factory=lambda: AppProviderHealth())
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_key", mode="before")
    @classmethod
    def validate_provider_key(cls, value: Any) -> str:
        token = _normalize_provider_token(value)
        if not token:
            raise ValueError("provider_key cannot be empty")
        return token

    @field_validator("provider_type", mode="before")
    @classmethod
    def validate_provider_type(cls, value: Any) -> str:
        token = _normalize_provider_token(value)
        if token not in APP_PROVIDER_TYPES:
            allowed = ", ".join(sorted(APP_PROVIDER_TYPES))
            raise ValueError(f"provider_type must be one of: {allowed}")
        return token

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, value: Any) -> str:
        token = _normalize_provider_token(value or "global")
        if token not in APP_PROVIDER_SCOPES:
            allowed = ", ".join(sorted(APP_PROVIDER_SCOPES))
            raise ValueError(f"scope must be one of: {allowed}")
        return token

    @field_validator("display_name", "credentials_ref", mode="before")
    @classmethod
    def clean_optional_text(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("credential_status", mode="before")
    @classmethod
    def validate_credential_status(cls, value: Any) -> str:
        token = _normalize_provider_token(value or "none")
        if token not in APP_PROVIDER_CREDENTIAL_STATUSES:
            allowed = ", ".join(sorted(APP_PROVIDER_CREDENTIAL_STATUSES))
            raise ValueError(f"credential_status must be one of: {allowed}")
        return token

    @field_validator("capabilities", mode="before")
    @classmethod
    def validate_capabilities(cls, value: Any) -> list[str]:
        raw_values = value or []
        if isinstance(raw_values, str):
            raw_values = [item.strip() for item in raw_values.split(",")]
        cleaned: list[str] = []
        for item in raw_values:
            token = _normalize_provider_token(item)
            if not token:
                continue
            if token not in APP_PROVIDER_CAPABILITIES:
                allowed = ", ".join(sorted(APP_PROVIDER_CAPABILITIES))
                raise ValueError(f"capability must be one of: {allowed}")
            if token not in cleaned:
                cleaned.append(token)
        return cleaned


class AppProviderConfigList(BaseModel):
    contract_version: str = "app-provider-config-v1"
    providers: list[AppProviderConfig] = Field(default_factory=list)


class AppProviderHealth(BaseModel):
    """Provider health telemetry exposed without credentials or raw secrets."""

    status: str = "unknown"
    error_type: str = ""
    error: str = ""
    duration_ms: int = Field(default=0, ge=0)
    checked_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        token = _normalize_provider_token(value or "unknown")
        if token not in APP_PROVIDER_HEALTH_STATUSES:
            allowed = ", ".join(sorted(APP_PROVIDER_HEALTH_STATUSES))
            raise ValueError(f"status must be one of: {allowed}")
        return token

    @field_validator("error_type", "error", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return _clean_text(value)


class AppProviderConfigUpdate(BaseModel):
    """Editable provider config input. API keys are submission-only."""

    enabled: bool | None = None
    scope: str | None = None
    display_name: str | None = None
    capabilities: list[str] | None = None
    settings: dict[str, Any] | None = None
    credentials_ref: str | None = None
    api_key: str | None = Field(
        default=None,
        description="Submission-only secret. Never returned by provider config APIs.",
    )
    clear_credentials: bool = False
    metadata: dict[str, Any] | None = None

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, value: Any) -> str | None:
        if value is None:
            return None
        token = _normalize_provider_token(value)
        if token not in APP_PROVIDER_SCOPES:
            allowed = ", ".join(sorted(APP_PROVIDER_SCOPES))
            raise ValueError(f"scope must be one of: {allowed}")
        return token

    @field_validator("capabilities", mode="before")
    @classmethod
    def validate_capabilities(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        return AppProviderConfig.validate_capabilities(value)


class ProviderRegistry:
    """In-process provider registry backed by app-owned provider configs."""

    def __init__(self, providers: list[AppProviderConfig] | None = None) -> None:
        self._providers = providers or _default_provider_configs()

    def list_configs(self) -> AppProviderConfigList:
        return AppProviderConfigList(
            providers=[_with_resolved_status(provider) for provider in self._providers]
        )

    def get_config(self, provider_key: str) -> AppProviderConfig | None:
        key = _normalize_provider_token(provider_key)
        for provider in self._providers:
            if provider.provider_key == key:
                return _with_resolved_status(provider)
        return None

    def update_config(
        self,
        provider_key: str,
        update: AppProviderConfigUpdate,
    ) -> AppProviderConfig | None:
        key = _normalize_provider_token(provider_key)
        updated: list[AppProviderConfig] = []
        target: AppProviderConfig | None = None
        for provider in self._providers:
            if provider.provider_key != key:
                updated.append(provider)
                continue
            payload = provider.model_dump(mode="json")
            update_payload = update.model_dump(exclude_unset=True)
            update_payload.pop("api_key", None)
            clear_credentials = bool(update_payload.pop("clear_credentials", False))
            if clear_credentials:
                update_payload["credentials_ref"] = ""
                update_payload["credential_status"] = "none"
                _submitted_provider_secrets.pop(provider.provider_key, None)
            elif update.api_key is not None and update.api_key.strip():
                update_payload["credentials_ref"] = f"submitted:{provider.provider_key}"
                update_payload["credential_status"] = "configured"
                _submitted_provider_secrets[provider.provider_key] = update.api_key.strip()
                update_payload.setdefault("metadata", payload.get("metadata") or {})
                update_payload["metadata"] = {
                    **(payload.get("metadata") or {}),
                    **(update_payload.get("metadata") or {}),
                    "credential_submission": "accepted_without_echo",
                }
            payload.update(update_payload)
            target = AppProviderConfig.model_validate(payload)
            updated.append(target)
        if target is None:
            return None
        self._providers = updated
        return _with_resolved_status(target)

    def enabled_configs(
        self,
        *,
        provider_type: str,
        capability: str | None = None,
    ) -> list[AppProviderConfig]:
        normalized_type = _normalize_provider_token(provider_type)
        normalized_capability = (
            _normalize_provider_token(capability) if capability else ""
        )
        configs: list[AppProviderConfig] = []
        for provider in self._providers:
            provider = _with_resolved_status(provider)
            if not provider.enabled or provider.provider_type != normalized_type:
                continue
            if provider.credential_status == "missing":
                continue
            if normalized_capability and normalized_capability not in provider.capabilities:
                continue
            configs.append(provider)
        return configs


def _default_provider_configs() -> list[AppProviderConfig]:
    return [
        AppProviderConfig(
            provider_key="mem0",
            provider_type="memory",
            enabled=False,
            display_name="mem0",
            capabilities=["memory_recall", "semantic_search"],
            credentials_ref="env:MEM0_API_KEY",
            credential_status="missing",
            health=AppProviderHealth(status="disabled"),
            metadata={"provider_source": "builtin"},
        ),
        AppProviderConfig(
            provider_key="gbrain",
            provider_type="research_observation",
            enabled=False,
            display_name="gbrain",
            capabilities=[
                "research_observation",
                "source_visit",
                "semantic_search",
            ],
            credentials_ref="env:GBRAIN_API_KEY",
            credential_status="missing",
            health=AppProviderHealth(status="disabled"),
            metadata={"provider_source": "builtin"},
        ),
        AppProviderConfig(
            provider_key="tavily",
            provider_type="web_search",
            enabled=False,
            display_name="Tavily Search",
            capabilities=["web_search"],
            settings={
                "max_results": 3,
                "search_depth": "basic",
                "include_answer": True,
                "include_raw_content": False,
                "health_check_query": "OpenAI",
                "health_check_timeout_seconds": 15,
            },
            credentials_ref="env:TAVILY_API_KEY",
            credential_status="missing",
            health=AppProviderHealth(status="disabled"),
            metadata={"provider_source": "builtin"},
        ),
    ]


def _merge_provider_configs(
    base: list[AppProviderConfig],
    overrides: list[AppProviderConfig],
) -> list[AppProviderConfig]:
    by_key = {provider.provider_key: provider for provider in base}
    for override in overrides:
        by_key[override.provider_key] = override
    return list(by_key.values())


def _parse_provider_config_json(raw_value: str) -> list[AppProviderConfig]:
    text = raw_value.strip()
    if not text:
        return []
    payload = json.loads(text)
    raw_providers = payload.get("providers") if isinstance(payload, dict) else payload
    if not isinstance(raw_providers, list):
        raise ValueError("APP_PROVIDER_CONFIGS_JSON must be a list or object with providers")
    return [AppProviderConfig.model_validate(item) for item in raw_providers]


def _credential_status_for_ref(credentials_ref: str) -> str:
    ref = credentials_ref.strip()
    if not ref:
        return "none"
    if ref.startswith("env:"):
        env_name = ref.removeprefix("env:").strip()
        return "configured" if os.getenv(env_name) else "missing"
    if ref.startswith("submitted:"):
        provider_key = ref.removeprefix("submitted:").strip()
        return "configured" if _submitted_provider_secrets.get(provider_key) else "missing"
    if ref.startswith("db:"):
        secret_key = _db_secret_key_from_ref(ref)
        return "configured" if _submitted_provider_secrets.get(secret_key) else "missing"
    return "configured"


def resolve_provider_api_key(config: AppProviderConfig) -> str:
    """Resolve a provider API key from an app-owned credential reference."""
    ref = config.credentials_ref.strip()
    if not ref:
        return ""
    if ref.startswith("env:"):
        return os.getenv(ref.removeprefix("env:").strip(), "")
    if ref.startswith("submitted:"):
        return _submitted_provider_secrets.get(ref.removeprefix("submitted:").strip(), "")
    if ref.startswith("db:"):
        return _submitted_provider_secrets.get(_db_secret_key_from_ref(ref), "")
    return ""


def _has_offline_provider_fixture(config: AppProviderConfig) -> bool:
    settings = config.settings or {}
    return any(
        key in settings
        for key in (
            "live_response",
            "seed_memories",
            "seed_observations",
        )
    )


def _coerce_bool_setting(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int_setting(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _clean_tavily_search_depth(value: Any, default: str = "basic") -> str:
    token = _normalize_provider_token(value or default)
    return token if token in {"basic", "advanced", "fast", "ultra-fast"} else default


def _redact_secret(text: str, secret: str) -> str:
    cleaned = _clean_text(text)
    if secret:
        cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def _tavily_result_count(result: Any) -> int:
    if isinstance(result, dict):
        results = result.get("results")
        if isinstance(results, list):
            return len(results)
        return 1 if result else 0
    if isinstance(result, list):
        return len(result)
    return 1 if result else 0


def _tavily_result_error(result: Any) -> str:
    if isinstance(result, dict):
        error = result.get("error")
        if error:
            return _clean_text(error)
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


async def run_tavily_search_request(
    *,
    api_key: str,
    query: str,
    max_results: int,
    search_depth: str,
    include_answer: bool,
    include_raw_content: bool,
    timeout_seconds: int = 30,
    api_base_url: str = "",
    include_images: bool = False,
    include_image_descriptions: bool = False,
    include_favicon: bool = False,
    topic: str = "general",
    time_range: str | None = None,
    country: str | None = None,
    include_usage: bool | None = None,
    exact_match: bool | None = None,
) -> dict[str, Any]:
    """Run Tavily search through requests.

    langchain-tavily's async wrapper uses aiohttp and can fail in local proxy
    setups where requests succeeds. Keep this helper small and app-owned so
    Provider Settings health checks and the chat tool exercise the same path.
    """

    base_url = (api_base_url or "https://api.tavily.com").rstrip("/")
    payload: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
        "include_images": include_images,
        "include_image_descriptions": include_image_descriptions,
        "include_favicon": include_favicon,
        "topic": topic,
        "time_range": time_range,
        "country": country,
        "include_usage": include_usage,
        "exact_match": exact_match,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Client-Source": "test01-book-assistant",
    }

    def _post() -> dict[str, Any]:
        response = requests.post(
            f"{base_url}/search",
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
        if response.status_code != 200:
            message = response.reason or "Unknown error"
            try:
                detail = response.json().get("detail", {})
            except ValueError:
                detail = {}
            if isinstance(detail, dict):
                message = str(detail.get("error") or message)
            raise ValueError(f"Error {response.status_code}: {message}")
        return response.json()

    return await asyncio_to_thread(_post)


async def _run_tavily_health_probe(config: AppProviderConfig) -> dict[str, Any]:
    """Run a low-cost live Tavily query using server-side credentials."""
    start = time.perf_counter()
    api_key = resolve_provider_api_key(config).strip()
    if not api_key:
        return {
            "health_status": "missing_credentials",
            "health_error_type": "missing_credentials",
            "health_error": "provider credentials are not configured",
            "health_duration_ms": 0,
        }

    settings = config.settings or {}
    query = _clean_text(settings.get("health_check_query") or "OpenAI")
    if not query:
        query = "OpenAI"
    query = query[:256]
    max_results = _coerce_int_setting(
        settings.get("health_check_max_results") or settings.get("max_results"),
        1,
        minimum=1,
        maximum=3,
    )
    search_depth = _clean_tavily_search_depth(
        settings.get("health_check_search_depth") or settings.get("search_depth"),
        "basic",
    )
    include_answer = _coerce_bool_setting(
        settings.get("health_check_include_answer"),
        False,
    )
    timeout_seconds = _coerce_int_setting(
        settings.get("health_check_timeout_seconds"),
        15,
        minimum=3,
        maximum=60,
    )
    api_base_url = _clean_text(settings.get("api_base_url"))

    try:
        async with asyncio_timeout(timeout_seconds):
            result = await run_tavily_search_request(
                api_key=api_key,
                query=query,
                api_base_url=api_base_url,
                timeout_seconds=timeout_seconds,
                max_results=max_results,
                include_answer=include_answer,
                include_raw_content=False,
                search_depth=search_depth,
            )
    except TimeoutError:
        return {
            "health_status": "timeout",
            "health_error_type": "timeout",
            "health_error": f"Tavily health check timed out after {timeout_seconds}s",
            "health_duration_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as exc:
        message = _redact_secret(str(exc) or exc.__class__.__name__, api_key)
        return {
            "health_status": "failed",
            "health_error_type": _tavily_error_type(message),
            "health_error": message,
            "health_duration_ms": int((time.perf_counter() - start) * 1000),
        }

    error_message = _redact_secret(_tavily_result_error(result), api_key)
    if error_message:
        return {
            "health_status": "failed",
            "health_error_type": _tavily_error_type(error_message),
            "health_error": error_message,
            "health_duration_ms": int((time.perf_counter() - start) * 1000),
        }

    result_count = _tavily_result_count(result)
    duration_ms = int((time.perf_counter() - start) * 1000)
    if result_count <= 0:
        return {
            "health_status": "failed",
            "health_error_type": "no_results",
            "health_error": f"Tavily health check returned no results for query: {query}",
            "health_duration_ms": duration_ms,
        }

    return {
        "health_status": "ok",
        "health_error_type": "",
        "health_error": "",
        "health_duration_ms": duration_ms,
    }


def _with_resolved_status(config: AppProviderConfig) -> AppProviderConfig:
    credential_status = _credential_status_for_ref(config.credentials_ref)
    health = config.health
    if not config.enabled:
        health = health.model_copy(update={"status": "disabled"})
    elif credential_status == "missing" or (
        credential_status == "none" and not _has_offline_provider_fixture(config)
    ):
        health = health.model_copy(update={"status": "missing_credentials"})
    return config.model_copy(
        update={
            "credential_status": credential_status,
            "health": health,
        }
    )


def _health_from_record(record: AppProviderConfigRecord) -> AppProviderHealth:
    return AppProviderHealth(
        status=record.health_status,
        error_type=record.health_error_type,
        error=record.health_error,
        duration_ms=record.health_duration_ms,
        checked_at=(
            record.health_checked_at.isoformat()
            if record.health_checked_at is not None
            else None
        ),
        metadata={},
    )


def _config_from_record(record: AppProviderConfigRecord) -> AppProviderConfig:
    credentials_ref = record.credentials_ref
    if record.encrypted_api_key:
        from app.utils.crypto import decrypt_api_key

        credentials_ref = _db_credentials_ref(record.provider_key, record.scope)
        _submitted_provider_secrets[_db_secret_key_from_ref(credentials_ref)] = (
            decrypt_api_key(record.encrypted_api_key)
        )
    config = AppProviderConfig(
        provider_key=record.provider_key,
        provider_type=record.provider_type,
        scope=record.scope,
        enabled=record.enabled,
        display_name=record.display_name,
        capabilities=record.capabilities or [],
        settings=record.settings or {},
        credentials_ref=credentials_ref,
        health=_health_from_record(record),
        metadata=record.metadata_json or {},
    )
    return _with_resolved_status(config)


def _record_data_from_default_config(config: AppProviderConfig) -> dict[str, Any]:
    return {
        "provider_key": config.provider_key,
        "provider_type": config.provider_type,
        "scope": config.scope,
        "enabled": config.enabled,
        "display_name": config.display_name,
        "capabilities": config.capabilities,
        "settings": config.settings,
        "credentials_ref": config.credentials_ref,
        "encrypted_api_key": "",
        "health_status": config.health.status,
        "health_error_type": config.health.error_type,
        "health_error": config.health.error,
        "health_duration_ms": config.health.duration_ms,
        "metadata_json": config.metadata,
    }


async def ensure_default_provider_configs_in_db(
    db: AsyncSession,
    *,
    scope: str = "global",
) -> None:
    """Create missing built-in provider rows without overwriting user edits."""
    normalized_scope = _normalize_provider_token(scope or "global")
    for config in _default_provider_configs():
        if config.scope != normalized_scope:
            continue
        existing = await app_provider_config_crud.get_app_provider_config(
            db,
            config.provider_key,
            scope=normalized_scope,
        )
        if existing is not None:
            continue
        await app_provider_config_crud.create_app_provider_config(
            db,
            _record_data_from_default_config(config),
        )


async def list_provider_configs_from_db(
    db: AsyncSession,
    *,
    scope: str = "global",
) -> AppProviderConfigList:
    await ensure_default_provider_configs_in_db(db, scope=scope)
    records = await app_provider_config_crud.get_app_provider_configs(db, scope=scope)
    providers = [_config_from_record(record) for record in records]
    return AppProviderConfigList(providers=providers)


async def get_provider_config_from_db(
    db: AsyncSession,
    provider_key: str,
    *,
    scope: str = "global",
) -> AppProviderConfig | None:
    await ensure_default_provider_configs_in_db(db, scope=scope)
    record = await app_provider_config_crud.get_app_provider_config(
        db,
        _normalize_provider_token(provider_key),
        scope=scope,
    )
    return _config_from_record(record) if record else None


async def update_provider_config_in_db(
    db: AsyncSession,
    provider_key: str,
    update: AppProviderConfigUpdate,
    *,
    scope: str = "global",
) -> AppProviderConfig | None:
    key = _normalize_provider_token(provider_key)
    await ensure_default_provider_configs_in_db(db, scope=scope)
    data: dict[str, Any] = {}
    payload = update.model_dump(exclude_unset=True)

    for field in (
        "enabled",
        "display_name",
        "capabilities",
        "settings",
    ):
        if field in payload:
            data[field] = payload[field]

    if "metadata" in payload:
        data["metadata_json"] = payload["metadata"]

    if "scope" in payload and payload["scope"] is not None:
        data["scope"] = payload["scope"]

    if update.clear_credentials:
        data["encrypted_api_key"] = ""
        data["credentials_ref"] = ""
    elif update.api_key is not None and update.api_key.strip():
        from app.utils.crypto import encrypt_api_key

        data["encrypted_api_key"] = encrypt_api_key(update.api_key.strip())
        data["credentials_ref"] = _db_credentials_ref(key, scope)
    elif "credentials_ref" in payload:
        data["credentials_ref"] = update.credentials_ref or ""
        if update.credentials_ref:
            data["encrypted_api_key"] = ""

    if not data:
        record = await app_provider_config_crud.get_app_provider_config(
            db,
            key,
            scope=scope,
        )
    else:
        record = await app_provider_config_crud.update_app_provider_config(
            db,
            key,
            data,
            scope=scope,
        )
    return _config_from_record(record) if record else None


async def enabled_provider_configs_from_db(
    db: AsyncSession,
    *,
    provider_type: str,
    capability: str | None = None,
    scope: str = "global",
) -> list[AppProviderConfig]:
    configs = (await list_provider_configs_from_db(db, scope=scope)).providers
    normalized_type = _normalize_provider_token(provider_type)
    normalized_capability = _normalize_provider_token(capability) if capability else ""
    result: list[AppProviderConfig] = []
    for config in configs:
        if not config.enabled or config.provider_type != normalized_type:
            continue
        if config.credential_status == "missing" or (
            config.credential_status == "none"
            and not _has_offline_provider_fixture(config)
        ):
            continue
        if normalized_capability and normalized_capability not in config.capabilities:
            continue
        result.append(config)
    return result


async def check_provider_health_in_db(
    db: AsyncSession,
    provider_key: str,
    *,
    scope: str = "global",
) -> AppProviderConfig | None:
    key = _normalize_provider_token(provider_key)
    await ensure_default_provider_configs_in_db(db, scope=scope)
    record = await app_provider_config_crud.get_app_provider_config(db, key, scope=scope)
    if record is None:
        return None

    config = _config_from_record(record)
    status = "ok"
    error_type = ""
    error = ""
    duration_ms = 0
    if not config.enabled:
        status = "disabled"
    elif config.credential_status == "missing" or (
        config.credential_status == "none" and not _has_offline_provider_fixture(config)
    ):
        status = "missing_credentials"
        error_type = "missing_credentials"
        error = "provider credentials are not configured"

    forced_status = str(config.settings.get("force_health_status") or "").strip()
    if forced_status:
        status = _normalize_provider_token(forced_status)
        if status not in APP_PROVIDER_HEALTH_STATUSES:
            status = "failed"
        if status in {"timeout", "failed"}:
            error_type = status
            error = str(config.settings.get("force_health_error") or status)
    elif status == "ok" and key == "tavily":
        tavily_health = await _run_tavily_health_probe(config)
        status = str(tavily_health["health_status"])
        error_type = str(tavily_health["health_error_type"])
        error = str(tavily_health["health_error"])
        duration_ms = int(tavily_health["health_duration_ms"])

    updated = await app_provider_config_crud.update_app_provider_config(
        db,
        key,
        {
            "health_status": status,
            "health_error_type": error_type,
            "health_error": error,
            "health_duration_ms": duration_ms,
            "health_checked_at": datetime.now(timezone.utc),
        },
        scope=scope,
    )
    return _config_from_record(updated) if updated else None


async def safe_enabled_provider_configs_from_db(
    db: AsyncSession,
    *,
    provider_type: str,
    capability: str | None = None,
    scope: str = "global",
) -> list[AppProviderConfig]:
    try:
        return await enabled_provider_configs_from_db(
            db,
            provider_type=provider_type,
            capability=capability,
            scope=scope,
        )
    except SQLAlchemyError:
        return []


@lru_cache(maxsize=1)
def get_provider_registry() -> ProviderRegistry:
    settings = get_settings()
    raw_config = getattr(settings, "APP_PROVIDER_CONFIGS_JSON", "")
    providers = _merge_provider_configs(
        _default_provider_configs(),
        _parse_provider_config_json(raw_config or ""),
    )
    return ProviderRegistry(providers)


def reset_provider_registry() -> None:
    get_provider_registry.cache_clear()
