from __future__ import annotations

import asyncio
import math
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.infra.llm.embedding import (
    assess_persistent_embedding_compatibility,
    get_embedding_client,
    probe_embedding_runtime,
    reset_embedding_runtime,
)
from app.infra.llm.embedding_config import build_explicit_embedding_config
from app.services.routing.semantic import InMemorySemanticRecall


def _config(
    *,
    api_key: str = "test-key",
    base_url: str = "https://openrouter.ai/api/v1",
    headers: dict[str, str] | None = None,
):
    return build_explicit_embedding_config(
        provider="openrouter",
        configured_model_id="nvidia/nemotron-3-embed-1b:free",
        api_key=api_key,
        base_url=base_url,
        headers=headers,
        is_openai_compatible=True,
        model_id="embedding-model-id",
        connection_id="openrouter-connection-id",
    )


class EmbeddingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        reset_embedding_runtime()

    def test_fingerprint_covers_connection_material_without_exposing_secret(self):
        first = _config(headers={"X-Test": "one"})
        same = _config(headers={"X-Test": "one"})
        changed_key = _config(api_key="different-key", headers={"X-Test": "one"})
        changed_header = _config(headers={"X-Test": "two"})

        self.assertEqual(first.fingerprint, same.fingerprint)
        self.assertNotEqual(first.fingerprint, changed_key.fingerprint)
        self.assertNotEqual(first.fingerprint, changed_header.fingerprint)
        self.assertNotIn("test-key", first.fingerprint)

    def test_client_cache_is_scoped_by_configuration_fingerprint(self):
        first_config = _config()
        second_config = _config(base_url="https://example.test/v1")

        first = get_embedding_client(first_config)
        same = get_embedding_client(first_config)
        second = get_embedding_client(second_config)

        self.assertIs(first, same)
        self.assertIsNot(first, second)

    async def test_probe_records_real_dimension_and_blocks_incompatible_storage(self):
        config = _config()
        response = SimpleNamespace(
            data=[{"embedding": [0.25] * 2048}],
        )
        with patch(
            "app.infra.llm.embedding.litellm.aembedding",
            new=AsyncMock(return_value=response),
        ):
            result = await probe_embedding_runtime(
                config,
                timeout_seconds=1,
                text="dimension probe",
            )

        self.assertTrue(result.probe_ok)
        self.assertEqual(result.embedding_dimensions, 2048)
        compatibility = assess_persistent_embedding_compatibility(
            config,
            storage_dimension=1024,
        )
        self.assertFalse(compatibility.compatible)
        self.assertEqual(
            compatibility.reason,
            "embedding_dimension_mismatch",
        )
        self.assertEqual(compatibility.embedding_dimension, 2048)

    async def test_probe_classifies_invalid_vectors_as_dimension_failure(self):
        config = _config()
        response = SimpleNamespace(
            data=[{"embedding": [math.nan]}],
        )
        with patch(
            "app.infra.llm.embedding.litellm.aembedding",
            new=AsyncMock(return_value=response),
        ):
            result = await probe_embedding_runtime(
                config,
                timeout_seconds=1,
            )

        self.assertFalse(result.probe_ok)
        self.assertEqual(result.error_category, "dimension")

    async def test_semantic_index_rebuilds_when_fingerprint_changes(self):
        recall = InMemorySemanticRecall()

        class FakeEmbeddings:
            def __init__(self, fingerprint: str) -> None:
                self.fingerprint = fingerprint
                self.calls = 0

            async def aembed_documents(
                self,
                texts: list[str],
            ) -> list[list[float]]:
                self.calls += 1
                return [[float(index + 1), 1.0] for index, _ in enumerate(texts)]

        first = FakeEmbeddings("fingerprint-a")
        second = FakeEmbeddings("fingerprint-b")
        await recall._ensure_index(first, first.fingerprint)
        await recall._ensure_index(first, first.fingerprint)
        await recall._ensure_index(second, second.fingerprint)

        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 1)
        self.assertEqual(recall._vector_model_key, "fingerprint-b")

    async def test_probe_timeout_is_fail_open_network_health(self):
        config = _config()

        async def slow_embedding(**_: object):
            await asyncio.sleep(0.05)
            return SimpleNamespace(data=[{"embedding": [1.0]}])

        with patch(
            "app.infra.llm.embedding.litellm.aembedding",
            new=slow_embedding,
        ):
            result = await probe_embedding_runtime(
                config,
                timeout_seconds=0.001,
            )

        self.assertFalse(result.probe_ok)
        self.assertEqual(result.error_category, "network")


if __name__ == "__main__":
    unittest.main()
