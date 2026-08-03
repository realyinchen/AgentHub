from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.infra.config import Settings
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.controller_client import controller_tool_schemas
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
)
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.agent_runtime.legacy_compatibility import (
    LegacyRoutingRuntimeCompatibility,
)
from app.services.agent_runtime.legacy_availability import (
    LegacyRuntimeAvailability,
)
from app.services.conversation.authoritative_reader import (
    JournalConversationReader,
)
from app.services.conversation.contracts import ConversationReadRequest
from app.services.conversation.journal_contracts import (
    ConversationJournalEvent,
    ConversationJournalPage,
)
from app.services.conversation.legacy_backfill_policy import (
    LegacyHistoryBackfillPolicy,
)


USER_ID = uuid4()
THREAD_ID = uuid4()


def _registry(
    core: CoreCapabilityAvailability,
) -> CapabilityRegistry:
    return CapabilityRegistry(core_availability=core)


class CoreCapabilityMatrixTests(unittest.TestCase):
    def test_production_defaults_fail_closed(self) -> None:
        fields = Settings.model_fields
        self.assertIs(fields["AGENT_CAPABILITY_CONVERSATION_V1"].default, False)
        self.assertIs(fields["AGENT_CAPABILITY_MEMORY_READ_V1"].default, False)
        self.assertIs(fields["AGENT_CAPABILITY_MEMORY_WRITE_V1"].default, False)
        self.assertIs(fields["AGENT_CAPABILITY_TASK_V1"].default, False)

        registry = _registry(CoreCapabilityAvailability())
        self.assertEqual(registry.enabled_names, ())
        schemas = controller_tool_schemas(registry)
        names = [item["function"]["name"] for item in schemas]
        self.assertEqual(names, ["request_clarification"])

    def test_read_write_and_task_switches_are_independent(self) -> None:
        registry = _registry(
            CoreCapabilityAvailability(
                conversation_read=True,
                memory_read=True,
            )
        )
        self.assertEqual(
            registry.enabled_names,
            ("conversation_read", "search_memory"),
        )
        self.assertFalse(registry.task_planning_enabled)
        names = {item["function"]["name"] for item in controller_tool_schemas(registry)}
        self.assertEqual(
            names,
            {
                "conversation_read",
                "search_memory",
                "request_clarification",
            },
        )
        self.assertNotIn("save_memory", names)
        self.assertNotIn("update_memory", names)


class _CountingRuntime(SystemRuntime):
    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        legacy_memory_write: bool = True,
    ) -> None:
        super().__init__(
            capability_registry=registry,
            compatibility=LegacyRoutingRuntimeCompatibility(
                core_availability=registry.core_availability,
                availability=LegacyRuntimeAvailability(
                    memory_write_compat=legacy_memory_write
                ),
            ),
        )
        self.calls = 0

    async def _execute_action(self, action, *, context, user_input, previous):
        self.calls += 1
        return ActionReceipt(
            action_id=action.action_id,
            capability=action.capability,
            operation=action.operation,
            status="completed",
            output={"answer": "trusted"},
            admitted=True,
        )


class RuntimeAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def _plan(self) -> ActionPlan:
        return ActionPlan(
            source="controller_proposal",
            route_type="fast_path",
            intent="conversation_recall",
            goal="What did I say?",
            actions=[
                PlannedAction(
                    action_id="read",
                    capability="conversation",
                    operation="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                    },
                )
            ],
        )

    def _context(self) -> ExecutionContext:
        return ExecutionContext(
            user_id=uuid4(),
            thread_id=uuid4(),
            request_id="r6-runtime",
        )

    async def test_manual_plan_cannot_bypass_disabled_projection(self) -> None:
        runtime = _CountingRuntime(_registry(CoreCapabilityAvailability()))
        receipt = await runtime.execute(
            self._plan(),
            context=self._context(),
        )
        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(
            receipt.actions[0].error,
            "core_capability_conversation_read_disabled",
        )

    async def test_same_matrix_authorizes_projection_and_execution(self) -> None:
        runtime = _CountingRuntime(
            _registry(CoreCapabilityAvailability(conversation_read=True))
        )
        receipt = await runtime.execute(
            self._plan(),
            context=self._context(),
        )
        self.assertEqual(receipt.status, "completed")
        self.assertEqual(runtime.calls, 1)

    async def test_controller_plan_cannot_reach_legacy_context_reader(self) -> None:
        plan = self._plan().model_copy(
            update={
                "actions": [
                    PlannedAction(
                        action_id="legacy-read",
                        capability="memory",
                        operation="search_memory",
                        arguments={"query": "name"},
                    )
                ]
            }
        )
        runtime = _CountingRuntime(_registry(CoreCapabilityAvailability()))
        receipt = await runtime.execute(plan, context=self._context())
        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(
            receipt.actions[0].error,
            "runtime_operation_not_registered",
        )

    async def test_r6_memory_write_disables_legacy_writer(self) -> None:
        plan = ActionPlan(
            source="routing_decision",
            route_type="fast_path",
            intent="memory_update",
            goal="remember",
            actions=[
                PlannedAction(
                    action_id="legacy-write",
                    capability="memory",
                    operation="process_memory_write_request",
                )
            ],
        )
        runtime = _CountingRuntime(
            _registry(CoreCapabilityAvailability(memory_write=True))
        )
        receipt = await runtime.execute(plan, context=self._context())
        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(
            receipt.actions[0].error,
            "legacy_memory_write_disabled_for_r6",
        )

    async def test_rollback_can_leave_legacy_writer_permanently_off(self) -> None:
        plan = ActionPlan(
            source="routing_decision",
            route_type="fast_path",
            intent="memory_update",
            goal="remember",
            actions=[
                PlannedAction(
                    action_id="legacy-write",
                    capability="memory",
                    operation="process_memory_write_request",
                )
            ],
        )
        runtime = _CountingRuntime(
            _registry(CoreCapabilityAvailability()),
            legacy_memory_write=False,
        )
        receipt = await runtime.execute(plan, context=self._context())
        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(runtime.calls, 0)
        self.assertEqual(
            receipt.actions[0].error,
            "legacy_memory_write_disabled_for_r6",
        )


