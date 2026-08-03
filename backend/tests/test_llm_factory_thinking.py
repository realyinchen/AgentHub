from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.infra.llm.factory import get_llm


class _Manager:
    def __init__(self, *, thinking: bool) -> None:
        self.model = SimpleNamespace(
            model_id="configured-model",
            provider="dashscope",
            connection_id=None,
            thinking=thinking,
        )
        self.provider = SimpleNamespace(is_openai_compatible=False)

    def get_model(self, _model_id):
        return self.model

    def get_connection(self, _connection_id):
        return None

    def get_provider(self, _provider):
        return self.provider

    def get_api_key(self, _provider):
        return "test-key"

    def get_base_url(self, _provider):
        return None


class LlmFactoryThinkingTests(unittest.TestCase):
    def test_omitted_mode_uses_database_configuration(self) -> None:
        sentinel = object()
        with (
            patch(
                "app.infra.llm.factory.get_model_manager",
                return_value=_Manager(thinking=True),
            ),
            patch(
                "app.infra.llm.factory.create_llm_from_config",
                return_value=sentinel,
            ) as create,
        ):
            result = get_llm("configured-model")

        self.assertIs(result, sentinel)
        self.assertTrue(create.call_args.kwargs["thinking_mode"])

    def test_explicit_mode_overrides_database_configuration(self) -> None:
        with (
            patch(
                "app.infra.llm.factory.get_model_manager",
                return_value=_Manager(thinking=True),
            ),
            patch(
                "app.infra.llm.factory.create_llm_from_config",
                return_value=object(),
            ) as create,
        ):
            get_llm("configured-model", thinking_mode=False)

        self.assertFalse(create.call_args.kwargs["thinking_mode"])


if __name__ == "__main__":
    unittest.main()
