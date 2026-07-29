"""Offline verification for the unified embedding runtime architecture."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.llm import embedding as embedding_runtime
from app.infra.embedding_spaces.contracts import build_embedding_space_spec
from app.infra.llm.embedding_config import (
    build_explicit_embedding_config,
    resolve_embedding_config,
)
from app.infra.llm.embedding_errors import classify_embedding_error


class _Settings:
    SYSTEM_DEFAULT_EMBEDDING_MODEL = "openai/env-embedding"
    SYSTEM_DEFAULT_LLM_BASE_URL = "https://env.example/v1"
    EMBEDDING_DIMENSION = 1024
    OPENROUTER_HTTP_REFERER = None
    OPENROUTER_X_TITLE = "AgentHub"
    system_default_embedding_api_key = "env-key"


class _Manager:
    _initialized = True
    default_embedding_id = "db-model-id"

    def __init__(self) -> None:
        self.model = SimpleNamespace(
            id="db-model-id",
            provider="openrouter",
            connection_id="connection-id",
            model_type="embedding",
            model_id="nvidia/nemotron-3-embed-1b:free",
            is_active=True,
        )
        self.connection = SimpleNamespace(
            provider="openrouter",
            extra_headers_json={"X-Test": "db"},
        )
        self.provider = SimpleNamespace(is_openai_compatible=True)

    def get_first_active_embedding_id(self) -> str:
        return "db-model-id"

    def get_model(self, model_id: str):
        return self.model if model_id == "db-model-id" else None

    def get_connection(self, connection_id: str):
        return self.connection if connection_id == "connection-id" else None

    def get_provider(self, provider: str):
        return self.provider if provider == "openrouter" else None

    def get_connection_api_key(self, connection_id: str) -> str:
        return "db-key"

    def get_api_key(self, provider: str) -> str:
        return "provider-key"

    def get_connection_base_url(self, connection_id: str) -> str:
        return "https://openrouter.ai/api/v1"

    def get_base_url(self, provider: str) -> str:
        return "https://provider.example/v1"


async def _verify() -> None:
    embedding_runtime.reset_embedding_runtime()
    settings = _Settings()

    resolved = resolve_embedding_config(
        manager=_Manager(),  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
    )
    assert resolved is not None
    assert resolved.source == "database"
    assert resolved.model == "openai/nvidia/nemotron-3-embed-1b:free"
    assert resolved.base_url == "https://openrouter.ai/api/v1"
    assert resolved.headers["X-Test"] == "db"
    assert resolved.dimension is None

    same = build_explicit_embedding_config(
        provider="openrouter",
        configured_model_id="nvidia/nemotron-3-embed-1b:free",
        api_key="db-key",
        base_url="https://openrouter.ai/api/v1",
        headers={"X-Test": "db"},
        is_openai_compatible=True,
        model_id="db-model-id",
        connection_id="connection-id",
        settings=settings,  # type: ignore[arg-type]
    )
    changed_key = build_explicit_embedding_config(
        provider="openrouter",
        configured_model_id="nvidia/nemotron-3-embed-1b:free",
        api_key="rotated-key",
        base_url="https://openrouter.ai/api/v1",
        headers={"X-Test": "db"},
        is_openai_compatible=True,
        model_id="db-model-id",
        connection_id="connection-id",
        settings=settings,  # type: ignore[arg-type]
    )
    assert same.fingerprint == resolved.fingerprint
    assert changed_key.fingerprint != resolved.fingerprint
    assert embedding_runtime.get_embedding_client(resolved) is (
        embedding_runtime.get_embedding_client(same)
    )
    original_space = build_embedding_space_spec(
        purpose="documents",
        config=resolved,
        dimensions=2048,
    )
    rotated_key_space = build_embedding_space_spec(
        purpose="documents",
        config=changed_key,
        dimensions=2048,
    )
    assert original_space.fingerprint == rotated_key_space.fingerprint
    assert original_space.index_kind == "hnsw_halfvec"

    original = embedding_runtime.litellm.aembedding

    async def fake_embedding(**_kwargs):
        return SimpleNamespace(data=[{"embedding": [0.25] * 2048}])

    embedding_runtime.litellm.aembedding = fake_embedding
    try:
        client = embedding_runtime.get_embedding_client(resolved)
        assert client is not None
        vector = await client.aembed_query("dimension check")
        assert len(vector) == 2048
    finally:
        embedding_runtime.litellm.aembedding = original

    compatibility = embedding_runtime.assess_persistent_embedding_compatibility(
        resolved,
        storage_dimension=1024,
    )
    assert not compatibility.compatible
    assert compatibility.reason == "embedding_dimension_mismatch"
    assert compatibility.embedding_dimension == 2048
    assert classify_embedding_error(ConnectionError("connection error")) == "network"
    assert classify_embedding_error(ValueError("dimension mismatch")) == "dimension"

    embedding_runtime.reset_embedding_runtime()


if __name__ == "__main__":
    asyncio.run(_verify())
    print("embedding runtime architecture verification passed")
