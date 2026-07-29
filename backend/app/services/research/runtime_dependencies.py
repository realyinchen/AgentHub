from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
)
from app.services.research.loop import (
    ResearchGapAssessment,
    ResearchRoundSources,
    ResearchSearchTask,
    acquire_research_round,
    evidence_was_admitted,
    evaluate_research_gaps,
    plan_research_search_task,
)


async def execute_research_dependency(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    previous: list[ActionReceipt],
) -> Any | None:
    """Resolve research run/source dependencies from prior receipts."""

    if action.operation == "plan_research_search":
        return _plan_search(action, previous=previous)
    if action.operation == "acquire_research_sources":
        return await _acquire(action, previous=previous)
    if action.operation == "collect_research_sources":
        return await _collect(action, context=context, previous=previous)
    if action.operation == "add_evidence" and not action.arguments.get("claim"):
        return await _admit_evidence(action, context=context, previous=previous)
    if action.operation == "evaluate_research_gaps":
        return await _evaluate_gaps(
            action,
            context=context,
            previous=previous,
        )
    if action.operation == "build_research_report" and not action.arguments.get("run_id"):
        return await _invoke_with_run(action, context=context, previous=previous)
    if action.operation == "synthesize_research_answer":
        return await _synthesize(
            action=action,
            previous=previous,
            context=context,
        )
    if action.operation == "publish_research_answer":
        return await _publish(previous=previous, context=context)
    if action.operation == "finalize_research_answer" and not action.arguments.get("run_id"):
        return await _invoke_with_run(action, context=context, previous=previous)
    return None


def _plan_search(
    action: PlannedAction,
    *,
    previous: list[ActionReceipt],
) -> dict[str, Any]:
    round_index = _round_index(action)
    previous_assessment = _round_output(
        previous,
        operation="evaluate_research_gaps",
        round_index=round_index - 1,
    )
    task = plan_research_search_task(
        objective=str(action.arguments.get("objective") or ""),
        round_index=round_index,
        budget=action.arguments.get("budget") or {},
        constraints=list(action.arguments.get("constraints") or []),
        previous_assessment=previous_assessment,
    )
    return {
        "status": "completed",
        **task.model_dump(mode="json"),
    }


async def _acquire(
    action: PlannedAction,
    *,
    previous: list[ActionReceipt],
) -> dict[str, Any]:
    round_index = _round_index(action)
    task_output = _round_output(
        previous,
        operation="plan_research_search",
        round_index=round_index,
    )
    if task_output is None:
        return _skipped("missing research search task receipt")
    task = ResearchSearchTask.model_validate(task_output)

    async def execute_search(arguments: dict[str, Any]) -> dict[str, Any]:
        from app.services.external_search import SearchRequest, get_search_gateway

        used = tuple(
            str(receipt.output.get("provider") or "")
            for receipt in previous
            if receipt.operation == "acquire_research_sources"
            and isinstance(receipt.output, dict)
            and receipt.output.get("provider")
        )
        result = await get_search_gateway().search(
            SearchRequest.model_validate(arguments),
            previously_used=used,
        )
        return result.model_dump(mode="json")

    result = await acquire_research_round(
        task=task,
        executor=execute_search,
    )
    return result.model_dump(mode="json")


async def _collect(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    previous: list[ActionReceipt],
) -> dict[str, Any]:
    run_id = _research_run_id(previous)
    round_index = _round_index(action)
    sources = _round_sources(previous, round_index)
    if not run_id:
        return _skipped("missing run_id from start_research")
    if sources is None:
        return _skipped("missing research round source receipt")
    records = [
        item.model_dump(mode="json")
        for item in sources.source_records
    ]
    if not sources.executed:
        return {
            "status": "completed",
            "result_mode": "research_source_collection",
            "run_id": run_id,
            "round_index": round_index,
            "source_count": 0,
            "publishable_source_count": 0,
            "execution_disposition": "no_op",
        }
    from app.agents.tools.research import collect_research_sources

    payload = await collect_research_sources.ainvoke(
        {
            "user_id": str(context.user_id),
            "run_id": run_id,
            "query": sources.task.query,
            "subquestion": sources.task.objective,
            "provider_source": sources.provider or "web_search",
            "sources": records,
            "status": "completed",
            "rationale": (
                f"Record research search round {round_index} before "
                "evidence admission."
            ),
            "duration_ms": 0,
            "error": sources.error or None,
            "metadata": {
                **dict(action.arguments.get("metadata") or {}),
                "research_round": round_index,
                "target_gaps": sources.task.target_gaps,
            },
        }
    )
    result = _json_or_value(payload)
    if isinstance(result, dict):
        collection_status = str(result.get("status") or "")
        if collection_status == "empty_result":
            result["status"] = "completed"
        result["collection_status"] = collection_status
        result["round_index"] = round_index
        result["provider_status"] = sources.provider_status
    return result