class _JournalRepository:
    def __init__(self, events: list[ConversationJournalEvent]) -> None:
        self.events = events
        self.exclude_request_id = None

    async def list_events(
        self,
        _db,
        *,
        after_sequence,
        exclude_request_id,
        **_kwargs,
    ) -> ConversationJournalPage:
        self.exclude_request_id = exclude_request_id
        events = [
            event
            for event in self.events
            if event.sequence_no > after_sequence
            and event.request_id != exclude_request_id
        ]
        return ConversationJournalPage(events=events, has_more=False)


def _event(
    *,
    sequence: int,
    request_id: str,
    role: str,
    content: str,
    exchange_id,
) -> ConversationJournalEvent:
    return ConversationJournalEvent(
        id=uuid4(),
        user_id=USER_ID,
        thread_id=THREAD_ID,
        request_id=request_id,
        exchange_id=exchange_id,
        sequence_no=sequence,
        event_type=("user_message" if role == "user" else "assistant_published"),
        role=role,
        content=content,
        created_at=datetime.now(timezone.utc),
    )


class JournalAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_read_uses_only_prior_journal_events(self) -> None:
        prior_exchange = uuid4()
        current_exchange = uuid4()
        repository = _JournalRepository(
            [
                _event(
                    sequence=1,
                    request_id="prior",
                    role="user",
                    content="I am Binglu.",
                    exchange_id=prior_exchange,
                ),
                _event(
                    sequence=2,
                    request_id="prior",
                    role="assistant",
                    content="Hello, Binglu.",
                    exchange_id=prior_exchange,
                ),
                _event(
                    sequence=3,
                    request_id="current",
                    role="user",
                    content="What did I say?",
                    exchange_id=current_exchange,
                ),
            ]
        )
        result = await JournalConversationReader(repository).read(
            object(),
            user_id=USER_ID,
            thread_id=THREAD_ID,
            exclude_request_id="current",
            request=ConversationReadRequest(
                target="exchange",
                selection="latest",
            ),
        )
        self.assertEqual(repository.exclude_request_id, "current")
        self.assertEqual(
            [turn.content for turn in result.turns],
            ["I am Binglu.", "Hello, Binglu."],
        )

    def test_new_runtime_has_no_metadata_history_fallback(self) -> None:
        from app.services.agent_runtime import runtime
        from app.services.conversation import legacy_history_reader
        from app.api.v1.chat import history

        source = inspect.getsource(runtime._read_conversation)
        self.assertNotIn("_conversation_window", source)
        self.assertNotIn("conversation_turns", source)
        self.assertNotIn("get_agent", inspect.getsource(history))
        self.assertIn(
            "get_agent",
            inspect.getsource(legacy_history_reader),
        )


class LegacyBackfillPolicyTests(unittest.TestCase):
    def test_compatibility_bridge_is_explicit_and_audited(self) -> None:
        disabled = LegacyHistoryBackfillPolicy(enabled=False)
        self.assertFalse(
            disabled.authorize(
                user_id=uuid4(),
                thread_id=uuid4(),
            )
        )
        enabled = LegacyHistoryBackfillPolicy(enabled=True)
        with self.assertLogs(
            "app.services.conversation.legacy_backfill_policy",
            level="WARNING",
        ) as captured:
            allowed = enabled.authorize(
                user_id=uuid4(),
                thread_id=uuid4(),
            )
        self.assertTrue(allowed)
        self.assertIn("compatibility=read_only", captured.output[0])


if __name__ == "__main__":
    unittest.main()
