from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.services.agent_core.contracts import ControllerOutput, ControllerToolCall
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_runtime.contracts import PlannedAction
from app.services.routing.contracts import ProposedAction
from app.services.routing.interaction_contracts import DecisionConstraint
from app.services.system_owned_fields import (
    ACTION_ARGUMENT_FORBIDDEN_FIELDS,
    MODEL_PROPOSAL_FORBIDDEN_FIELDS,
)
from app.services.tasks.contracts import TaskPlanDraft, TaskPlanStepDraft


class SystemOwnedFieldPolicyTests(unittest.TestCase):
    def test_required_security_fields_have_one_shared_policy(self) -> None:
        self.assertTrue(
            {
                "user_id",
                "thread_id",
                "request_id",
                "origin_request_id",
                "task_id",
                "plan_version_id",
                "action_id",
                "idempotency_key",
                "source_commit_sha",
                "schema_key",
                "memory_key",
            }.issubset(MODEL_PROPOSAL_FORBIDDEN_FIELDS)
        )
        self.assertNotIn("operation", ACTION_ARGUMENT_FORBIDDEN_FIELDS)

    def test_all_model_and_plan_entries_reject_same_nested_fields(self) -> None:
        controller = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="read",
                    name="conversation_read",
                    arguments={
                        "nested": [{"origin_request_id": "forbidden"}]
                    },
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "origin_request_id"):
            ProposalValidator().validate(controller)
        release_identity = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="unsafe-release",
                    name="conversation_read",
                    arguments={
                        "nested": [
                            {"source_commit_sha": "a" * 40}
                        ]
                    },
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "source_commit_sha"):
            ProposalValidator().validate(release_identity)

        with self.assertRaisesRegex(ValidationError, "origin_request_id"):
            TaskPlanDraft(
                goal="读取",
                steps=[
                    TaskPlanStepDraft(
                        step_key="read",
                        title="读取",
                        capability="conversation_read",
                        arguments={
                            "nested": [{"origin_request_id": "forbidden"}]
                        },
                    )
                ],
            )

        with self.assertRaisesRegex(ValidationError, "origin_request_id"):
            PlannedAction(
                capability="conversation",
                operation="conversation_read",
                arguments={
                    "nested": [{"origin_request_id": "forbidden"}]
                },
            )

        with self.assertRaisesRegex(ValidationError, "origin_request_id"):
            ProposedAction(
                action_key="read",
                capability="conversation",
                operation="conversation_read",
                arguments={
                    "nested": [{"origin_request_id": "forbidden"}]
                },
            )

        with self.assertRaisesRegex(ValidationError, "origin_request_id"):
            DecisionConstraint(
                field="genre",
                value={
                    "nested": [{"origin_request_id": "forbidden"}]
                },
            )

    def test_model_control_field_is_scoped_not_treated_as_identity(self) -> None:
        controller = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="read",
                    name="conversation_read",
                    arguments={"nested": {"operation": "forbidden"}},
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "operation"):
            ProposalValidator().validate(controller)

        # A trusted internal typed request may carry its own business operation
        # during migration; identity and secret fields remain forbidden.
        action = PlannedAction(
            capability="memory",
            operation="process_memory_write_request",
            arguments={"request": {"operation": "create"}},
        )
        routed = ProposedAction(
            action_key="capture",
            capability="memory",
            operation="process_memory_write_request",
            arguments={"request": {"operation": "create"}},
        )
        self.assertEqual(action.arguments["request"]["operation"], "create")
        self.assertEqual(routed.arguments["request"]["operation"], "create")


if __name__ == "__main__":
    unittest.main()
