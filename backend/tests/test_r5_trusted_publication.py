from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from app.schemas.chat import UserInput
from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.contracts import (
    CapabilityProposalBatch,
    ControllerOutput,
    ValidatedCapabilityProposal,
)
from app.services.agent_core.publication.commit import TurnPublicationCommitter
from app.services.agent_core.publication.contracts import (
    CommittedPublication,
    ReceiptEvidenceBundle,
)
from app.services.agent_core.publication.graph import (
    build_turn_execution_graph,
    project_public_execution_graph,
)
from app.services.agent_core.publication.service import TrustedPublisher
from app.services.agent_core.publication.stream import TrustedStreamSequencer
from app.services.agent_core.trusted_stream import TrustedControllerStream
from app.services.agent_core.receipt_projector import ReceiptContextProjector
from app.services.agent_core.turn_contracts import (
    ControllerRoundReceipt,
    TurnReceipt,
)
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    PlanReceipt,
    PlannedAction,
)
from app.services.agent_runtime.execution_graph import build_execution_graph
from app.services.conversation.journal_contracts import (
    ConversationJournalEvent,
)


def _plan(
    *,
    response_mode: str = "model",
    side_effect: bool = False,
) -> ActionPlan:
    return ActionPlan(
        plan_id="plan-r5",
        source="controller_proposal",
        route_type="slow_path",
        intent="r5",
        goal="形成可信回答",
        response_mode=response_mode,
        actions=[
            PlannedAction(
                action_id="internal-action-r5",
                capability="web",
                operation="web_search_v2",
                metadata={"side_effect": side_effect},
            )
        ],
    )


def _receipt(
    plan: ActionPlan,
    *,
    status: str = "completed",
    output: dict | None = None,
) -> PlanReceipt:
    return PlanReceipt(
        plan_id=plan.plan_id,
        request_id="request-r5",
        route_type=plan.route_type,
        intent=plan.intent,
        status=status,
        actions=[
            ActionReceipt(
                action_id=plan.actions[0].action_id,
                capability=plan.actions[0].capability,
                operation=plan.actions[0].operation,
                status=status,
                output=output,
                admitted=True,
            )
        ],
    )


def _web_output() -> dict:
    return {
        "result_mode": "web_evidence",
        "status": "ok",
        "query": "近期好评图书",
        "sources": [
            {
                "title": "来源一",
                "url": "https://example.com/one",
                "snippet": "第一条经过清洗的证据。",
                "published_date": "2026-07-01",
            },
            {
                "title": "来源二",
                "url": "https://example.com/two",
                "snippet": "第二条经过清洗的证据。",
                "published_date": "2026-07-02",
            },
            {
                "title": "来源三",
                "url": "https://example.com/three",
                "snippet": "第三条经过清洗的证据。",
                "published_date": "2026-07-03",
            },
        ],
        "provider_raw": "MUST_NOT_LEAK",
    }


