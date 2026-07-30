from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LegacyRuntimeAvailability:
    """Explicit, one-way-compatible switches for pre-R6 runtime operations."""

    memory_write_compat: bool = True

    @classmethod
    def from_settings(
        cls,
        settings: Any | None = None,
    ) -> "LegacyRuntimeAvailability":
        if settings is None:
            from app.infra.config import get_settings

            settings = get_settings()
        return cls(
            memory_write_compat=bool(
                settings.AGENT_LEGACY_MEMORY_WRITE_COMPAT
            )
        )


__all__ = ["LegacyRuntimeAvailability"]
