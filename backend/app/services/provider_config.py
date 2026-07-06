from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import app_provider_config as app_provider_config_crud
from app.infra.config import get_settings
from app.models.app_provider_config import AppProviderConfigRecord


APP_PROVIDER_TYPES = frozenset({"memory", "research_observation"})
APP_PROVIDER_SCOPES = frozenset({"global", "workspace", "user"})
APP_PROVIDER_CAPABILITIES = frozenset(
    {
        "memory_recall",
        "research_observation",
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


async def list_provider_configs_from_db(
    db: AsyncSession,
    *,
    scope: str = "global",
) -> AppProviderConfigList:
    records = await app_provider_config_crud.get_app_provider_configs(db, scope=scope)
    providers = [_config_from_record(record) for record in records]
    return AppProviderConfigList(providers=providers)


async def get_provider_config_from_db(
    db: AsyncSession,
    provider_key: str,
    *,
    scope: str = "global",
) -> AppProviderConfig | None:
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
    record = await app_provider_config_crud.get_app_provider_config(db, key, scope=scope)
    if record is None:
        return None

    config = _config_from_record(record)
    status = "ok"
    error_type = ""
    error = ""
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

    updated = await app_provider_config_crud.update_app_provider_config(
        db,
        key,
        {
            "health_status": status,
            "health_error_type": error_type,
            "health_error": error,
            "health_duration_ms": 0,
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
