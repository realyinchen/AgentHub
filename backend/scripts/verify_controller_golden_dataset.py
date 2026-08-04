"""Validate or run the versioned Controller golden/safety dataset."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.infra.llm.resolver import resolve_model_name
from app.services.agent_certification import get_agent_mode_admission
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.controller_golden_evaluator import (
    ControllerGoldenReportEvaluator,
)
from app.services.agent_core.controller_golden_loader import (
    ControllerGoldenDatasetLoader,
)
from app.services.agent_core.controller_golden_runner import (
    ControllerGoldenRunner,
    golden_case_evaluator,
)
from app.services.agent_core.evidence_artifact import (
    EvidenceArtifactWriter,
)
from app.services.agent_core.evidence_source import (
    GitSourceState,
    GitSourceStateReader,
)
from app.services.agent_core.prompt_composer import (
    CONTROLLER_PROMPT_VERSION,
)


DEFAULT_DATASET = (
    BACKEND_DIR / "evals" / "controller_golden_v1.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--model-id")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--commit-sha")
    parser.add_argument("--output")
    return parser


def _self_test(loaded, *, commit_sha: str):
    evaluator = golden_case_evaluator()
    results = [
        evaluator.evaluate(case, case.reference_output)
        for case in loaded.dataset.cases
    ]
    report = ControllerGoldenReportEvaluator().evaluate(
        loaded.dataset,
        results,
        live_model_evidence=False,
        commit_sha=commit_sha or "c" * 40,
        source_dirty_worktree=True,
        generated_at=datetime.now(timezone.utc),
        model_id=None,
        certification_id=None,
        configuration_fingerprint="a" * 64,
        controller_fingerprint=current_controller_fingerprint(),
        prompt_version=CONTROLLER_PROMPT_VERSION,
        dataset_hash=loaded.sha256,
    )
    if (
        report.status != "blocked"
        or report.passed_count != report.sample_count
        or report.reasons != ["live_model_evidence_missing"]
    ):
        raise AssertionError(
            "reference outputs did not produce the expected blocked report"
        )

    recall_case = next(
        item
        for item in loaded.dataset.cases
        if item.category == "conversation_recall"
    )
    wrong_mode = evaluator.evaluate(
        recall_case,
        ControllerOutput(
            mode="direct_answer",
            text="I will answer without reading.",
        ),
    )
    if not {
        "unexpected_mode",
        "required_capability_missing",
    }.issubset(wrong_mode.reason_codes):
        raise AssertionError("wrong mode failure was not classified")

    simple_case = next(
        item for item in loaded.dataset.cases if item.simple_direct
    )
    simple_tool = evaluator.evaluate(
        simple_case,
        ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="wrong-tool",
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
    if "simple_direct_tool_triggered" not in simple_tool.reason_codes:
        raise AssertionError(
            "simple direct tool trigger was not classified"
        )

    invalid_system_field = evaluator.evaluate(
        recall_case,
        ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="unsafe",
                    name="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                        "user_id": "model-owned",
                    },
                )
            ],
        ),
    )
    if "shadow_validation_failed" not in invalid_system_field.reason_codes:
        raise AssertionError(
            "system-owned field failure was not classified"
        )
    trusted_memory_case = next(
        item
        for item in loaded.dataset.cases
        if item.case_id == "memory.read.identity"
    )
    missing_trusted_fact = evaluator.evaluate(
        trusted_memory_case,
        ControllerOutput(
            mode="direct_answer",
            text="我不知道你的名字。",
        ),
    )
    if (
        "required_text_fragment_missing"
        not in missing_trusted_fact.reason_codes
    ):
        raise AssertionError(
            "trusted memory answer failure was not classified"
        )
    memory_search_case = next(
        item
        for item in loaded.dataset.cases
        if item.case_id == "memory.read.preference"
    )
    empty_memory_search = evaluator.evaluate(
        memory_search_case,
        ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="empty-memory-search",
                    name="search_memory",
                    arguments={"query": "", "predicate": ""},
                )
            ],
        ),
    )
    if "shadow_validation_failed" not in empty_memory_search.reason_codes:
        raise AssertionError(
            "empty memory search was not rejected"
        )
    conversation_case = next(
        item
        for item in loaded.dataset.cases
        if item.case_id == "conversation.latest.exchange"
    )
    wrong_conversation_target = evaluator.evaluate(
        conversation_case,
        ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="wrong-conversation-target",
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
    if (
        "required_call_arguments_mismatch"
        not in wrong_conversation_target.reason_codes
    ):
        raise AssertionError(
            "conversation argument mismatch was not classified"
        )
    multi_step_case = next(
        item
        for item in loaded.dataset.cases
        if item.case_id == "task.plan.multi.step"
    )
    multi_step_draft = multi_step_case.reference_output.task_plan_proposal
    undersized_plan = evaluator.evaluate(
        multi_step_case,
        ControllerOutput(
            mode="task_plan_proposal",
            task_plan_proposal=multi_step_draft.model_copy(
                update={"steps": [multi_step_draft.steps[0]]}
            ),
        ),
    )
    if not {
        "plan_step_count_below_minimum",
        "plan_dependency_edge_missing",
    }.issubset(undersized_plan.reason_codes):
        raise AssertionError(
            "undersized plan failure was not classified"
        )
    memory_audit_case = next(
        item
        for item in loaded.dataset.cases
        if item.case_id == "task.plan.memory.audit"
    )
    missing_plan_capability = evaluator.evaluate(
        memory_audit_case,
        multi_step_case.reference_output,
    )
    if (
        "required_plan_capability_missing"
        not in missing_plan_capability.reason_codes
    ):
        raise AssertionError(
            "missing plan capability was not classified"
        )
    report_json = report.model_dump_json()
    if (
        '"arguments"' in report_json
        or "你好我是冰露" in report_json
    ):
        raise AssertionError(
            "Controller golden report leaked inputs or arguments"
        )
    print("Controller golden dataset self-test passed")
    print(f"dataset_version={loaded.dataset.dataset_version}")
    print(f"dataset_hash={loaded.sha256}")
    print(f"sample_count={report.sample_count}")
    print(f"reference_cases_passed={report.passed_count}")
    print("wrong_mode_failure=classified")
    print("simple_tool_trigger=classified")
    print("system_field_failure=classified")
    print("trusted_memory_text_failure=classified")
    print("empty_memory_search=blocked")
    print("call_argument_mismatch=classified")
    print("plan_structure_failures=classified")
    print("raw_arguments_in_report=0")
    print("live_model_evidence=false")
    return report


async def _live(args, loaded, *, source_state: GitSourceState):
    model_id = UUID(str(args.model_id))
    await init_database_connection()
    try:
        await _refresh_live_model_cache()
        database = get_database()
        async with database.session() as db:
            admission = await get_agent_mode_admission(
                db,
                model_id,
                source_commit_sha=source_state.commit_sha,
            )
        if not admission.admitted:
            raise RuntimeError(
                "current model has no exact successful Agent admission: "
                + str(admission.reason)
            )
        model_name = resolve_model_name(str(model_id))
        if not model_name:
            raise RuntimeError("configured model name cannot be resolved")
        return await ControllerGoldenRunner().run(
            loaded,
            model_name=model_name,
            model_id=model_id,
            admission=admission,
            source_state=source_state,
            prompt_version=CONTROLLER_PROMPT_VERSION,
        )
    finally:
        await dispose_database()


async def _refresh_live_model_cache() -> None:
    """Mirror the application startup prerequisite for DB-backed get_llm."""
    from app.infra.llm.manager import get_model_manager

    await get_model_manager().refresh()


async def _run(args: argparse.Namespace) -> int:
    loaded = ControllerGoldenDatasetLoader().load(args.dataset)
    writer = EvidenceArtifactWriter()
    if args.self_test:
        report = _self_test(
            loaded,
            commit_sha=args.commit_sha or "c" * 40,
        )
    else:
        if not args.commit_sha:
            raise RuntimeError(
                "live Controller golden run requires --commit-sha"
            )
        if not args.output:
            raise RuntimeError(
                "live Controller golden run requires --output"
            )
        writer.require_available(args.output)
        source_state = GitSourceStateReader().require_release_state(
            BACKEND_DIR.parent,
            expected_commit_sha=args.commit_sha,
        )
        report = await _live(
            args,
            loaded,
            source_state=source_state,
        )
    rendered = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    if args.output:
        writer.write_json_new(args.output, report)
    if not args.self_test:
        print(rendered)
    return 0 if args.self_test or report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
