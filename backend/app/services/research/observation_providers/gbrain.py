from __future__ import annotations

from time import perf_counter
from typing import Any

from app.services.provider_config import AppProviderConfig
from app.services.research.observation_providers.contracts import (
    ObservationProviderRequest,
    ObservationProviderResult,
    ResearchObservation,
    map_provider_status,
)
from app.services.research.observation_providers.source import ObservationProvider


class GBrainObservationProvider(ObservationProvider):
    """gbrain adapter behind the app-owned research observation contract.

    gbrain is treated as an observation source only. It cannot write evidence or
    final answers directly; the harness routes observations through
    ResearchOrchestrator and verifier admission.
    """

    provider_name = "gbrain"

    def __init__(
        self,
        config: AppProviderConfig | None = None,
        *,
        seed_observations: list[dict[str, Any] | ResearchObservation] | None = None,
    ) -> None:
        self.config = config
        self._seed_observations = seed_observations
        if config is not None:
            self.provider_name = config.provider_key

    async def observe(
        self,
        request: ObservationProviderRequest,
    ) -> ObservationProviderResult:
        started_at = perf_counter()
        if self.config is not None and not self.config.enabled:
            return ObservationProviderResult(
                provider_name=self.provider_name,
                query=request.query,
                status="skipped",
                observations=[],
                error="provider_disabled",
                duration_ms=self._duration_ms(started_at),
                metadata=self._provider_metadata(
                    {
                        "reason": "provider_disabled",
                        "request": request.model_dump(mode="json", exclude={"seed_observations"}),
                    }
                ),
            )

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
                metadata=self._provider_metadata(
                    {
                        "forced_status": forced_status,
                        "request": request.model_dump(mode="json", exclude={"seed_observations"}),
                    }
                ),
            )

        raw_observations = self._raw_observations(request)
        observations: list[ResearchObservation] = []
        try:
            for raw in raw_observations[: request.max_results]:
                observations.append(self._normalize_observation(raw))
        except Exception as exc:
            return ObservationProviderResult(
                provider_name=self.provider_name,
                query=request.query,
                status="failed",
                observations=[],
                error=str(exc),
                duration_ms=self._duration_ms(started_at),
                metadata=self._provider_metadata(
                    {
                        "request": request.model_dump(mode="json", exclude={"seed_observations"}),
                        "raw_count": len(raw_observations),
                    }
                ),
            )

        return ObservationProviderResult(
            provider_name=self.provider_name,
            query=request.query,
            status="completed" if observations else "empty_result",
            observations=observations,
            duration_ms=self._duration_ms(started_at),
            metadata=self._provider_metadata(
                {
                    "request": request.model_dump(mode="json", exclude={"seed_observations"}),
                    "raw_count": len(raw_observations),
                    "result_count": len(observations),
                }
            ),
        )

    def _raw_observations(
        self,
        request: ObservationProviderRequest,
    ) -> list[dict[str, Any] | ResearchObservation]:
        if self._seed_observations is not None:
            return list(self._seed_observations)
        configured = (self.config.settings if self.config else {}).get("seed_observations")
        if isinstance(configured, list):
            return configured
        live_response = (self.config.settings if self.config else {}).get("live_response")
        if live_response:
            return self._extract_live_observations(live_response, request)
        metadata_provider = request.metadata.get("provider") or {}
        metadata_seed = metadata_provider.get("gbrain_seed_observations")
        if isinstance(metadata_seed, list):
            return metadata_seed
        return list(request.seed_observations)

    def _normalize_observation(
        self,
        raw_observation: dict[str, Any] | ResearchObservation,
    ) -> ResearchObservation:
        raw_payload = (
            raw_observation.model_dump(mode="json")
            if isinstance(raw_observation, ResearchObservation)
            else dict(raw_observation)
        )
        metadata = dict(raw_payload.get("metadata") or {})
        metadata["provider_source"] = metadata.get("provider_source") or self.provider_name
        metadata["provider_raw"] = metadata.get("provider_raw", raw_payload)
        payload = {**raw_payload, "metadata": metadata}
        return ResearchObservation.model_validate(payload)

    def _extract_live_observations(
        self,
        payload: Any,
        request: ObservationProviderRequest,
    ) -> list[dict[str, Any] | ResearchObservation]:
        raw_items: list[Any] = []
        if isinstance(payload, list):
            raw_items = payload
        elif isinstance(payload, dict):
            for key in ("observations", "results", "sources", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_items = value
                    break
                if isinstance(value, dict):
                    nested = self._extract_live_observations(value, request)
                    if nested:
                        return nested
            if not raw_items and any(
                key in payload for key in ("claim", "answer", "text", "content")
            ):
                raw_items = [payload]

        normalized: list[dict[str, Any] | ResearchObservation] = []
        for item in raw_items:
            if isinstance(item, ResearchObservation):
                normalized.append(item)
                continue
            if not isinstance(item, dict):
                continue
            claim = str(
                item.get("claim")
                or item.get("answer")
                or item.get("text")
                or item.get("content")
                or item.get("summary")
                or request.query
            ).strip()
            source_title = str(
                item.get("source_title")
                or item.get("title")
                or item.get("name")
                or "gbrain observation"
            ).strip()
            source_url = str(item.get("source_url") or item.get("url") or "").strip()
            excerpt = str(
                item.get("excerpt")
                or item.get("snippet")
                or item.get("summary")
                or item.get("content")
                or ""
            ).strip()
            quality = str(item.get("quality") or "unknown").strip()
            relevance = item.get("relevance", item.get("score", 3))
            normalized.append(
                {
                    "source_type": item.get("source_type") or "web",
                    "source_title": source_title,
                    "source_url": source_url,
                    "claim": claim,
                    "excerpt": excerpt,
                    "quality": quality,
                    "relevance": self._relevance(relevance),
                    "metadata": {
                        **(item.get("metadata") or {}),
                        "provider_source": self.provider_name,
                        "provider_raw": item,
                    },
                }
            )
        return normalized

    def _relevance(self, value: Any) -> int:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 3
        if numeric <= 1:
            numeric = numeric * 5
        return max(1, min(5, round(numeric)))

    def _provider_metadata(self, raw_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_source": self.provider_name,
            "provider_raw": raw_payload,
        }

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
