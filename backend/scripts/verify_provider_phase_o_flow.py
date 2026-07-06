"""
Verify Phase O1 app-provider contract and live-style normalization.

This check avoids real network calls and external credentials. It verifies:
- provider config scope, credential, health, and capability fields are app-owned
- submitted API keys are not echoed by config responses
- disabled or missing-credential providers do not become enabled runtime configs
- mem0 live-style payloads map into MemoryRecallProviderResult / MemoryEvent
- gbrain live-style payloads map into ObservationProviderResult / ResearchObservation

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_provider_phase_o_flow.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.memory import Mem0MemoryProvider
from app.services.memory.contracts import MemoryRecallProviderRequest
from app.services.provider_config import (
    AppProviderConfig,
    AppProviderConfigUpdate,
    ProviderRegistry,
    resolve_provider_api_key,
)
from app.services.research import GBrainObservationProvider
from app.services.research.observation_providers import ObservationProviderRequest


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _provider_config_checks() -> None:
    os.environ.pop("PHASE_O_MISSING_KEY", None)
    mem0 = AppProviderConfig(
        provider_key="mem0",
        provider_type="memory",
        enabled=True,
        capabilities=["memory_recall", "semantic_search"],
        credentials_ref="env:PHASE_O_MISSING_KEY",
    )
    registry = ProviderRegistry([mem0])
    listed = registry.list_configs().providers[0]
    _assert(listed.scope == "global", "provider scope should default to global")
    _assert(
        listed.credential_status == "missing",
        "missing env credential should be reported",
    )
    _assert(
        listed.health.status == "missing_credentials",
        "enabled provider with missing credential should show missing credential health",
    )
    _assert(
        registry.enabled_configs(provider_type="memory", capability="memory_recall") == [],
        "missing-credential provider should not be runtime-enabled",
    )

    updated = registry.update_config(
        "mem0",
        AppProviderConfigUpdate(api_key="secret-phase-o-key", enabled=True),
    )
    _assert(updated is not None, "provider update should succeed")
    assert updated is not None
    payload = updated.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False)
    _assert("secret-phase-o-key" not in serialized, "API key must not be echoed")
    _assert(updated.credentials_ref == "submitted:mem0", "submitted key should become a ref")
    _assert(updated.credential_status == "configured", "submitted key should be configured")
    _assert(
        resolve_provider_api_key(updated) == "secret-phase-o-key",
        "resolver should resolve submitted secret inside process",
    )
    _assert(
        registry.enabled_configs(provider_type="memory", capability="memory_recall"),
        "configured provider should be runtime-enabled",
    )

    cleared = registry.update_config(
        "mem0",
        AppProviderConfigUpdate(clear_credentials=True),
    )
    _assert(cleared is not None, "clear credentials should succeed")
    assert cleared is not None
    _assert(cleared.credential_status == "none", "cleared credential should be none")
    _assert(resolve_provider_api_key(cleared) == "", "cleared key should not resolve")

    try:
        AppProviderConfig(
            provider_key="bad",
            provider_type="memory",
            scope="project",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("unknown provider scope should be rejected")

    try:
        AppProviderConfig(
            provider_key="bad",
            provider_type="memory",
            capabilities=["provider_native_field"],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("provider-native capability should be rejected")


async def _mem0_live_style_normalization_check() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    provider = Mem0MemoryProvider(
        AppProviderConfig(
            provider_key="mem0",
            provider_type="memory",
            enabled=True,
            capabilities=["memory_recall"],
            settings={
                "live_response": {
                    "results": [
                        {
                            "id": str(uuid.uuid4()),
                            "memory": "The user likes warm character-driven novels.",
                            "user_id": str(user_id),
                            "categories": ["style"],
                            "score": 0.82,
                        }
                    ]
                }
            },
        )
    )
    result = await provider.search(
        MemoryRecallProviderRequest(
            user_id=user_id,
            thread_id=thread_id,
            query="warm character fiction",
            limit=5,
        )
    )
    _assert(result.status == "completed", "mem0 live-style result should complete")
    _assert(len(result.memories) == 1, "one memory should be normalized")
    memory = result.memories[0]
    _assert(memory.type == "preference", "unknown provider type should map to preference")
    _assert(memory.subject == "style", "category style should map to subject style")
    _assert(memory.value.startswith("The user likes"), "memory text should map to value")
    _assert(memory.confidence == 0.82, "score should map to confidence")
    _assert(
        memory.metadata["provider_source"] == "mem0",
        "provider source should be retained",
    )
    _assert(
        memory.metadata["provider_raw"]["memory"].startswith("The user likes"),
        "raw mem0 payload should stay in provider_raw",
    )

    missing = await Mem0MemoryProvider(
        AppProviderConfig(
            provider_key="mem0",
            provider_type="memory",
            enabled=True,
            capabilities=["memory_recall"],
            credentials_ref="env:PHASE_O_MISSING_KEY",
            settings={"mode": "live"},
        )
    ).search(
        MemoryRecallProviderRequest(
            user_id=user_id,
            query="requires credentials",
        )
    )
    _assert(missing.status == "failed", "missing live credentials should fail")
    _assert(missing.error == "missing_credentials", "missing credential error required")


async def _gbrain_live_style_normalization_check() -> None:
    run_id = uuid.uuid4()
    provider = GBrainObservationProvider(
        AppProviderConfig(
            provider_key="gbrain",
            provider_type="research_observation",
            enabled=True,
            capabilities=["research_observation"],
            settings={
                "live_response": {
                    "results": [
                        {
                            "answer": "A source says the candidate is warm and practical.",
                            "title": "Example gbrain source",
                            "url": "https://example.test/gbrain",
                            "snippet": "warm and practical",
                            "score": 0.8,
                        }
                    ]
                }
            },
        )
    )
    result = await provider.observe(
        ObservationProviderRequest(
            run_id=run_id,
            query="warm practical communication books",
        )
    )
    _assert(result.status == "completed", "gbrain live-style result should complete")
    _assert(len(result.observations) == 1, "one observation should be normalized")
    observation = result.observations[0]
    _assert(
        observation.claim.startswith("A source says"),
        "answer should map to observation claim",
    )
    _assert(observation.relevance == 4, "0.8 score should map to relevance 4")
    _assert(
        observation.metadata["provider_source"] == "gbrain",
        "provider source should be retained",
    )
    _assert(
        observation.metadata["provider_raw"]["answer"].startswith("A source says"),
        "raw gbrain payload should stay in provider_raw",
    )

    disabled = await GBrainObservationProvider(
        AppProviderConfig(
            provider_key="gbrain",
            provider_type="research_observation",
            enabled=False,
            capabilities=["research_observation"],
        )
    ).observe(
        ObservationProviderRequest(
            run_id=run_id,
            query="disabled provider",
        )
    )
    _assert(disabled.status == "skipped", "disabled gbrain should be skipped")
    _assert(disabled.error == "provider_disabled", "disabled reason required")


async def main() -> None:
    _provider_config_checks()
    await _mem0_live_style_normalization_check()
    await _gbrain_live_style_normalization_check()
    print("provider phase O verification passed")


if __name__ == "__main__":
    asyncio.run(main())
