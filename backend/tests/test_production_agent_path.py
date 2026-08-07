"""Static guardrails for the production-only Agent Core boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_MODULES = (
    ROOT / "app/services/chat.py",
    ROOT / "app/services/streaming.py",
    ROOT / "app/services/agent_core/chat_entry.py",
    ROOT / "app/services/agent_core/gateway.py",
    ROOT / "app/services/agent_core/controller_client.py",
    ROOT / "app/services/agent_core/request_builder.py",
    ROOT / "app/services/conversation/summary_llm_provider.py",
    ROOT / "app/api/v1/models.py",
    ROOT / "app/main.py",
)

FORBIDDEN_RUNTIME_TOKENS = (
    "agent_certification",
    "certification_contracts",
    "get_agent_mode_admission",
    "prepare_shadow_enrollment",
    "AGENT_CONTROLLER_V1_MODE",
    "AGENT_RELEASE_COMMIT_SHA",
    "PlainChatClient",
    "run_plain",
)


def test_production_modules_do_not_depend_on_developer_validation() -> None:
    for path in PRODUCTION_MODULES:
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_RUNTIME_TOKENS:
            assert token not in source, f"{path}: forbidden runtime token {token}"


def test_production_chat_has_one_agent_entry_call() -> None:
    source = (ROOT / "app/services/chat.py").read_text(encoding="utf-8")
    assert "await self._agent_entry.run(" in source
    assert "run_plain" not in source
    assert "_evaluate_entry" not in source


def test_controller_request_has_no_runtime_admission_contract() -> None:
    source = (ROOT / "app/services/agent_core/prompt_contracts.py").read_text(
        encoding="utf-8"
    )
    request_source = source.split("class ControllerModelRequest", 1)[1]
    assert "admission" not in request_source
