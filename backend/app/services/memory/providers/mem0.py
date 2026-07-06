from __future__ import annotations

from time import perf_counter
from typing import Any

from app.services.memory.contracts import (
    MEMORY_POLARITIES,
    MEMORY_SUBJECTS,
    MEMORY_TYPES,
    MemoryEvent,
    MemoryRecallProviderRequest,
    MemoryRecallProviderResult,
    map_memory_provider_status,
    normalize_memory_token,
)
from app.services.memory.providers.base import MemoryRecallProvider
from app.services.provider_config import AppProviderConfig, resolve_provider_api_key


class Mem0MemoryProvider(MemoryRecallProvider):
    """mem0 adapter behind the app-owned memory recall contract.

    This adapter is recall-only. It does not own memory lifecycle operations and
    cannot decide whether a memory is current; MemoryOrchestrator filters every
    candidate against Postgres current memories.
    """

    provider_name = "mem0"

    def __init__(
        self,
        config: AppProviderConfig | None = None,
        *,
        seed_memories: list[dict[str, Any] | MemoryEvent] | None = None,
    ) -> None:
        self.config = config
        self._seed_memories = seed_memories
        if config is not None:
            self.provider_name = config.provider_key

    async def search(
        self,
        request: MemoryRecallProviderRequest,
    ) -> MemoryRecallProviderResult:
        started_at = perf_counter()
        unavailable = self._unavailable_result(request, started_at)
        if unavailable is not None:
            return unavailable

        forced_status = self._forced_status(request.metadata)
        if forced_status and map_memory_provider_status(forced_status) != "completed":
            status = map_memory_provider_status(forced_status)
            return MemoryRecallProviderResult(
                provider_name=self.provider_name,
                status=status,
                memories=[],
                error=self._forced_error(request.metadata, status),
                duration_ms=self._duration_ms(started_at),
                metadata=self._provider_metadata(
                    {
                        "forced_status": forced_status,
                        "request": request.model_dump(mode="json", exclude={"current_memories"}),
                    }
                ),
            )

        raw_memories = self._raw_memories(request)
        memories: list[MemoryEvent] = []
        try:
            for raw in raw_memories[: request.limit]:
                memories.append(self._normalize_memory(raw, request))
        except Exception as exc:
            return MemoryRecallProviderResult(
                provider_name=self.provider_name,
                status="failed",
                memories=[],
                error=str(exc),
                duration_ms=self._duration_ms(started_at),
                metadata=self._provider_metadata(
                    {
                        "request": request.model_dump(mode="json", exclude={"current_memories"}),
                        "raw_count": len(raw_memories),
                    }
                ),
            )

        return MemoryRecallProviderResult(
            provider_name=self.provider_name,
            status="completed" if memories else "empty_result",
            memories=memories,
            duration_ms=self._duration_ms(started_at),
            metadata=self._provider_metadata(
                {
                    "request": request.model_dump(mode="json", exclude={"current_memories"}),
                    "raw_count": len(raw_memories),
                    "result_count": len(memories),
                }
            ),
        )

    def _raw_memories(
        self,
        request: MemoryRecallProviderRequest,
    ) -> list[dict[str, Any] | MemoryEvent]:
        if self._seed_memories is not None:
            return list(self._seed_memories)
        configured = (self.config.settings if self.config else {}).get("seed_memories")
        if isinstance(configured, list):
            return configured
        live_response = (self.config.settings if self.config else {}).get("live_response")
        if live_response:
            return self._extract_live_memories(live_response)
        metadata_provider = request.metadata.get("provider") or {}
        metadata_seed = metadata_provider.get("mem0_seed_memories")
        if isinstance(metadata_seed, list):
            return metadata_seed
        return []

    def _normalize_memory(
        self,
        raw_memory: dict[str, Any] | MemoryEvent,
        request: MemoryRecallProviderRequest,
    ) -> MemoryEvent:
        raw_payload = (
            raw_memory.model_dump(mode="json")
            if isinstance(raw_memory, MemoryEvent)
            else dict(raw_memory)
        )
        metadata = dict(raw_payload.get("metadata") or {})
        metadata["provider_source"] = metadata.get("provider_source") or self.provider_name
        metadata["provider_raw"] = metadata.get("provider_raw", raw_payload)
        value = self._memory_value(raw_payload)
        categories = raw_payload.get("categories") or raw_payload.get("category") or []
        if isinstance(categories, str):
            categories = [categories]
        metadata["provider_categories"] = list(categories) if isinstance(categories, list) else []
        payload = {
            **raw_payload,
            "id": raw_payload.get("id") or raw_payload.get("memory_id"),
            "type": self._memory_type(raw_payload),
            "subject": self._memory_subject(raw_payload, categories),
            "value": value,
            "polarity": self._memory_polarity(raw_payload),
            "confidence": self._confidence(raw_payload),
            "user_id": raw_payload.get("user_id") or request.user_id,
            "thread_id": raw_payload.get("thread_id") or request.thread_id,
            "source": raw_payload.get("source") or "tool",
            "metadata": metadata,
        }
        return MemoryEvent.model_validate(payload)

    def _extract_live_memories(self, payload: Any) -> list[dict[str, Any] | MemoryEvent]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("memories", "results", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = self._extract_live_memories(value)
                if nested:
                    return nested
        if any(key in payload for key in ("memory", "text", "content", "value")):
            return [payload]
        return []

    def _memory_value(self, raw_payload: dict[str, Any]) -> str:
        return str(
            raw_payload.get("value")
            or raw_payload.get("memory")
            or raw_payload.get("text")
            or raw_payload.get("content")
            or ""
        ).strip()

    def _memory_type(self, raw_payload: dict[str, Any]) -> str:
        token = normalize_memory_token(raw_payload.get("type") or "preference")
        return token if token in MEMORY_TYPES else "preference"

    def _memory_subject(self, raw_payload: dict[str, Any], categories: Any) -> str:
        subject = normalize_memory_token(raw_payload.get("subject"))
        if subject in MEMORY_SUBJECTS:
            return subject
        if isinstance(categories, list) and categories:
            category = normalize_memory_token(categories[0])
            if category in MEMORY_SUBJECTS:
                return category
        return "user"

    def _memory_polarity(self, raw_payload: dict[str, Any]) -> str:
        token = normalize_memory_token(raw_payload.get("polarity") or "neutral")
        return token if token in MEMORY_POLARITIES else "neutral"

    def _confidence(self, raw_payload: dict[str, Any]) -> float:
        raw_value = raw_payload.get("confidence", raw_payload.get("score", 1.0))
        try:
            confidence = float(raw_value)
        except (TypeError, ValueError):
            confidence = 1.0
        return max(0.0, min(1.0, confidence))

    def _unavailable_result(
        self,
        request: MemoryRecallProviderRequest,
        started_at: float,
    ) -> MemoryRecallProviderResult | None:
        if self.config is not None and not self.config.enabled:
            return MemoryRecallProviderResult(
                provider_name=self.provider_name,
                status="skipped",
                memories=[],
                error="provider_disabled",
                duration_ms=self._duration_ms(started_at),
                metadata=self._provider_metadata(
                    {
                        "reason": "provider_disabled",
                        "request": request.model_dump(mode="json", exclude={"current_memories"}),
                    }
                ),
            )
        mode = (self.config.settings if self.config else {}).get("mode")
        has_live_fixture = bool((self.config.settings if self.config else {}).get("live_response"))
        if mode == "live" and not has_live_fixture and not resolve_provider_api_key(self.config):
            return MemoryRecallProviderResult(
                provider_name=self.provider_name,
                status="failed",
                memories=[],
                error="missing_credentials",
                duration_ms=self._duration_ms(started_at),
                metadata=self._provider_metadata(
                    {
                        "reason": "missing_credentials",
                        "credentials_ref": self.config.credentials_ref,
                        "request": request.model_dump(mode="json", exclude={"current_memories"}),
                    }
                ),
            )
        return None

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
