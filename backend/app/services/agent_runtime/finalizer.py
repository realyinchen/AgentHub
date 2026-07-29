from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from app.schemas.chat import ChatMessage
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.agent_runtime.execution_graph import build_execution_graph
from app.services.agent_runtime.failure_projection import (
    RuntimeFailureSummary,
    project_runtime_failure,
    render_research_failure,
)
from app.services.fast_path import (
    _memory_lookup_response,
    _reading_feedback_response,
)
from app.services.memory import MemoryEvent
from app.utils.message import langchain_to_chat_message


def finalize_runtime_receipt(
    plan: ActionPlan,
    receipt: PlanReceipt,
) -> ChatMessage:
    """Finalize every model-free response mode from an actual receipt."""

    if plan.response_mode == "deterministic":
        return finalize_deterministic_receipt(plan, receipt)
    if plan.response_mode != "receipt":
        raise ValueError("runtime finalizer requires deterministic or receipt mode")
    if receipt.plan_id != plan.plan_id:
        raise ValueError("receipt does not belong to the supplied action plan")

    final_action = next(
        (
            item
            for item in reversed(receipt.actions)
            if item.operation
            in {"publish_research_answer", "finalize_research_answer"}
        ),
        None,
    )
    output = (
        final_action.output
        if final_action and isinstance(final_action.output, dict)
        else {}
    )
    failure_summary: RuntimeFailureSummary | None = None
    if final_action is None:
        failure_summary = project_runtime_failure(plan, receipt)
        content = render_research_failure(failure_summary)
    elif final_action.status in {"failed", "blocked", "skipped"}:
        failure_summary = project_runtime_failure(plan, receipt)
        content = render_research_failure(failure_summary)
    else:
        content = str(output.get("answer") or "").strip()
        if not content:
            content = "研究回执中没有可发布的已验证结论。"

    return _chat_message_from_receipt(
        content,
        plan,
        receipt,
        failure_summary=failure_summary,
    )


def finalize_deterministic_receipt(
    plan: ActionPlan,
    receipt: PlanReceipt,
) -> ChatMessage:
    """Create a fast answer only after the system has issued a receipt."""

    if plan.response_mode != "deterministic":
        raise ValueError("deterministic finalizer requires deterministic response mode")
    if receipt.plan_id != plan.plan_id:
        raise ValueError("receipt does not belong to the supplied action plan")

    first = receipt.actions[0] if receipt.actions else None
    if first is None:
        content = "这次请求没有生成可执行动作。"
    elif first.status in {"failed", "blocked"}:
        content = _failed_action_response(first.operation)
    elif first.operation == "process_memory_write_request":
        content = _memory_write_from_receipt(first.output)
    elif first.operation == "recall_recent_conversation":
        content = _conversation_recall_from_receipt(first.output)
    elif first.operation == "search_memory":
        content = _memory_lookup_from_receipt(first.output)
    elif first.operation == "record_book_feedback":
        content = _reading_feedback_response(
            first.output if isinstance(first.output, dict) else {}
        )
    else:
        content = "动作已执行完成。"

    return _chat_message_from_receipt(content, plan, receipt)


def _chat_message_from_receipt(
    content: str,
    plan: ActionPlan,
    receipt: PlanReceipt,
    *,
    failure_summary: RuntimeFailureSummary | None = None,
) -> ChatMessage:
    tool_info = receipt_tool_info(receipt, plan=plan)
    trace = runtime_trace(plan, receipt)
    execution_graph = build_execution_graph(plan, receipt)
    message = AIMessage(
        content=content,
        additional_kwargs={
            "custom_data": {
                "runtime_trace": trace,
                "action_plan": plan.model_dump(mode="json"),
                "plan_receipt": receipt.model_dump(mode="json"),
                "execution_graph": execution_graph.model_dump(mode="json"),
                "tool_info": tool_info,
                "failure_summary": (
                    failure_summary.model_dump(mode="json")
                    if failure_summary is not None
                    else None
                ),
            }
        },
    )
    result = langchain_to_chat_message(message)
    result.request_id = receipt.request_id
    result.custom_data.update(message.additional_kwargs["custom_data"])
    return result


def receipt_tool_info(
    receipt: PlanReceipt,
    *,
    plan: ActionPlan | None = None,
) -> list[dict[str, Any]]:
    dependencies = _dependencies_by_action_id(plan)
    return [
        {
            "name": item.operation,
            "id": item.action_id,
            "args": item.business_input,
            "output": json.dumps(item.output, ensure_ascii=False, default=str),
            "order": index,
            "status": item.status,
            "error": item.error or None,
            "duration_ms": item.duration_ms,
            "system_executed": True,
            "plan_id": receipt.plan_id,
            "depends_on": dependencies.get(item.action_id, []),
        }
        for index, item in enumerate(receipt.actions)
    ]