class TrustedPublicationTests(unittest.TestCase):
    def test_direct_and_model_synthesis_are_distinct_modes(self) -> None:
        publisher = TrustedPublisher()
        direct = publisher.publish_direct(
            ControllerOutput(mode="direct_answer", text="你好。")
        )
        self.assertEqual(direct.publication_mode, "direct")
        self.assertFalse(direct.receipt_backed)

        plan = _plan()
        receipt = _receipt(plan, output=_web_output())
        synthesis = publisher.publish_synthesis(
            ControllerOutput(
                mode="direct_answer",
                text=(
                    "## 推荐结论\n\n"
                    "- [来源一](https://example.com/one)：第一条证据。\n"
                    "- [来源二](https://example.com/two)：第二条证据。"
                ),
            ),
            evidence=[ReceiptEvidenceBundle(plan=plan, receipt=receipt)],
        )
        self.assertEqual(synthesis.publication_mode, "model_synthesis")
        self.assertTrue(synthesis.receipt_backed)
        self.assertEqual(synthesis.receipt_refs, ["internal-action-r5"])

    def test_synthesis_rejects_internal_runtime_text(self) -> None:
        plan = _plan()
        receipt = _receipt(plan, output=_web_output())
        with self.assertRaisesRegex(ValueError, "technical"):
            TrustedPublisher().publish_synthesis(
                ControllerOutput(
                    mode="direct_answer",
                    text="dependency did not complete: internal-action-r5",
                ),
                evidence=[
                    ReceiptEvidenceBundle(plan=plan, receipt=receipt)
                ],
            )

    def test_synthesis_rejects_unstructured_external_dump(self) -> None:
        plan = _plan()
        receipt = _receipt(plan, output=_web_output())
        with self.assertRaisesRegex(ValueError, "structured"):
            TrustedPublisher().publish_synthesis(
                ControllerOutput(
                    mode="direct_answer",
                    text=(
                        "来源一 https://example.com/one 第一条证据 "
                        "来源二 https://example.com/two 第二条证据 "
                        "来源三 https://example.com/three 第三条证据 "
                    )
                    * 25,
                ),
                evidence=[
                    ReceiptEvidenceBundle(plan=plan, receipt=receipt)
                ],
            )

    def test_model_synthesis_cannot_cover_side_effect_plan(self) -> None:
        plan = _plan(side_effect=True)
        receipt = _receipt(plan, output=_web_output())
        with self.assertRaisesRegex(ValueError, "read-only"):
            TrustedPublisher().publish_synthesis(
                ControllerOutput(
                    mode="direct_answer",
                    text=(
                        "## 结果\n\n"
                        "- [来源一](https://example.com/one)：证据。"
                    ),
                ),
                evidence=[
                    ReceiptEvidenceBundle(plan=plan, receipt=receipt)
                ],
            )

    def test_waiting_receipt_only_publishes_clarification(self) -> None:
        plan = ActionPlan(
            plan_id="waiting-plan",
            source="controller_proposal",
            route_type="slow_path",
            intent="remember",
            goal="记住名字",
            response_mode="receipt",
            actions=[
                PlannedAction(
                    action_id="remember",
                    capability="memory",
                    operation="remember_memory_v2",
                    metadata={"side_effect": True},
                )
            ],
        )
        receipt = PlanReceipt(
            plan_id=plan.plan_id,
            request_id="request-r5",
            route_type=plan.route_type,
            intent=plan.intent,
            status="waiting",
            actions=[
                ActionReceipt(
                    action_id="remember",
                    capability="memory",
                    operation="remember_memory_v2",
                    status="waiting",
                    admitted=True,
                    output={
                        "status": "clarification_required",
                        "clarification_question": "你的名字是什么？",
                    },
                )
            ],
        )
        answer = TrustedPublisher().publish_deterministic(plan, receipt)
        self.assertEqual(answer.status, "clarification_required")
        self.assertEqual(answer.publication_mode, "deterministic_receipt")
        self.assertNotIn("完成", answer.content)

    def test_compiler_rejects_side_effect_mixed_with_model_synthesis(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "mixed with side effects"):
            WorkflowCompiler().compile(
                CapabilityProposalBatch(
                    proposals=[
                        ValidatedCapabilityProposal(
                            call_id="remember",
                            capability="remember_memory",
                            side_effect=True,
                        ),
                        ValidatedCapabilityProposal(
                            call_id="web",
                            capability="web_search",
                            side_effect=False,
                        ),
                    ]
                ),
                goal="记住名字并查资料",
            )


class TrustedEvidenceProjectionTests(unittest.TestCase):
    def test_external_receipt_is_typed_and_raw_fields_are_dropped(self) -> None:
        plan = _plan()
        receipt = _receipt(plan, output=_web_output())
        projected = ReceiptContextProjector().project(receipt)
        terminal = projected[-1]
        dumped = terminal.model_dump_json()
        self.assertEqual(terminal.result_mode, "web_evidence")
        self.assertEqual(len(terminal.sources), 3)
        self.assertNotIn("provider_raw", dumped)
        self.assertNotIn("MUST_NOT_LEAK", dumped)


