from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class DeveloperShadowClosedWindow:
    started_at: datetime
    ended_at: datetime
    collected_at: datetime


class DeveloperShadowWindowClock:
    """Own monotonic evidence-window boundaries for one preview."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))

    def open(self) -> datetime:
        return self._require_aware(self._now())

    def close(self, *, started_at: datetime) -> DeveloperShadowClosedWindow:
        started = self._require_aware(started_at)
        ended = max(
            self._require_aware(self._now()),
            started + timedelta(microseconds=1),
        )
        collected = max(self._require_aware(self._now()), ended)
        return DeveloperShadowClosedWindow(
            started_at=started,
            ended_at=ended,
            collected_at=collected,
        )

    @staticmethod
    def _require_aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("developer Shadow clock requires aware time")
        return value


__all__ = [
    "DeveloperShadowClosedWindow",
    "DeveloperShadowWindowClock",
]