def receipt_trace_steps(
    receipt: PlanReceipt,
    *,
    plan: ActionPlan | None = None,
) -> list[dict[str, Any]]:
    """Project receipts into the existing tool-step observability contract."""

    dependencies = _dependencies_by_action_id(plan)
    return [
        {
            "action_id": item.action_id,
            "tool_name": item.operation,
            "args": item.business_input,
            "output": item.output,
            "error": item.error or None,
            "status": item.status,
            "duration_ms": item.duration_ms,
            "system_executed": True,
            "plan_id": receipt.plan_id,
            "depends_on": dependencies.get(item.action_id, []),
        }
        for item in receipt.actions
    ]


def runtime_trace(plan: ActionPlan, receipt: PlanReceipt) -> dict[str, Any]:
    memory_admission: list[dict[str, Any]] = []
    for action in receipt.actions:
        output = action.output if isinstance(action.output, dict) else {}
        candidates = output.get("admission") or output.get("memory_admission")
        if isinstance(candidates, list):
            memory_admission.extend(
                item for item in candidates if isinstance(item, dict)
            )
    return {
        "request_id": receipt.request_id,
        "plan_id": plan.plan_id,
        "route_type": plan.route_type,
        "intent": plan.intent,
        "fast_path": plan.route_type == "fast_path",
        "slow_path": plan.route_type == "slow_path",
        "planner_used": plan.planner_used,
        "plan_source": plan.source,
        "receipt_status": receipt.status,
        "duration_ms": receipt.duration_ms,
        "memory_admission": memory_admission,
        "execution_graph": build_execution_graph(plan, receipt).model_dump(
            mode="json"
        ),
        "system_executed_tools": receipt_tool_info(receipt, plan=plan),
    }


def _dependencies_by_action_id(
    plan: ActionPlan | None,
) -> dict[str, list[str]]:
    if plan is None:
        return {}
    return {
        action.action_id: list(action.depends_on)
        for action in plan.actions
    }


def _memory_write_from_receipt(output: Any) -> str:
    payload = output if isinstance(output, dict) else {}
    status = str(payload.get("status") or "")
    facts = [
        item for item in payload.get("facts", []) if isinstance(item, dict)
    ]
    summaries = [
        str(item.get("summary") or "").strip()
        for item in facts
        if str(item.get("summary") or "").strip()
    ]
    rendered = "；".join(summaries)
    if status == "committed":
        return f"好的，我已经记住：{rendered}。" if rendered else "好的，这条事实已经记住。"
    if status == "noop_duplicate":
        return (
            f"我已经记得：{rendered}，不需要重复保存。"
            if rendered
            else "这条事实已经在长期记忆中，不需要重复保存。"
        )
    if status == "clarification_required":
        return str(payload.get("clarification_question") or "").strip() or (
            "我还不能确定要保存的完整事实，请再说明一下。"
        )
    if status == "rejected":
        return "这条内容没有形成完整、可确认的长期事实，因此我没有保存。"
    return "这条信息没有成功保存，我不会把它说成已经记住。"


def _conversation_recall_from_receipt(output: Any) -> str:
    payload = output if isinstance(output, dict) else {}
    return str(payload.get("answer") or "").strip() or (
        "当前会话里没有更早的消息可供回顾。"
    )


def _memory_lookup_from_receipt(output: Any) -> str:
    payload = output if isinstance(output, dict) else {}
    memories: list[MemoryEvent] = []
    for item in payload.get("memories", []):
        if not isinstance(item, dict):
            continue
        try:
            memories.append(MemoryEvent.model_validate(item))
        except Exception:
            continue
    return _memory_lookup_response(
        memories,
        lookup_kind=str(payload.get("lookup_kind") or "generic"),
    )


def _failed_action_response(operation: str) -> str:
    if operation == "process_memory_write_request":
        return "这条信息没有成功保存，我不会把它说成已经记住。"
    if operation == "recall_recent_conversation":
        return "这次没有成功读取当前会话记录。"
    if operation == "search_memory":
        return "这次记忆查询没有成功完成。"
    if operation == "record_book_feedback":
        return "这条阅读反馈没有成功保存。"
    return "这次动作没有成功完成。"