class TrustedStreamProtocolTests(unittest.TestCase):
    def test_clarification_turn_projects_waiting_response(self) -> None:
        output = ControllerOutput(
            mode="request_clarification",
            text="请告诉我需要记住的名字。",
        )
        answer = TrustedPublisher().publish_direct(output)
        turn = TurnReceipt(
            status="clarification_required",
            request_id="request-waiting",
            rounds=[
                ControllerRoundReceipt(
                    round_no=1,
                    output=output,
                    answer=answer,
                )
            ],
            final_answer=answer,
        )

        internal = build_turn_execution_graph(
            turn,
            request_id=turn.request_id,
        )
        public = project_public_execution_graph(internal)

        self.assertEqual(internal.nodes[-1].status, "waiting")
        self.assertEqual(public.nodes[-1].status, "waiting")

    def test_waiting_receipt_remains_waiting_in_graphs(self) -> None:
        plan = _plan()
        receipt = _receipt(plan, status="waiting")

        internal = build_execution_graph(plan, receipt)
        public = project_public_execution_graph(internal)

        self.assertEqual(internal.nodes[1].status, "waiting")
        self.assertEqual(public.nodes[1].status, "waiting")

    def test_public_graph_keeps_authoritative_edges_without_internal_ids(
        self,
    ) -> None:
        plan = _plan()
        receipt = _receipt(plan, output=_web_output())
        graph = project_public_execution_graph(
            build_execution_graph(plan, receipt)
        )
        dumped = graph.model_dump_json()
        self.assertEqual(
            [(edge.source_id, edge.target_id) for edge in graph.edges],
            [("turn", "step-1"), ("step-1", "answer")],
        )
        self.assertNotIn("internal-action-r5", dumped)
        self.assertNotIn("provider_raw", dumped)

    def test_answer_completed_requires_committed_journal_event(self) -> None:
        plan = _plan()
        receipt = _receipt(plan, output=_web_output())
        answer = TrustedPublisher().publish_synthesis(
            ControllerOutput(
                mode="direct_answer",
                text=(
                    "## 推荐结论\n\n"
                    "- [来源一](https://example.com/one)：证据。"
                ),
            ),
            evidence=[ReceiptEvidenceBundle(plan=plan, receipt=receipt)],
        )
        turn = TurnReceipt(
            status="completed",
            request_id="request-r5",
            rounds=[
                ControllerRoundReceipt(
                    round_no=1,
                    output=ControllerOutput(
                        mode="capability_proposals",
                        tool_calls=[
                            {
                                "call_id": "web",
                                "name": "web_search",
                                "arguments": {"query": "近期好评图书"},
                            }
                        ],
                    ),
                    plan=plan,
                    receipt=receipt,
                ),
                ControllerRoundReceipt(
                    round_no=2,
                    output=ControllerOutput(
                        mode="direct_answer",
                        text=answer.content,
                    ),
                    answer=answer,
                ),
            ],
            plan_receipts=[receipt],
            final_answer=answer,
        )
        sequencer = TrustedStreamSequencer(request_id="request-r5")
        started = sequencer.turn_started()
        self.assertEqual(started.sequence, 1)
        self.assertEqual(started.type, "turn.started")
        with self.assertRaisesRegex(ValueError, "committed"):
            sequencer.answer_completed(answer=answer, committed=None)

        event = ConversationJournalEvent.model_validate(
            {
                "id": "2fd42c87-694b-45a6-ae9a-cc90f5685ef4",
                "user_id": "0564cc32-d249-4ed8-ad25-05835fc82aaf",
                "thread_id": "c418a420-013d-4194-a7c4-ffddf6c1f700",
                "request_id": "request-r5",
                "exchange_id": "3aa80a90-560f-44da-85f1-60b62b9ded61",
                "sequence_no": 2,
                "event_type": "assistant_published",
                "role": "assistant",
                "content": answer.content,
                "receipt_refs": answer.receipt_refs,
                "created_at": "2026-07-30T00:00:00Z",
            }
        )
        graph_event = sequencer.graph_snapshot(
            project_public_execution_graph(
                build_execution_graph(plan, receipt)
            )
        )
        committed = CommittedPublication(
            message={
                "type": "ai",
                "content": answer.content,
                "request_id": "request-r5",
            },
            journal_event=event,
            execution_graph=build_execution_graph(plan, receipt),
        )
        completed = sequencer.answer_completed(
            answer=turn.final_answer,
            committed=committed,
        )
        self.assertEqual(graph_event.sequence, 2)
        self.assertEqual(completed.sequence, 3)
        self.assertEqual(completed.type, "answer.completed")
        self.assertEqual(
            completed.content["journal_sequence"],
            event.sequence_no,
        )


class PublicationCommitTests(unittest.IsolatedAsyncioTestCase):
    async def test_turn_started_precedes_database_or_model_work(self) -> None:
        user_input = UserInput(
            content="你好",
            user_id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            request_id="request-r5-first-event",
        )
        stream = TrustedControllerStream(
            database_factory=lambda: (_ for _ in ()).throw(
                AssertionError(
                    "database opened before turn.started"
                )
            )
        ).generate(user_input)
        first = await anext(stream)
        await stream.aclose()
        self.assertIn('"type": "turn.started"', first)
        self.assertIn('"sequence": 1', first)

    async def test_commit_receipt_is_returned_only_after_db_commit(
        self,
    ) -> None:
        user_id = uuid.uuid4()
        thread_id = uuid.uuid4()

        class _DatabaseSession:
            committed = False

            async def commit(self):
                self.committed = True

        db = _DatabaseSession()

        class _Journal:
            async def record_assistant_message(
                self,
                db_session,
                *,
                user_input,
                message,
            ):
                self.assert_not_committed = not db_session.committed
                return ConversationJournalEvent(
                    id=uuid.uuid4(),
                    user_id=user_input.user_id,
                    thread_id=user_input.thread_id,
                    request_id=user_input.request_id,
                    exchange_id=uuid.uuid4(),
                    sequence_no=2,
                    event_type="assistant_published",
                    role="assistant",
                    content=message.content,
                    receipt_refs=[],
                    created_at=datetime.now(timezone.utc),
                )

        trace_observations: list[bool] = []

        async def _trace_writer(
            db_session,
            *,
            user_input,
            message,
            graph,
            model_name,
        ):
            del user_input, message, graph, model_name
            trace_observations.append(db_session.committed)

        answer = TrustedPublisher().publish_direct(
            ControllerOutput(mode="direct_answer", text="可信回答。")
        )
        journal = _Journal()
        committed = await TurnPublicationCommitter(
            journal=journal,
            trace_writer=_trace_writer,
        ).commit(
            db,  # type: ignore[arg-type]
            user_input=UserInput(
                content="你好",
                user_id=user_id,
                thread_id=thread_id,
                request_id="request-r5-commit",
            ),
            answer=answer,
            turn=None,
            model_name="fixture",
            agent_mode="plain_chat",
        )
        self.assertTrue(journal.assert_not_committed)
        self.assertEqual(trace_observations, [False])
        self.assertTrue(db.committed)
        self.assertEqual(
            committed.journal_event.event_type,
            "assistant_published",
        )
        self.assertEqual(
            committed.message.custom_data["agent_mode"],
            "plain_chat",
        )


if __name__ == "__main__":
    unittest.main()
