from __future__ import annotations

import unittest
from uuid import uuid4

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ExecutionContext,
    PlannedAction,
)
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.conversation.contracts import ConversationTurn, ConversationWindow
from app.services.conversation.recall import recall_recent_conversation
from app.services.memory.fact_extractor import MemoryFactExtractor
from app.services.memory.fact_validator import MemoryFactValidator
from app.services.memory.identity import extract_declared_name
from app.services.memory.committer import MemoryCommitter
from app.services.memory.providers.postgres import PostgresMemoryProvider
from app.services.memory.reference_resolver import MemoryReferenceResolver
from app.services.memory.write_coordinator import MemoryWriteCoordinator
from app.services.memory.write_contracts import (
    MemoryCommitCommand,
    MemoryWriteDecision,
    MemoryWriteRequest,
)
from app.services.profile_memory_capture import (
    extract_explicit_profile_memory_candidates,
)
from app.services.routing.contracts import RoutingQuery
from app.services.routing.context import (
    _context_from_messages,
    needs_business_context,
)
from app.services.routing.funnel import RoutingFunnel
from app.services.routing.interaction_contracts import BusinessRoutingContext
from app.services.routing.semantic import InMemorySemanticRecall


def _user_input(content: str) -> UserInput:
    return UserInput(
        content=content,
        user_id=uuid4(),
        thread_id=uuid4(),
        request_id=f"test-{uuid4()}",
    )


class MemoryPrecommitPipelineTests(unittest.TestCase):
    def test_greeting_prefixed_name_is_a_complete_canonical_fact(self) -> None:
        user_input = _user_input("你好我是冰露")
        self.assertEqual(extract_declared_name(user_input.content), "冰露")

        request = MemoryWriteRequest(
            utterance=user_input.content,
            explicit=False,
        )
        resolution = MemoryReferenceResolver().resolve(
            request,
            ConversationWindow(),
        )
        drafts = MemoryFactExtractor().deterministic(
            user_input=user_input,
            resolution=resolution,
        )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].state_key, "profile.name")
        self.assertEqual(drafts[0].state_value, {"name": "冰露"})
        self.assertEqual(drafts[0].summary, "你的名字是冰露")
        self.assertEqual(MemoryFactValidator().reasons(drafts[0]), [])

    def test_non_ascii_fact_values_receive_stable_ascii_state_keys(self) -> None:
        user_input = _user_input("我有一只猫咪叫咪咪，是一只三花母猫")
        resolution = MemoryReferenceResolver().resolve(
            MemoryWriteRequest(
                utterance=user_input.content,
                explicit=False,
            ),
            ConversationWindow(),
        )
        drafts = MemoryFactExtractor().deterministic(
            user_input=user_input,
            resolution=resolution,
        )

        self.assertEqual(len(drafts), 1)
        self.assertTrue(drafts[0].state_key.startswith("relation."))
        self.assertTrue(drafts[0].state_key.isascii())
        self.assertEqual(MemoryFactValidator().reasons(drafts[0]), [])

    def test_name_reference_uses_prior_user_assertion_only(self) -> None:
        request = MemoryWriteRequest(
            utterance="记住我的名字",
            target_expression="我的名字",
            explicit=True,
            conversation_context_required=True,
        )
        window = ConversationWindow(
            turns=[
                ConversationTurn(
                    role="user",
                    turn_offset=-2,
                    content="你好我是冰露",
                ),
                ConversationTurn(
                    role="assistant",
                    turn_offset=-1,
                    content="你好，冰露！",
                ),
            ]
        )

        resolution = MemoryReferenceResolver().resolve(request, window)

        self.assertEqual(resolution.status, "resolved")
        self.assertIsNotNone(resolution.source)
        assert resolution.source is not None
        self.assertEqual(resolution.source.source_kind, "prior_user_assertion")
        self.assertEqual(resolution.source.excerpt, "你好我是冰露")

    def test_unresolved_reference_requests_clarification_without_fact(self) -> None:
        request = MemoryWriteRequest(
            utterance="把这个记住",
            target_expression="这个",
            explicit=True,
            conversation_context_required=True,
        )

        resolution = MemoryReferenceResolver().resolve(
            request,
            ConversationWindow(),
        )

        self.assertEqual(resolution.status, "clarification_required")
        self.assertIsNone(resolution.source)
        self.assertTrue(resolution.clarification_question)

    def test_commit_ready_contract_cannot_exist_without_resolved_facts(self) -> None:
        with self.assertRaises(ValidationError):
            MemoryWriteDecision(status="commit_ready")

    def test_postgres_boundary_rejects_chat_event_without_full_proof(self) -> None:
        candidate = extract_explicit_profile_memory_candidates(
            _user_input("你好我是冰露")
        )[0]
        incomplete = candidate.to_memory_event()

        with self.assertRaisesRegex(
            ValueError,
            "complete precommit proof",
        ):
            PostgresMemoryProvider._assert_commit_ready(incomplete)

        metadata = dict(incomplete.metadata)
        precommit = dict(metadata["precommit"])
        precommit["conflict_checked"] = True
        metadata["precommit"] = precommit
        complete = incomplete.model_copy(update={"metadata": metadata})

        PostgresMemoryProvider._assert_commit_ready(complete)

    def test_conversation_recall_does_not_project_long_term_memory(self) -> None:
        window = ConversationWindow(
            turns=[
                ConversationTurn(
                    role="user",
                    turn_offset=-3,
                    content="你好我是冰露",
                ),
                ConversationTurn(
                    role="assistant",
                    turn_offset=-2,
                    content="你好，冰露！",
                ),
                ConversationTurn(
                    role="user",
                    turn_offset=-1,
                    content="记住我的名字",
                ),
            ]
        )

        result = recall_recent_conversation(
            window,
            query="我刚才跟你说什么了",
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            [turn.content for turn in result.turns],
            ["你好我是冰露", "记住我的名字"],
        )
        self.assertNotIn("memory", result.model_dump(mode="json"))