async def _admit_evidence(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    previous: list[ActionReceipt],
) -> dict[str, Any]:
    run_id = _research_run_id(previous)
    round_index = _round_index(action)
    sources = _round_sources(previous, round_index)
    records = (
        [
            item.model_dump(mode="json")
            for item in sources.source_records
        ]
        if sources is not None
        else []
    )
    limit = max(1, min(int(action.arguments.get("max_records") or 3), 5))
    seen = _admitted_record_keys(previous, before_round=round_index)
    selected = [
        record
        for record in records
        if _record_key(record) not in seen
    ][:limit]
    if not run_id:
        return _skipped("missing run_id from start_research")
    if sources is None:
        return _skipped("missing research round source receipt")
    if not sources.executed:
        return {
            "status": "completed",
            "result_mode": "research_evidence_admission_batch",
            "run_id": run_id,
            "round_index": round_index,
            "added_count": 0,
            "attempted_count": 0,
            "execution_disposition": "no_op",
            "admitted_record_keys": [],
            "results": [],
        }
    if not selected:
        return {
            "status": "completed",
            "result_mode": "research_evidence_admission_batch",
            "run_id": run_id,
            "round_index": round_index,
            "added_count": 0,
            "attempted_count": 0,
            "empty_reason": "no_publishable_evidence_candidates",
            "admitted_record_keys": [],
            "results": [],
        }

    from app.agents.tools.research import add_evidence

    results: list[Any] = []
    admitted_record_keys: list[list[str]] = []
    for record in selected:
        payload = await add_evidence.ainvoke(
            {
                "user_id": str(context.user_id),
                "run_id": run_id,
                "source_type": record.get("source_type") or "web",
                "source_title": record.get("source_title") or "",
                "source_url": record.get("source_url") or "",
                "claim": record.get("claim") or "",
                "excerpt": record.get("excerpt") or record.get("claim") or "",
                "quality": record.get("quality") or "unknown",
                "relevance": record.get("relevance") or 3,
                "known_facts": [record.get("claim")] if record.get("claim") else [],
                "metadata": {
                    "capture_source": "routing_decision",
                    "source_record": record,
                },
            }
        )
        result = _json_or_value(payload)
        results.append(result)
        if evidence_was_admitted(result):
            admitted_record_keys.append(list(_record_key(record)))
    return {
        "status": "completed",
        "result_mode": "research_evidence_admission_batch",
        "run_id": run_id,
        "round_index": round_index,
        "added_count": len(admitted_record_keys),
        "attempted_count": len(selected),
        "admitted_record_keys": admitted_record_keys,
        "results": results,
    }


async def _evaluate_gaps(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    previous: list[ActionReceipt],
) -> dict[str, Any]:
    round_index = _round_index(action)
    run_id = _research_run_id(previous)
    if not run_id:
        return _skipped("missing run_id from start_research")

    current_sources = _round_sources(previous, round_index)
    previous_assessment = _round_output(
        previous,
        operation="evaluate_research_gaps",
        round_index=round_index - 1,
    )
    if (
        current_sources is not None
        and not current_sources.executed
        and previous_assessment is not None
    ):
        assessment = ResearchGapAssessment.model_validate(
            previous_assessment
        ).model_copy(
            update={
                "round_index": round_index,
                "stop_reason": "previous_round_satisfied",
                "should_continue": False,
            }
        )
    else:
        admitted_keys = _admitted_record_keys(
            previous,
            before_round=round_index + 1,
        )
        rounds: list[ResearchRoundSources] = []
        for receipt in previous:
            if receipt.operation != "acquire_research_sources":
                continue
            if not isinstance(receipt.output, dict):
                continue
            sources = ResearchRoundSources.model_validate(receipt.output)
            if sources.round_index > round_index:
                continue
            rounds.append(
                sources.model_copy(
                    update={
                        "source_records": [
                            record
                            for record in sources.source_records
                            if _record_key(record.model_dump(mode="json"))
                            in admitted_keys
                        ]
                    }
                )
            )
        assessment = evaluate_research_gaps(
            round_index=round_index,
            rounds=rounds,
            budget=action.arguments.get("budget") or {},
        )

    from app.services.research.orchestrator import get_research_orchestrator

    await get_research_orchestrator().update_research_state(
        user_id=context.user_id,
        run_id=UUID(run_id),
        gaps=assessment.gap_descriptions,
        exhausted_queries=assessment.exhausted_queries,
        next_actions=assessment.next_actions,
        metadata={
            "research_loop": assessment.model_dump(mode="json"),
        },
        replace=True,
    )
    return assessment.model_dump(mode="json")


async def _invoke_with_run(
    action: PlannedAction,
    *,
    context: ExecutionContext,
    previous: list[ActionReceipt],
) -> dict[str, Any]:
    run_id = _research_run_id(previous)
    if not run_id:
        return _skipped("missing run_id from start_research")

    from app.agents import tools as agent_tools

    tool = getattr(agent_tools, action.operation)
    payload = await tool.ainvoke(
        {
            **action.arguments,
            "user_id": str(context.user_id),
            "run_id": run_id,
        }
    )
    return _json_or_value(payload)


