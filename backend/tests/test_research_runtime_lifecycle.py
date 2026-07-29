from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
    PlanReceipt,
)
from app.services.research.runtime_lifecycle import (
    close_interrupted_research_run,
)


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def finish_research(self, **kwargs):
        self.calls.append(kwargs)
        return {}


def _plan() -> ActionPlan:
    start = PlannedAction(
        action_id="start",
        capability="research",
        operation="start_research",
    )
    publish = PlannedAction(
        action_id="publish",
        capability="research",
        operation="publish_research_answer",
        depends_on=["start"],
    )
    return ActionPlan(
        plan_id="plan-test",
        source="routing_decision",
        route_type="slow_path",
        intent="deep_research",
        goal="research",
        response_mode="receipt",
        actions=[start, publish],
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        user_id=uuid4(),
        request_id="request-test",
    )


class ResearchRuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_run_is_closed_as_failed(self) -> None:
        run_id = uuid4()
        receipt = PlanReceipt(
            plan_id="plan-test",
            request_id="request-test",
            route_type="slow_path",
            intent="deep_research",
            status="partial",
            actions=[
                ActionReceipt(
                    action_id="start",
                    capability="research",
                    operation="start_research",
                    status="completed",
                    output={"run": {"id": str(run_id)}},
                ),
                ActionReceipt(
                    action_id="publish",
                    capability="research",
                    operation="publish_research_answer",
                    status="skipped",
                ),
            ],
        )
        orchestrator = _FakeOrchestrator()
        with patch(
            "app.services.research.orchestrator.get_research_orchestrator",
            return_value=orchestrator,
        ):
            await close_interrupted_research_run(
                plan=_plan(),
                receipt=receipt,
                context=_context(),
            )
        self.assertEqual(len(orchestrator.calls), 1)
        self.assertEqual(orchestrator.calls[0]["run_id"], run_id)
        self.assertEqual(orchestrator.calls[0]["status"], "failed")
        self.assertTrue(orchestrator.calls[0]["metadata"]["terminal_guard"])

    async def test_completed_publication_does_not_finish_twice(self) -> None:
        receipt = PlanReceipt(
            plan_id="plan-test",
            request_id="request-test",
            route_type="slow_path",
            intent="deep_research",
            status="completed",
            actions=[
                ActionReceipt(
                    action_id="start",
                    capability="research",
                    operation="start_research",
                    status="completed",
                    output={"run": {"id": str(uuid4())}},
                ),
                ActionReceipt(
                    action_id="publish",
                    capability="research",
                    operation="publish_research_answer",
                    status="completed",
                    output={"answer": "done"},
                ),
            ],
        )
        orchestrator = _FakeOrchestrator()
        with patch(
            "app.services.research.orchestrator.get_research_orchestrator",
            return_value=orchestrator,
        ):
            await close_interrupted_research_run(
                plan=_plan(),
                receipt=receipt,
                context=_context(),
            )
        self.assertEqual(orchestrator.calls, [])


if __name__ == "__main__":
    unittest.main()