class _NoLiveSemanticRecall(InMemorySemanticRecall):
    async def _vector_candidates(self, text: str):
        del text
        return []


class MemoryClarificationContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_contradictory_same_key_batch_never_reaches_database(self) -> None:
        user_input = _user_input("我喜欢蓝色")
        resolution = MemoryReferenceResolver().resolve(
            MemoryWriteRequest(
                utterance=user_input.content,
                explicit=False,
            ),
            ConversationWindow(),
        )
        draft = MemoryFactExtractor().deterministic(
            user_input=user_input,
            resolution=resolution,
        )[0]
        fact = MemoryFactValidator().resolve(draft)
        opposite = fact.model_copy(
            update={
                "polarity": "dislike",
                "state_value": {
                    **fact.state_value,
                    "polarity": "dislike",
                },
            }
        )

        outcome = await MemoryCommitter().commit(
            MemoryCommitCommand(facts=[fact, opposite]),
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
        )

        self.assertEqual(outcome.status, "clarification_required")
        self.assertEqual(
            outcome.reason_codes,
            ["batch_canonical_key_conflict"],
        )

    async def test_bare_name_answer_resumes_typed_clarification(self) -> None:
        user_input = _user_input("记住我的名字")
        initial = await MemoryWriteCoordinator().process(
            MemoryWriteRequest(
                utterance=user_input.content,
                target_expression="我的名字",
                explicit=True,
                conversation_context_required=True,
            ),
            user_input=user_input,
            conversation=ConversationWindow(),
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
        )
        self.assertEqual(initial.status, "clarification_required")
        self.assertIsNotNone(initial.pending_clarification)
        assert initial.pending_clarification is not None

        decision = await RoutingFunnel(
            semantic_provider=_NoLiveSemanticRecall()
        ).decide(
            RoutingQuery(
                text="冰露",
                context=BusinessRoutingContext(
                    pending_memory_write=(
                        initial.pending_clarification.model_dump(mode="json")
                    )
                ),
            )
        )

        self.assertEqual(decision.primary_intent, "memory_update")
        self.assertEqual(decision.metadata["layers_used"], ["layer0_rule"])
        self.assertEqual(
            [action.operation for action in decision.proposed_actions],
            ["process_memory_write_request"],
        )
        resumed = MemoryWriteRequest.model_validate(
            decision.proposed_actions[0].arguments["request"]
        )
        resolution = MemoryReferenceResolver().resolve(
            resumed,
            ConversationWindow(),
        )
        self.assertEqual(resolution.status, "resolved")
        self.assertEqual(resolution.resolved_text, "我的名字是冰露")
        assert resolution.source is not None
        self.assertEqual(resolution.source.excerpt, "冰露")

    async def test_last_runtime_receipt_projects_pending_state(self) -> None:
        message = AIMessage(
            content="你希望我记住的名字是什么？",
            additional_kwargs={
                "custom_data": {
                    "plan_receipt": {
                        "actions": [
                            {
                                "operation": "process_memory_write_request",
                                "output": {
                                    "status": "clarification_required",
                                    "pending_clarification": {
                                        "kind": "reference",
                                        "original_utterance": "记住我的名字",
                                        "target_expression": "我的名字",
                                        "question": "你希望我记住的名字是什么？",
                                    },
                                },
                            }
                        ]
                    }
                }
            },
        )

        context = _context_from_messages([message])

        self.assertIsNotNone(context.pending_memory_write)
        assert context.pending_memory_write is not None
        self.assertEqual(
            context.pending_memory_write.target_expression,
            "我的名字",
        )

    async def test_bare_answer_reads_context_but_greeting_does_not(self) -> None:
        bare = _user_input("小雨")
        greeting = bare.model_copy(update={"content": "你好"})

        self.assertTrue(needs_business_context(bare))
        self.assertFalse(needs_business_context(greeting))

    async def test_runtime_blocks_retired_direct_memory_write_operation(self) -> None:
        user_input = _user_input("记住我喜欢蓝色")
        plan = ActionPlan(
            source="routing_decision",
            route_type="fast_path",
            intent="memory_update",
            goal=user_input.content,
            actions=[
                PlannedAction(
                    capability="memory",
                    operation="remember_memory",
                    arguments={
                        "type": "preference",
                        "subject": "tag",
                        "value": "蓝色",
                    },
                )
            ],
        )

        receipt = await SystemRuntime().execute(
            plan,
            context=ExecutionContext(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                request_id=user_input.request_id,
            ),
            user_input=user_input,
        )

        self.assertEqual(receipt.status, "blocked")
        self.assertEqual(
            receipt.actions[0].error,
            "chat_memory_write_requires_precommit_pipeline",
        )


if __name__ == "__main__":
    unittest.main()
