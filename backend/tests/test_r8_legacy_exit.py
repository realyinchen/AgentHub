from __future__ import annotations

import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.infra.config import Settings
from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_core.chat_entry import AgentChatEntry
from app.services.agent_core.legacy_chat_runtime import LegacyChatRuntimeBridge
from app.services.agent_runtime.compatibility import RuntimeCompatibilityPort
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ExecutionContext,
    PlannedAction,
)
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.agent_runtime.legacy_compatibility import (
    LegacyRoutingRuntimeCompatibility,
)
from scripts.verify_release_gates import REQUIRED_GATES, build_release_report
from scripts.verify_r8_legacy_exit import verify_structure


def _input() -> UserInput:
    return UserInput(
        user_id=uuid4(),
        thread_id=uuid4(),
        request_id="r8-test",
        content="hello",
    )


def _legacy_plan() -> ActionPlan:
    return ActionPlan(
        source="routing_decision",
        route_type="fast_path",
        intent="legacy_probe",
        goal="legacy probe",
        actions=[
            PlannedAction(
                action_id="legacy",
                capability="legacy",
                operation="legacy_probe",
            )
        ],
    )


class _FixtureCompatibility(RuntimeCompatibilityPort):
    def __init__(self) -> None:
        self.calls = 0

    def handles(self, plan, action):
        return plan.source == "routing_decision"

    def admit(self, plan, action):
        return True, "fixture_compatibility"

    async def execute(
        self,
        plan,
        action,
        *,
        context,
        user_input,
        previous,
    ):
        self.calls += 1
        return {"status": "completed", "source": "fixture"}

    def injected_fields(self, action, context):
        return ()


class RuntimeIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_runtime_fails_closed_for_legacy_plan(self) -> None:
        receipt = await SystemRuntime().execute(
            _legacy_plan(),
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r8-default-runtime",
            ),
        )
        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(
            receipt.actions[0].error,
            "legacy_runtime_compatibility_disabled",
        )

    async def test_explicit_port_is_required_for_legacy_execution(self) -> None:
        compatibility = _FixtureCompatibility()
        receipt = await SystemRuntime(compatibility=compatibility).execute(
            _legacy_plan(),
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r8-explicit-runtime",
            ),
        )
        self.assertEqual(receipt.status, "completed")
        self.assertEqual(compatibility.calls, 1)

    async def test_legacy_adapter_rejects_unregistered_operations(self) -> None:
        receipt = await SystemRuntime(
            compatibility=LegacyRoutingRuntimeCompatibility(),
        ).execute(
            _legacy_plan(),
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r8-legacy-allowlist",
            ),
        )
        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(
            receipt.actions[0].error,
            "legacy_operation_not_registered",
        )


class LegacyBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_bridge_does_not_load_old_runtime(self) -> None:
        calls = 0

        async def forbidden_factory(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("disabled bridge loaded the old runtime")

        result = await LegacyChatRuntimeBridge(
            enabled=False,
            turn_factory=forbidden_factory,
        ).prepare(_input())
        self.assertEqual(result.status, "disabled")
        self.assertIsNone(result.turn)
        self.assertEqual(calls, 0)

    async def test_plain_entry_has_no_runtime_or_tool_execution(self) -> None:
        class _ForbiddenGateway:
            async def evaluate(self, *args, **kwargs):
                raise AssertionError("plain entry called Controller")

        class _Plain:
            calls = 0

            async def answer(self, db, *, user_input, model_name):
                self.calls += 1
                return ChatMessage(
                    type="ai",
                    content="plain",
                    request_id=user_input.request_id,
                )

        plain = _Plain()
        result = await AgentChatEntry(
            gateway=_ForbiddenGateway(),  # type: ignore[arg-type]
            plain_chat=plain,  # type: ignore[arg-type]
        ).run_plain(
            object(),  # type: ignore[arg-type]
            user_input=_input(),
            model_name="fixture",
        )
        self.assertTrue(result.handled)
        self.assertEqual(result.message.content, "plain")
        self.assertEqual(plain.calls, 1)


class StaticLegacyExitTests(unittest.TestCase):
    def test_candidate_defaults_remain_explicit_and_release_blocking(self) -> None:
        fields = Settings.model_fields
        self.assertIs(fields["AGENT_LEGACY_RUNTIME_FALLBACK"].default, True)
        self.assertIs(fields["AGENT_LEGACY_MEMORY_WRITE_COMPAT"].default, True)

    def test_shadow_and_memory_write_cutovers_are_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                AGENT_CONTROLLER_V1_MODE="shadow",
                AGENT_LEGACY_RUNTIME_FALLBACK=False,
            )
        with self.assertRaises(ValidationError):
            Settings(
                AGENT_CAPABILITY_MEMORY_WRITE_V1=True,
                AGENT_LEGACY_MEMORY_WRITE_COMPAT=True,
            )

    def test_production_entry_has_one_quarantine_boundary(self) -> None:
        result = verify_structure()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["bridge_count"], 1)
        self.assertEqual(result["system_runtime_retired_operations"], 0)

    def test_release_aggregator_cannot_pass_without_every_gate(self) -> None:
        import subprocess
        from pathlib import Path

        workspace = Path(__file__).resolve().parents[2]
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        report = build_release_report(
            expected_commit_sha=commit_sha,
            task_document=workspace / "local-dev/AGENT_CORE_ARCHITECTURE.md",
            evidence_dir=workspace / "local-dev/nonexistent-release-evidence",
        )
        self.assertNotEqual(report["overall_status"], "release_ready")
        self.assertEqual(len(report["gates"]), len(REQUIRED_GATES))
        self.assertTrue(all(item["status"] != "passed" for item in report["gates"]))


if __name__ == "__main__":
    unittest.main()