async def _synthesize(
    *,
    action: PlannedAction,
    previous: list[ActionReceipt],
    context: ExecutionContext,
) -> dict[str, Any]:
    report_receipt = _latest(previous, "build_research_report")
    if report_receipt is None or not isinstance(report_receipt.output, dict):
        return _skipped("missing research report receipt")

    from app.services.research.publication import synthesize_research_report

    result = await synthesize_research_report(
        report_receipt.output,
        model_id=context.model_name,
        target_findings=int(action.arguments.get("target_findings") or 0),
    )
    return result.model_dump(mode="json")


async def _publish(
    *,
    previous: list[ActionReceipt],
    context: ExecutionContext,
) -> dict[str, Any]:
    report_receipt = _latest(previous, "build_research_report")
    synthesis_receipt = _latest(previous, "synthesize_research_answer")
    if report_receipt is None or not isinstance(report_receipt.output, dict):
        return _skipped("missing research report receipt")
    if synthesis_receipt is None or not isinstance(
        synthesis_receipt.output,
        dict,
    ):
        return _skipped("missing research synthesis receipt")

    from app.services.research.publication import publish_research_answer

    result = publish_research_answer(
        report_receipt.output,
        synthesis_receipt.output,
    )
    acquisitions = [
        receipt.output
        for receipt in previous
        if receipt.operation == "acquire_research_sources"
        and isinstance(receipt.output, dict)
    ]
    providers_unavailable = bool(acquisitions) and all(
        str(output.get("provider_status") or "") == "unavailable"
        for output in acquisitions
    )
    final_status = (
        "failed"
        if (
            result.answer_status == "blocked_no_publishable_evidence"
            and providers_unavailable
        )
        else "completed"
    )

    from app.services.research.orchestrator import get_research_orchestrator

    state = await get_research_orchestrator().finish_research(
        user_id=context.user_id,
        run_id=result.run_id,
        conclusion=result.answer,
        status=final_status,
        gaps=list(result.limitations),
        metadata={
            "publication_status": result.answer_status,
            "providers_unavailable": providers_unavailable,
        },
    )
    return {
        **result.model_dump(mode="json"),
        "research_status": final_status,
        "research_state": state.model_dump(mode="json"),
    }


def _research_run_id(receipts: list[ActionReceipt]) -> str:
    paths = (
        ("run", "id"),
        ("state", "run_id"),
        ("run_id",),
        ("id",),
        ("research_state", "run", "id"),
        ("research_state", "state", "run_id"),
    )
    for receipt in reversed(receipts):
        if receipt.operation not in {
            "start_research",
            "collect_research_sources",
            "add_evidence",
        } or not isinstance(receipt.output, dict):
            continue
        for path in paths:
            value = _nested(receipt.output, path)
            if value:
                return str(value)
    return ""


def _latest(receipts: list[ActionReceipt], operation: str) -> ActionReceipt | None:
    return next(
        (item for item in reversed(receipts) if item.operation == operation),
        None,
    )


def _round_index(action: PlannedAction) -> int:
    return max(1, min(int(action.arguments.get("round_index") or 1), 3))


def _round_output(
    receipts: list[ActionReceipt],
    *,
    operation: str,
    round_index: int,
) -> dict[str, Any] | None:
    if round_index < 1:
        return None
    for receipt in reversed(receipts):
        if receipt.operation != operation or not isinstance(receipt.output, dict):
            continue
        if int(receipt.output.get("round_index") or 0) == round_index:
            return receipt.output
    return None


def _round_sources(
    receipts: list[ActionReceipt],
    round_index: int,
) -> ResearchRoundSources | None:
    output = _round_output(
        receipts,
        operation="acquire_research_sources",
        round_index=round_index,
    )
    return ResearchRoundSources.model_validate(output) if output is not None else None


def _admitted_record_keys(
    receipts: list[ActionReceipt],
    *,
    before_round: int,
) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for receipt in receipts:
        if receipt.operation != "add_evidence":
            continue
        if not isinstance(receipt.output, dict):
            continue
        round_index = int(receipt.output.get("round_index") or 0)
        if round_index >= before_round:
            continue
        for key in receipt.output.get("admitted_record_keys") or []:
            if isinstance(key, list) and len(key) == 2:
                result.add((str(key[0]), str(key[1])))
    return result


def _record_key(record: dict[str, Any]) -> tuple[str, str]:
    return (
        str(record.get("source_url") or "").strip().lower(),
        str(record.get("claim") or "").strip().lower(),
    )


def _nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _skipped(reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "result_mode": "dependency_skipped",
        "error": reason,
    }


def _json_or_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
