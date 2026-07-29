from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.infra.config import get_settings
from app.infra.database import get_database
from app.services.provider_config import (
    AppProviderConfig,
    get_provider_config_from_db,
    resolve_provider_api_key,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedSearchProvider:
    name: str
    enabled: bool
    api_key: str = ""
    api_base_url: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    error: str = ""


def _secret_value(value: Any) -> str:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter() or "").strip()
    return str(value or "").strip()


async def resolve_search_provider(
    provider_name: str,
    *,
    env_setting: str,
    default_api_base_url: str,
    allow_anonymous: bool = False,
) -> ResolvedSearchProvider:
    """Resolve one adapter's runtime configuration without performing search."""

    app_settings = get_settings()
    env_key = _secret_value(getattr(app_settings, env_setting, None))
    provider: AppProviderConfig | None = None
    try:
        database = get_database()
        async with database.session() as session:
            provider = await get_provider_config_from_db(session, provider_name)
    except Exception as exc:  # pragma: no cover - degraded startup path
        logger.warning("Unable to read %s provider config: %s", provider_name, exc)

    if provider is not None and provider.enabled:
        api_key = resolve_provider_api_key(provider).strip() or env_key
        anonymous = _bool_value(
            provider.settings.get("allow_anonymous"),
            allow_anonymous,
        )
        if api_key or anonymous:
            return ResolvedSearchProvider(
                name=provider_name,
                enabled=True,
                api_key=api_key,
                api_base_url=str(
                    provider.settings.get("api_base_url") or default_api_base_url
                ).strip(),
                settings=dict(provider.settings),
                source=provider.credentials_ref or (
                    f"env:{env_setting}" if api_key else "anonymous"
                ),
            )
        return ResolvedSearchProvider(
            name=provider_name,
            enabled=False,
            settings=dict(provider.settings),
            source=provider.credentials_ref,
            error=f"{provider_name} credentials are not configured",
        )

    if env_key:
        return ResolvedSearchProvider(
            name=provider_name,
            enabled=True,
            api_key=env_key,
            api_base_url=default_api_base_url,
            source=f"env:{env_setting}",
        )
    if provider is None and allow_anonymous:
        return ResolvedSearchProvider(
            name=provider_name,
            enabled=True,
            api_base_url=default_api_base_url,
            settings={"allow_anonymous": True},
            source="anonymous",
        )
    return ResolvedSearchProvider(
        name=provider_name,
        enabled=False,
        error=f"{provider_name} is disabled or not configured",
    )


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default
