from __future__ import annotations

from app.infra.database import get_database
from app.services.provider_config import (
    ProviderRegistry,
    get_provider_registry,
    safe_enabled_provider_configs_from_db,
)
from app.services.research.observation_providers.gbrain import GBrainObservationProvider
from app.services.research.observation_providers.source import (
    ObservationProvider,
    SourceObservationProvider,
)


def get_default_observation_provider(
    provider_registry: ProviderRegistry | None = None,
) -> ObservationProvider:
    registry = provider_registry or get_provider_registry()
    for config in registry.enabled_configs(
        provider_type="research_observation",
        capability="research_observation",
    ):
        if config.provider_key == "gbrain":
            return GBrainObservationProvider(config)
    return SourceObservationProvider()


async def get_default_observation_provider_from_db() -> ObservationProvider:
    db = get_database()
    async with db.session() as session:
        configs = await safe_enabled_provider_configs_from_db(
            session,
            provider_type="research_observation",
            capability="research_observation",
        )
    for config in configs:
        if config.provider_key == "gbrain":
            return GBrainObservationProvider(config)
    return get_default_observation_provider()
