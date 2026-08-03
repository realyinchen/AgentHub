from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.model_probe import ProbeConfig, get_model_probe
from app.services.model_probe.chat import ChatProbe
from app.services.model_probe.embedding import EmbeddingProbe
from app.services.model_probe.errors import classify_probe_error
from app.crud.model_capability import create_capability_check
from app.schemas.model import ModelCapabilityStatus


def _config(**overrides) -> ProbeConfig:
    values = {
        "provider": "openrouter",
        "provider_model_id": "nvidia/nemotron-3-embed-1b:free",
        "api_key": "test-key",
        "base_url": "https://openrouter.ai/api/v1",
        "is_openai_compatible": True,
        "timeout_seconds": 1,
        "check_thinking": False,
    }
    values.update(overrides)
    return ProbeConfig(**values)


class _FakeEmbeddingClient:
    def __init__(self, vectors):
        self.vectors = vectors
        self.inputs = None

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs = texts
        return self.vectors


class _FakeSession:
    def __init__(self) -> None:
        self.added = None

    def add(self, value) -> None:
        self.added = value

    async def flush(self) -> None:
        return None

    async def refresh(self, value) -> None:
        value.id = value.id or uuid.uuid4()
        value.checked_at = value.checked_at or datetime.now(timezone.utc)


class ModelProbeTests(unittest.IsolatedAsyncioTestCase):
    def test_dispatches_by_modality(self) -> None:
        self.assertIsInstance(get_model_probe("embedding"), EmbeddingProbe)
        self.assertIsInstance(get_model_probe("llm"), ChatProbe)
        self.assertIsInstance(get_model_probe("vlm"), ChatProbe)

    async def test_embedding_probe_validates_and_reports_dimensions(self) -> None:
        client = _FakeEmbeddingClient([[0.1, 0.2], [0.3, 0.4]])
        outcome = await EmbeddingProbe(lambda _config: client).run(_config())

        self.assertTrue(outcome.probe_ok)
        self.assertEqual(outcome.probe_kind, "embedding")
        self.assertEqual(outcome.embedding_dimensions, 2)
        self.assertIsNone(outcome.error_category)
        self.assertEqual(len(client.inputs), 2)

    async def test_embedding_probe_rejects_inconsistent_dimensions(self) -> None:
        client = _FakeEmbeddingClient([[0.1, 0.2], [0.3]])
        outcome = await EmbeddingProbe(lambda _config: client).run(_config())

        self.assertFalse(outcome.probe_ok)
        self.assertEqual(outcome.error_category, "dimension")
        self.assertEqual(outcome.error_type, "invalid_embedding_dimensions")

    async def test_embedding_probe_honors_timeout(self) -> None:
        class SlowClient:
            async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
                await asyncio.sleep(0.05)
                return [[0.1], [0.2]]

        outcome = await EmbeddingProbe(lambda _config: SlowClient()).run(
            _config(timeout_seconds=0.001)
        )

        self.assertFalse(outcome.probe_ok)
        self.assertEqual(outcome.error_category, "network")

    async def test_chat_probe_reports_generic_and_reasoning_fields(self) -> None:
        async def invoke(*, config, thinking_mode, prompt):
            if thinking_mode:
                return AIMessage(
                    content="OK",
                    additional_kwargs={"reasoning_content": "17 + 25 = 42"},
                )
            return AIMessage(content="OK")

        outcome = await ChatProbe(invoke).run(_config(check_thinking=True))

        self.assertTrue(outcome.probe_ok)
        self.assertEqual(outcome.probe_kind, "chat")
        self.assertTrue(outcome.thinking_request_ok)
        self.assertTrue(outcome.reasoning_text_ok)

    async def test_chat_probe_uses_configured_thinking_for_basic_request(
        self,
    ) -> None:
        observed: list[bool] = []

        async def invoke(*, config, thinking_mode, prompt):
            observed.append(thinking_mode)
            return AIMessage(content="OK")

        outcome = await ChatProbe(invoke).run(
            _config(
                check_thinking=False,
                configured_thinking=True,
            )
        )

        self.assertTrue(outcome.probe_ok)
        self.assertEqual(observed, [True])

    def test_error_categories_are_stable(self) -> None:
        cases = {
            "Connection error": "network",
            "401 Unauthorized": "auth",
            "model not found": "model",
            "429 too many requests": "rate_limit",
            "provider returned inconsistent dimensions": "dimension",
            "bad response": "provider",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(classify_probe_error(Exception(message)), expected)

    async def test_capability_storage_projects_canonical_and_legacy_fields(self) -> None:
        session = _FakeSession()
        model_id = uuid.uuid4()
        check = await create_capability_check(
            session,
            {
                "model_id": model_id,
                "provider": "openrouter",
                "provider_model_id": "nvidia/nemotron-3-embed-1b:free",
                "probe_kind": "embedding",
                "probe_ok": True,
                "embedding_dimensions": 2048,
                "error_category": None,
                "raw_summary": {"model_type": "embedding"},
            },
        )

        self.assertTrue(check.chat_ok)
        self.assertTrue(check.probe_ok)
        self.assertEqual(check.probe_kind, "embedding")
        self.assertEqual(check.embedding_dimensions, 2048)
        status = ModelCapabilityStatus.model_validate(check)
        self.assertTrue(status.probe_ok)
        self.assertTrue(status.chat_ok)
        self.assertEqual(status.embedding_dimensions, 2048)

    def test_legacy_capability_row_projects_chat_probe(self) -> None:
        from app.models.model_capability import ModelCapabilityCheck

        check = ModelCapabilityCheck(
            id=uuid.uuid4(),
            model_id=uuid.uuid4(),
            provider="openrouter",
            provider_model_id="legacy-chat-model",
            checked_at=datetime.now(timezone.utc),
            chat_ok=True,
            raw_summary={},
        )

        status = ModelCapabilityStatus.model_validate(check)
        self.assertEqual(status.probe_kind, "chat")
        self.assertTrue(status.probe_ok)
        self.assertTrue(status.chat_ok)


if __name__ == "__main__":
    unittest.main()
