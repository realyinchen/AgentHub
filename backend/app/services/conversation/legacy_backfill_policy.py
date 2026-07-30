from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LegacyHistoryBackfillPolicy:
    """Authorize and audit the temporary read-only pre-Journal bridge."""

    enabled: bool = False

    @classmethod
    def from_settings(
        cls,
        settings: Any | None = None,
    ) -> "LegacyHistoryBackfillPolicy":
        if settings is None:
            from app.infra.config import get_settings

            settings = get_settings()
        return cls(
            enabled=bool(settings.AGENT_LEGACY_HISTORY_READ_FALLBACK)
        )

    def authorize(self, *, user_id: UUID, thread_id: UUID) -> bool:
        if not self.enabled:
            return False
        logger.warning(
            "legacy_history_fallback_read compatibility=read_only "
            "user_id=%s thread_id=%s",
            user_id,
            thread_id,
        )
        return True


__all__ = ["LegacyHistoryBackfillPolicy"]
