from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.services.agent_core.certification_contracts import (
    AgentModeAdmission,
)
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.controller_golden_evaluator import (
    ControllerGoldenCaseEvaluator,
    ControllerGoldenReportEvaluator,
)
from app.services.agent_core.controller_golden_loader import (
    ControllerGoldenDatasetLoader,
)
from app.services.agent_core.controller_golden_runner import (
    ControllerGoldenRunner,
)
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_core.shadow import ShadowValidator
from app.services.memory.version_contracts import SearchMemoryRequest
from app.services.tasks.draft_validator import TaskPlanDraftValidator


DATASET = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "controller_golden_v1.json"
)


def _enabled_case_evaluator() -> ControllerGoldenCaseEvaluator:
    registry = CapabilityRegistry(
        core_availability=CoreCapabilityAvailability.all_enabled()
    )
    return ControllerGoldenCaseEvaluator(
        shadow_validator=ShadowValidator(
            validator=ProposalValidator(registry),
            task_plan_validator=TaskPlanDraftValidator(registry),
        )
    )


class _ReferenceController:
    def __init__(self, loaded) -> None:
        self.calls = 0
        self._outputs = {
            item.current_user_message: item.reference_output
            for item in loaded.dataset.cases
        }

    async def decide(self, request):
        self.calls += 1
        return self._outputs[request.current_user_message]


class ControllerGoldenDatasetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.loaded = ControllerGoldenDatasetLoader().load(DATASET)

    def test_dataset_has_all_fixed_denominators(self) -> None:
        dataset = self.loaded.dataset
        self.assertEqual(dataset.dataset_version, "controller-golden-v1")
        self.assertEqual(len(dataset.cases), 26)
        self.assertTrue(any(item.critical for item in dataset.cases))
        self.assertTrue(any(item.safety for item in dataset.cases))
        self.assertTrue(any(item.simple_direct for item in dataset.cases))
        self.assertTrue(any(item.explicit_tool for item in dataset.cases))

    def test_reference_outputs_pass_but_are_not_live_evidence(self) -> None:
        evaluator = _enabled_case_evaluator()
        results = [
            evaluator.evaluate(case, case.reference_output)
            for case in self.loaded.dataset.cases
        ]
        report = ControllerGoldenReportEvaluator().evaluate(
            self.loaded.dataset,
            results,
            live_model_evidence=False,
            commit_sha="c" * 40,
            source_dirty_worktree=True,
            generated_at=datetime.now(timezone.utc),
            model_id=None,
            certification_id=None,
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            prompt_version="controller-prompt-v1",
            dataset_hash=self.loaded.sha256,
        )
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.passed_count, 26)
        self.assertEqual(
            report.reasons,
            ["live_model_evidence_missing"],
        )
        rendered = report.model_dump_json()
        self.assertNotIn('"arguments"', rendered)
        self.assertNotIn("你好我是冰露", rendered)

    def test_stable_case_failure_codes_cover_quality_axes(self) -> None:
        evaluator = _enabled_case_evaluator()
        recall = next(
            item
            for item in self.loaded.dataset.cases
            if item.category == "conversation_recall"
        )
        wrong = evaluator.evaluate(
            recall,
            ControllerOutput(
                mode="direct_answer",
                text="No read.",
            ),
        )
        self.assertIn("unexpected_mode", wrong.reason_codes)
        self.assertIn(
            "required_capability_missing",
            wrong.reason_codes,
        )

        simple = next(
            item
            for item in self.loaded.dataset.cases
            if item.simple_direct
        )
        triggered = evaluator.evaluate(
            simple,
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="read",
                        name="conversation_read",
                        arguments={
                            "target": "exchange",
                            "selection": "latest",
                            "count": 1,
                        },
                    )
                ],
            ),
        )
        self.assertIn(
            "simple_direct_tool_triggered",
            triggered.reason_codes,
        )

        trusted = next(
            item
            for item in self.loaded.dataset.cases
            if item.case_id == "memory.read.identity"
        )
        missing_fact = evaluator.evaluate(
            trusted,
            ControllerOutput(
                mode="direct_answer",
                text="我不知道。",
            ),
        )
        self.assertIn(
            "required_text_fragment_missing",
            missing_fact.reason_codes,
        )

        conversation = next(
            item
            for item in self.loaded.dataset.cases
            if item.case_id == "conversation.latest.exchange"
        )
        wrong_target = evaluator.evaluate(
            conversation,
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="wrong-target",
                        name="conversation_read",
                        arguments={
                            "target": "user",
                            "selection": "latest",
                            "count": 1,
                        },
                    )
                ],
            ),
        )
        self.assertIn(
            "required_call_arguments_mismatch",
            wrong_target.reason_codes,
        )

        task_case = next(
            item
            for item in self.loaded.dataset.cases
            if item.case_id == "task.plan.multi.step"
        )
        draft = task_case.reference_output.task_plan_proposal
        undersized = evaluator.evaluate(
            task_case,
            ControllerOutput(
                mode="task_plan_proposal",
                task_plan_proposal=draft.model_copy(
                    update={"steps": [draft.steps[0]]}
                ),
            ),
        )
        self.assertIn(
            "plan_step_count_below_minimum",
            undersized.reason_codes,
        )
        self.assertIn(
            "plan_dependency_edge_missing",
            undersized.reason_codes,
        )

    def test_memory_search_requires_query_or_predicate(self) -> None:
        with self.assertRaises(ValidationError):
            SearchMemoryRequest(query=" ", predicate="")
        self.assertEqual(
            SearchMemoryRequest(
                query="",
                predicate="name",
            ).predicate,
            "name",
        )

    async def test_runner_calls_controller_once_and_never_runtime(
        self,
    ) -> None:
        controller = _ReferenceController(self.loaded)
        model_id = uuid4()
        report = await ControllerGoldenRunner(
            controller=controller,
            case_evaluator=_enabled_case_evaluator(),
        ).run(
            self.loaded,
            model_name="fixture-controller",
            model_id=model_id,
            admission=AgentModeAdmission(
                admitted=True,
                certification_id="fixture-cert",
                configuration_fingerprint="a" * 64,
                controller_fingerprint="b" * 64,
                source_commit_sha="c" * 40,
            ),
            source_state=GitSourceState(
                commit_sha="c" * 40,
                dirty_worktree=False,
            ),
            prompt_version="controller-prompt-v1",
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(controller.calls, 26)
        self.assertEqual(report.total_controller_calls, 26)
        self.assertEqual(report.total_runtime_calls, 0)
        self.assertFalse(report.source_dirty_worktree)
        self.assertEqual(report.certification_id, "fixture-cert")

    async def test_runner_rejects_dirty_source_before_controller_call(
        self,
    ) -> None:
        controller = _ReferenceController(self.loaded)
        with self.assertRaisesRegex(
            ValueError,
            "requires clean source",
        ):
            await ControllerGoldenRunner(controller=controller).run(
                self.loaded,
                model_name="fixture-controller",
                model_id=uuid4(),
                admission=AgentModeAdmission(
                    admitted=True,
                    certification_id="fixture-cert",
                    configuration_fingerprint="a" * 64,
                    controller_fingerprint="b" * 64,
                    source_commit_sha="c" * 40,
                ),
                source_state=GitSourceState(
                    commit_sha="c" * 40,
                    dirty_worktree=True,
                ),
                prompt_version="controller-prompt-v1",
            )
        self.assertEqual(controller.calls, 0)

    async def test_runner_rejects_other_release_admission_before_call(
        self,
    ) -> None:
        controller = _ReferenceController(self.loaded)
        with self.assertRaisesRegex(
            ValueError,
            "admission belongs to another release",
        ):
            await ControllerGoldenRunner(controller=controller).run(
                self.loaded,
                model_name="fixture-controller",
                model_id=uuid4(),
                admission=AgentModeAdmission(
                    admitted=True,
                    certification_id="fixture-cert",
                    configuration_fingerprint="a" * 64,
                    controller_fingerprint="b" * 64,
                    source_commit_sha="d" * 40,
                ),
                source_state=GitSourceState(
                    commit_sha="c" * 40,
                    dirty_worktree=False,
                ),
                prompt_version="controller-prompt-v1",
            )
        self.assertEqual(controller.calls, 0)


if __name__ == "__main__":
    unittest.main()
