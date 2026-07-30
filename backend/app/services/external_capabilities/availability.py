from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExternalCapabilityAvailability:
    """Fine-grained switches shared by model projection and runtime admission."""

    weather_get: bool = False
    web_search: bool = False
    book_search: bool = False
    research_start: bool = False

    @classmethod
    def from_settings(
        cls,
        settings: Any | None = None,
    ) -> "ExternalCapabilityAvailability":
        if settings is None:
            from app.infra.config import get_settings

            settings = get_settings()
        return cls(
            weather_get=bool(settings.AGENT_CAPABILITY_WEATHER_V1),
            web_search=bool(settings.AGENT_CAPABILITY_WEB_V1),
            book_search=bool(settings.AGENT_CAPABILITY_BOOK_V1),
            research_start=bool(settings.AGENT_CAPABILITY_RESEARCH_V1),
        )

    def enabled(self, capability: str) -> bool:
        field_name = str(capability or "").strip()
        if field_name not in {
            "weather_get",
            "web_search",
            "book_search",
            "research_start",
        }:
            return False
        return bool(getattr(self, field_name))


__all__ = ["ExternalCapabilityAvailability"]

