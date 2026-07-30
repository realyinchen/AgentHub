from __future__ import annotations

import unittest
from uuid import uuid4

from app.schemas.chat import UserInput
from app.schemas.chat import ChatMessage
from app.services.agent_core.chat_entry import AgentChatEntry
from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.contracts import (
    AgentCoreTurnResult,
    ControllerOutput,
    ShadowEvaluationRecord,
)
from app.services.agent_core.gateway import (
    AgentControllerAttempt,
    AgentControllerGateway,
)
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ControllerModelRequest,
)
from app.services.agent_core.shadow_dispatcher import (
    ShadowDispatchReceipt,
)
from app.services.conversation.journal_contracts import (
    ConversationShadowEnrollment,
)


def _input(*, model_uuid: str | None = None) -> UserInput:
    return UserInput(
        content="What did I just say?",
        user_id=uuid4(),
        thread_id=uuid4(),
        request_id="gateway-request",
        model_uuid=model_uuid,
    )


def _admission(*, admitted: bool = True) -> AgentModeAdmission:
    return AgentModeAdmission(
        admitted=admitted,
        certification_id="cert-r3" if admitted else None,
        reason=None if admitted else "certification_missing",
        configuration_fingerprint="b" * 64,
        controller_fingerprint="c" * 64,
        source_commit_sha="d" * 40,
    )


class _RequestBuilder:
    async def build(
        self,
        db,
        *,
        user_input,
        model_name,
        admission,
        journal_sequence_watermark=None,
    ):
        return ControllerModelRequest(
            model_name=model_name,
            current_user_message=user_input.content,
            context=ControllerContextSnapshot(),
            admission=admission,
        )


class _Controller:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, request):
        self.calls += 1
        return ControllerOutput(
            mode="direct_answer",
            text="You asked what you just said.",
        )


class AgentControllerGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_mode_makes_no_admission_or_model_call(self) -> None:
        admission_calls = 0
        controller = _Controller()

        async def admission_loader(db, model_id):
            nonlocal admission_calls
            admission_calls += 1
            return _admission()

        result = await AgentControllerGateway(
            controller=controller,  # type: ignore[arg-type]
            request_builder=_RequestBuilder(),  # type: ignore[arg-type]
            admission_loader=admission_loader,
        ).evaluate(
            object(),  # type: ignore[arg-type]
            user_input=_input(model_uuid=str(uuid4())),
            model_name="fixture",
            mode="off",
        )

        self.assertEqual(result.status, "off")
        self.assertEqual(admission_calls, 0)
        self.assertEqual(controller.calls, 0)

    async def test_denied_admission_never_calls_controller(self) -> None:
        controller = _Controller()

        async def admission_loader(db, model_id):
            return _admission(admitted=False)

        result = await AgentControllerGateway(
            controller=controller,  # type: ignore[arg-type]
            request_builder=_RequestBuilder(),  # type: ignore[arg-type]
            admission_loader=admission_loader,
        ).evaluate(
            object(),  # type: ignore[arg-type]
            user_input=_input(model_uuid=str(uuid4())),
            model_name="fixture",
            mode="live",
        )

        self.assertEqual(result.status, "denied")
        self.assertEqual(controller.calls, 0)

    async def test_shadow_runs_dry_harness_only(self) -> None:
        controller = _Controller()

        async def admission_loader(db, model_id):
            return _admission()

        result = await AgentControllerGateway(
            controller=controller,  # type: ignore[arg-type]
            request_builder=_RequestBuilder(),  # type: ignore[arg-type]
            admission_loader=admission_loader,
        ).evaluate(
            object(),  # type: ignore[arg-type]
            user_input=_input(model_uuid=str(uuid4())),
            model_name="fixture",
            mode="shadow",
        )

        self.assertEqual(result.status, "shadow_valid")
        self.assertEqual(controller.calls, 1)
        self.assertIsNotNone(result.shadow)
        self.assertFalse(result.shadow.would_execute)

    async def test_live_direct_answer_uses_one_controller_round(self) -> None:
        controller = _Controller()

        async def admission_loader(db, model_id):
            return _admission()

        result = await AgentControllerGateway(
            controller=controller,  # type: ignore[arg-type]
            request_builder=_RequestBuilder(),  # type: ignore[arg-type]
            admission_loader=admission_loader,
        ).evaluate(
            object(),  # type: ignore[arg-type]
            user_input=_input(model_uuid=str(uuid4())),
            model_name="fixture",
            mode="live",
        )

        self.assertEqual(result.status, "live_completed")
        self.assertEqual(controller.calls, 1)
        self.assertEqual(len(result.turn.rounds), 1)
        self.assertFalse(result.turn.final_answer.receipt_backed)

    async def test_shadow_uses_internal_audit_request_id_only_for_runtime_context(
        self,
    ) -> None:
        class _CapturingHarness:
            def __init__(self) -> None:
                self.context = None

            async def run(
                self,
                output,
                *,
                goal,
                context,
                user_input,
                execution_mode,
            ):
                self.context = context
                return AgentCoreTurnResult(
                    execution_mode="shadow",
                    output=output,
                    shadow=ShadowEvaluationRecord(valid=True),
                )

        async def admission_loader(db, model_id):
            return _admission()

        harness = _CapturingHarness()
        original = _input(model_uuid=str(uuid4()))
        audit_request_id = "shadow-audit:" + "d" * 64
        result = await AgentControllerGateway(
            controller=_Controller(),  # type: ignore[arg-type]
            harness=harness,  # type: ignore[arg-type]
            request_builder=_RequestBuilder(),  # type: ignore[arg-type]
            admission_loader=admission_loader,
        ).evaluate(
            object(),  # type: ignore[arg-type]
            user_input=original,
            model_name="fixture",
            mode="shadow",
            execution_request_id=audit_request_id,
        )

        self.assertEqual(result.status, "shadow_valid")
        self.assertEqual(
            harness.context.request_id,
            audit_request_id,
        )
        self.assertNotEqual(
            harness.context.request_id,
            original.request_id,
        )


class AgentChatEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_denied_and_failed_use_plain_chat_not_legacy_path(
        self,
    ) -> None:
        attempts = (
            AgentControllerAttempt(
                mode="live",
                status="denied",
                reason="certification_missing",
            ),
            AgentControllerAttempt(
                mode="live",
                status="failed",
                reason="controller_unavailable:RuntimeError",
            ),
        )

        class _Gateway:
            def __init__(self, attempt) -> None:
                self._attempt = attempt

            async def evaluate(
                self,
                db,
                *,
                user_input,
                model_name,
                mode=None,
            ):
                return self._attempt

        class _Plain:
            def __init__(self) -> None:
                self.calls = 0

            async def answer(self, db, *, user_input, model_name):
                self.calls += 1
                return ChatMessage(
                    type="ai",
                    content="Plain chat answer",
                    request_id=user_input.request_id,
                )

        for attempt in attempts:
            with self.subTest(status=attempt.status):
                plain = _Plain()
                result = await AgentChatEntry(
                    gateway=_Gateway(attempt),  # type: ignore[arg-type]
                    plain_chat=plain,  # type: ignore[arg-type]
                ).run(
                    object(),  # type: ignore[arg-type]
                    user_input=_input(model_uuid=str(uuid4())),
                    model_name="fixture",
                    mode="live",
                )

                self.assertTrue(result.handled)
                self.assertEqual(result.message.content, "Plain chat answer")
                self.assertEqual(plain.calls, 1)

    async def test_shadow_only_enqueues_and_never_calls_gateway_or_plain(
        self,
    ) -> None:
        dispatch_receipts = (
            ShadowDispatchReceipt(status="queued"),
            ShadowDispatchReceipt(
                status="dropped",
                reason="queue_full",
            ),
        )

        class _ForbiddenGateway:
            async def evaluate(self, *args, **kwargs):
                raise AssertionError("Shadow entry awaited Controller Gateway")

        class _ForbiddenPlain:
            async def answer(self, *args, **kwargs):
                raise AssertionError("Shadow entry called plain chat")

        class _Dispatcher:
            def __init__(self, receipt) -> None:
                self.receipt = receipt
                self.commands = []

            def submit(self, command):
                self.commands.append(command)
                return self.receipt

        for receipt in dispatch_receipts:
            with self.subTest(status=receipt.status):
                dispatcher = _Dispatcher(receipt)
                model_id = uuid4()
                user_input = _input(model_uuid=str(model_id))
                enrollment = ConversationShadowEnrollment(
                    source_commit_sha="d" * 40,
                    controller_fingerprint="c" * 64,
                    prompt_version="controller-prompt-v1",
                    model_id=model_id,
                    model_name="fixture",
                    timezone="Asia/Shanghai",
                )
                result = await AgentChatEntry(
                    gateway=_ForbiddenGateway(),  # type: ignore[arg-type]
                    plain_chat=_ForbiddenPlain(),  # type: ignore[arg-type]
                    shadow_dispatcher=dispatcher,  # type: ignore[arg-type]
                ).run(
                    object(),  # type: ignore[arg-type]
                    user_input=user_input,
                    model_name="fixture",
                    mode="shadow",
                    journal_sequence_watermark=1,
                    shadow_enrollment=enrollment,
                )

                self.assertFalse(result.handled)
                self.assertEqual(
                    result.attempt.status,
                    (
                        "shadow_queued"
                        if receipt.status == "queued"
                        else "shadow_dropped"
                    ),
                )
                self.assertEqual(len(dispatcher.commands), 1)
                self.assertEqual(
                    dispatcher.commands[0].source_commit_sha,
                    "d" * 40,
                )


if __name__ == "__main__":
    unittest.main()
