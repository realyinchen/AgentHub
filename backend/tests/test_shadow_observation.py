from __future__ import annotations

import json
import unittest
from uuid import uuid4

from app.schemas.chat import UserInput
from app.services.agent_core.certification_contracts import (
    AgentModeAdmission,
)
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
    ShadowEvaluationRecord,
)
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.gateway import AgentControllerAttempt
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ControllerModelRequest,
    ConversationContextTurn,
)
from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
)
from app.services.agent_core.shadow_evidence import (
    build_shadow_run_evidence,
)
from app.services.agent_core.shadow_observation_projector import (
    ShadowObservationProjector,
)
from app.services.agent_core.shadow_observation import (
    ShadowObservationWorker,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_audit_request_id,
    shadow_observation_key,
)


class ShadowObservationTests(unittest.TestCase):
    def test_violation_categories_are_allowlisted_not_raw_errors(
        self,
    ) -> None:
        command = ShadowControllerCommand(
            user_input=UserInput(
                content="remember this",
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="shadow-violation",
                model_uuid=str(uuid4()),
            ),
            model_name="fixture",
            journal_sequence_watermark=1,
            controller_fingerprint="c" * 64,
            source_commit_sha="c" * 40,
        )
        attempt = AgentControllerAttempt(
            mode="shadow",
            status="shadow_invalid",
            shadow=ShadowEvaluationRecord(
                valid=False,
                checks=[
                    {
                        "capability": "remember_memory",
                        "status": "clarification_required",
                    }
                ],
                errors=[
                    "model proposal contains system-owned fields: user_id",
                    "side-effect success claims require a runtime receipt",
                ],
            ),
        )

        observation = ShadowObservationProjector().project(
            command,
            attempt,
            latency_ms=1,
        )

        self.assertEqual(
            observation.violation_codes,
            [
                "memory_precommit_not_ready",
                "system_owned_field",
                "unreceipted_success_claim",
            ],
        )
        self.assertNotIn("user_id", json.dumps(observation.error_hashes))

    def test_observation_contains_hashes_not_raw_conversation_or_arguments(
        self,
    ) -> None:
        secret_text = "I am Ice Dew and token-secret-123"
        user_id = uuid4()
        thread_id = uuid4()
        model_id = uuid4()
        admission = AgentModeAdmission(
            admitted=True,
            certification_id=str(uuid4()),
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        )
        request = ControllerModelRequest(
            model_name="fixture",
            current_user_message=secret_text,
            admission=admission,
            context=ControllerContextSnapshot(
                conversation=[
                    ConversationContextTurn(
                        role="user",
                        content=secret_text,
                    )
                ]
            ),
        )
        output = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="provider-call-secret",
                    name="search_memory",
                    arguments={"query": secret_text, "limit": 5},
                )
            ],
        )
        evidence = build_shadow_run_evidence(request, output)
        attempt = AgentControllerAttempt(
            mode="shadow",
            status="shadow_valid",
            admission=admission,
            shadow=ShadowEvaluationRecord(
                valid=True,
                would_execute=True,
                checks=[
                    {
                        "capability": "search_memory",
                        "status": "ready",
                    }
                ],
            ),
            shadow_evidence=evidence,
        )
        command = ShadowControllerCommand(
            user_input=UserInput(
                content=secret_text,
                user_id=user_id,
                thread_id=thread_id,
                request_id="shadow-observation-1",
                model_uuid=str(model_id),
            ),
            model_name="fixture",
            journal_sequence_watermark=1,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        )

        observation = ShadowObservationProjector().project(
            command,
            attempt,
            latency_ms=17,
        )
        serialized = json.dumps(
            observation.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )

        self.assertNotIn(secret_text, serialized)
        self.assertNotIn("provider-call-secret", serialized)
        self.assertEqual(observation.user_id, user_id)
        self.assertEqual(observation.thread_id, thread_id)
        self.assertEqual(observation.model_id, model_id)
        self.assertEqual(
            observation.journal_sequence_watermark,
            1,
        )
        self.assertEqual(observation.output_mode, "capability_proposals")
        self.assertEqual(
            observation.proposal_summary["capabilities"][0]["name"],
            "search_memory",
        )
        self.assertEqual(
            len(
                observation.proposal_summary[
                    "capabilities"
                ][0]["argument_hash"]
            ),
            64,
        )
        self.assertEqual(len(observation.observation_key), 64)
        mismatched_attempt = attempt.model_copy(
            update={
                "admission": admission.model_copy(
                    update={"source_commit_sha": "d" * 40}
                )
            }
        )
        with self.assertRaisesRegex(
            ValueError,
            "admission release differs from enrollment",
        ):
            ShadowObservationProjector().project(
                command,
                mismatched_attempt,
                latency_ms=17,
            )

    def test_same_request_and_controller_contract_is_idempotent(self) -> None:
        command = ShadowControllerCommand(
            user_input=UserInput(
                content="hello",
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="shadow-replay",
                model_uuid=str(uuid4()),
            ),
            model_name="fixture",
            journal_sequence_watermark=1,
            controller_fingerprint="c" * 64,
            source_commit_sha="c" * 40,
        )
        attempt = AgentControllerAttempt(
            mode="shadow",
            status="denied",
            reason="certification_missing",
        )

        first = ShadowObservationProjector().project(
            command,
            attempt,
            latency_ms=1,
        )
        second = ShadowObservationProjector().project(
            command,
            attempt,
            latency_ms=99,
        )

        self.assertEqual(
            first.observation_key,
            second.observation_key,
        )
        self.assertEqual(
            first.observation_key,
            shadow_observation_key(
                command,
                first.controller_fingerprint,
            ),
        )
        audit_id = shadow_audit_request_id(
            first.observation_key
        )
        self.assertNotEqual(
            audit_id,
            command.user_input.request_id,
        )
        self.assertLessEqual(len(audit_id), 128)
        self.assertNotIn(
            command.user_input.content,
            audit_id,
        )


class ShadowObservationWorkerTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_rejects_other_release_before_database_access(
        self,
    ) -> None:
        database_accesses = 0

        def database_provider():
            nonlocal database_accesses
            database_accesses += 1
            raise AssertionError("database must not be accessed")

        worker = ShadowObservationWorker(
            expected_source_commit_sha="a" * 40,
            database_provider=database_provider,
        )
        command = ShadowControllerCommand(
            user_input=UserInput(
                content="hello",
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="shadow-other-release",
                model_uuid=str(uuid4()),
            ),
            model_name="fixture",
            journal_sequence_watermark=1,
            controller_fingerprint=current_controller_fingerprint(),
            source_commit_sha="b" * 40,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "different source release",
        ):
            await worker.handle(command)

        self.assertEqual(database_accesses, 0)


if __name__ == "__main__":
    unittest.main()
