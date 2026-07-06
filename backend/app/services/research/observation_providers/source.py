from __future__ import annotations

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any

from app.services.research.observation_providers.contracts import (
    ObservationProviderRequest,
    ObservationProviderResult,
    ResearchObservation,
    map_provider_status,
)


class ObservationProvider(ABC):
    """Adapter interface for provider observations."""

    provider_name: str

    @abstractmethod
    async def observe(
        self,
        request: ObservationProviderRequest,
    ) -> ObservationProviderResult:
        raise NotImplementedError


class SourceObservationProvider(ObservationProvider):
    """Simple source adapter that normalizes provided source observations."""

    def __init__(self, provider_name: str = "source") -> None:
        self.provider_name = provider_name

    async def observe(
        self,
        request: ObservationProviderRequest,
    ) -> ObservationProviderResult:
        started_at = perf_counter()
        forced_status = self._forced_status(request.metadata)
        if forced_status and map_provider_status(forced_status) != "completed":
            status = map_provider_status(forced_status)
            return ObservationProviderResult(
                provider_name=self.provider_name,
                query=request.query,
                status=status,
                observations=[],
                error=self._forced_error(request.metadata, status),
                duration_ms=self._duration_ms(started_at),
                metadata={
                    "provider_source": self.provider_name,
                    "provider_raw": {
                        "forced_status": forced_status,
                        "request": request.model_dump(mode="json"),
                    },
                },
            )

        observations = [
            self._normalize_observation(observation)
            for observation in request.seed_observations[: request.max_results]
        ]
        status = "completed" if observations else "empty_result"
        return ObservationProviderResult(
            provider_name=self.provider_name,
            query=request.query,
            status=status,
            observations=observations,
            duration_ms=self._duration_ms(started_at),
            metadata={
                "provider_source": self.provider_name,
                "provider_raw": {
                    "request": request.model_dump(mode="json"),
                    "result_count": len(observations),
                },
            },
        )

    def _normalize_observation(
        self,
        observation: ResearchObservation,
    ) -> ResearchObservation:
        raw = observation.model_dump(mode="json")
        metadata = {
            **observation.metadata,
            "provider_source": observation.metadata.get(
                "provider_source",
                self.provider_name,
            ),
            "provider_raw": observation.metadata.get("provider_raw", raw),
        }
        return observation.model_copy(update={"metadata": metadata})

    def _forced_status(self, metadata: dict[str, Any]) -> Any:
        provider_metadata = metadata.get("provider") or {}
        return metadata.get("force_status") or provider_metadata.get("force_status")

    def _forced_error(self, metadata: dict[str, Any], status: str) -> str:
        provider_metadata = metadata.get("provider") or {}
        return (
            str(metadata.get("error") or provider_metadata.get("error") or "")
            .strip()
            or f"provider returned {status}"
        )

    def _duration_ms(self, started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))
