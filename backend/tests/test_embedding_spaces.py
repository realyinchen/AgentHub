from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.infra.embedding_spaces.contracts import build_embedding_space_spec
from app.infra.llm.embedding import (
    get_embedding_client,
    probe_embedding_runtime,
    reset_embedding_runtime,
    subscribe_embedding_observations,
)
from app.infra.llm.embedding_config import build_explicit_embedding_config


def _config(*, api_key: str = "key-a", model: str = "embed-model"):
    return build_explicit_embedding_config(
        provider="openrouter",
        configured_model_id=model,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        is_openai_compatible=True,
        model_id="configured-model",
        connection_id="configured-connection",
    )


class EmbeddingSpaceContractTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        reset_embedding_runtime()

    def test_secret_rotation_does_not_change_semantic_space(self):
        first = _config(api_key="key-a")
        rotated = _config(api_key="key-b")

        self.assertNotEqual(first.fingerprint, rotated.fingerprint)
        first_space = build_embedding_space_spec(
            purpose="documents",
            config=first,
            dimensions=2048,
        )
        rotated_space = build_embedding_space_spec(
            purpose="documents",
            config=rotated,
            dimensions=2048,
        )

        self.assertEqual(first_space.fingerprint, rotated_space.fingerprint)
        self.assertNotEqual(
            first_space.transport_fingerprint,
            rotated_space.transport_fingerprint,
        )

    def test_model_dimension_and_purpose_define_distinct_spaces(self):
        config = _config()
        documents = build_embedding_space_spec(
            purpose="documents",
            config=config,
            dimensions=2048,
        )
        routing = build_embedding_space_spec(
            purpose="routing",
            config=config,
            dimensions=2048,
        )
        changed_dimension = build_embedding_space_spec(
            purpose="documents",
            config=config,
            dimensions=1024,
        )

        self.assertNotEqual(documents.fingerprint, routing.fingerprint)
        self.assertNotEqual(documents.fingerprint, changed_dimension.fingerprint)
        self.assertEqual(documents.index_kind, "hnsw_halfvec")
        self.assertEqual(changed_dimension.index_kind, "hnsw_vector")

    def test_high_dimensions_degrade_to_exact_search(self):
        space = build_embedding_space_spec(
            purpose="documents",
            config=_config(),
            dimensions=4096,
        )
        self.assertEqual(space.index_kind, "exact")

    def test_operator_revision_forces_a_new_semantic_space(self):
        base = _config()
        revised = build_explicit_embedding_config(
            provider="openrouter",
            configured_model_id="embed-model",
            api_key="key-a",
            base_url="https://openrouter.ai/api/v1",
            is_openai_compatible=True,
            model_id="configured-model",
            connection_id="configured-connection",
            model_revision="revision-2",
        )
        first = build_embedding_space_spec(
            purpose="documents",
            config=base,
            dimensions=2048,
        )
        second = build_embedding_space_spec(
            purpose="documents",
            config=revised,
            dimensions=2048,
        )
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    async def test_first_observation_emits_runtime_contract_once(self):
        config = _config()
        client = get_embedding_client(config)
        self.assertIsNotNone(client)
        observations = []
        unsubscribe = subscribe_embedding_observations(observations.append)
        response = SimpleNamespace(data=[{"embedding": [0.5] * 2048}])
        try:
            with patch(
                "app.infra.llm.embedding.litellm.aembedding",
                new=AsyncMock(return_value=response),
            ):
                first = await probe_embedding_runtime(config, timeout_seconds=1)
                second = await probe_embedding_runtime(config, timeout_seconds=1)
        finally:
            unsubscribe()

        self.assertTrue(first.probe_ok)
        self.assertTrue(second.probe_ok)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].dimensions, 2048)
        self.assertIs(observations[0].embeddings, client)

    async def test_live_dimension_change_emits_a_new_observation(self):
        config = _config()
        observations = []
        unsubscribe = subscribe_embedding_observations(observations.append)
        responses = [
            SimpleNamespace(data=[{"embedding": [0.5] * 1024}]),
            SimpleNamespace(data=[{"embedding": [0.5] * 2048}]),
        ]
        try:
            with patch(
                "app.infra.llm.embedding.litellm.aembedding",
                new=AsyncMock(side_effect=responses),
            ):
                first = await probe_embedding_runtime(config, timeout_seconds=1)
                second = await probe_embedding_runtime(config, timeout_seconds=1)
        finally:
            unsubscribe()

        self.assertEqual(first.embedding_dimensions, 1024)
        self.assertEqual(second.embedding_dimensions, 2048)
        self.assertEqual(
            [observation.dimensions for observation in observations],
            [1024, 2048],
        )


if __name__ == "__main__":
    unittest.main()
