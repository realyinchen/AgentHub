from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from app.schemas.chat import ChatMessage
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.fast_path import (
    _immediate_memory_clarification,
    _memory_lookup_response,
    _memory_write_response,
    _reading_feedback_response,
)
from app.services.memory import MemoryEvent
from app.services.profile_memory_capture import ProfileMemoryCaptureResult
from app.utils.message import langchain_to_chat_message


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
    elif first.operation == "capture_user_state":
        content = _memory_write_from_receipt(plan, first.output)
    elif first.operation == "search_memory":
        content = _memory_lookup_from_receipt(first.output)
    elif first.operation == "record_book_feedback":
        content = _reading_feedback_response(
            first.output if isinstance(first.output, dict) else {}
        )
    else:
        content = "动作已执行完成。"

    tool_info = receipt_tool_info(receipt)
    trace = runtime_trace(plan, receipt)
    message = AIMessage(
        content=content,
        additional_kwargs={
            "custom_data": {
                "runtime_trace": trace,
                "action_plan": plan.model_dump(mode="json"),
                "plan_receipt": receipt.model_dump(mode="json"),
                "tool_info": tool_info,
            }
        },
    )
    result = langchain_to_chat_message(message)
    result.request_id = receipt.request_id
    result.custom_data.update(message.additional_kwargs["custom_data"])
    return result


def receipt_tool_info(receipt: PlanReceipt) -> list[dict[str, Any]]:
    return [
        {
            "name": item.operation,
            "id": item.action_id,
            "args": item.business_input,
            "output": json.dumps(item.output, ensure_ascii=False, default=str),
            "order": index,
            "status": item.status,
            "duration_ms": item.duration_ms,
            "system_executed": True,
            "plan_id": receipt.plan_id,
        }
        for index, item in enumerate(receipt.actions)
    ]


def receipt_trace_steps(receipt: PlanReceipt) -> list[dict[str, Any]]:
    """Project receipts into the existing tool-step observability contract."""

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
        }
        for item in receipt.actions
    ]


def runtime_trace(plan: ActionPlan, receipt: PlanReceipt) -> dict[str, Any]:
    memory_admission: list[dict[str, Any]] = []
    for action in receipt.actions:
        output = action.output if isinstance(action.output, dict) else {}
        candidates = output.get("memory_admission")
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
        "system_executed_tools": receipt_tool_info(receipt),
    }


def _memory_write_from_receipt(plan: ActionPlan, output: Any) -> str:
    payload = output if isinstance(output, dict) else {}
    if payload.get("capture_mode") == "deterministic":
        capture = ProfileMemoryCaptureResult(
            status=str(payload.get("status") or "completed"),
            captured_count=int(payload.get("captured_count") or 0),
            memories=[
                item for item in payload.get("memories", []) if isinstance(item, dict)
            ],
        )
        return _memory_write_response(capture)

    clarification = _immediate_memory_clarification(plan.goal)
    if clarification:
        return f"我已经先保存了你的原话，但当前指代不明确：{clarification}"
    if payload.get("memory_id"):
        return (
            f"已保存你的原话：{plan.goal.strip()}。"
            "后台会继续整理它与您的关系及适用场景；出现歧义或冲突时再向你确认。"
        )
    return "这条信息没有成功保存，我不会把它说成已经记住。"


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
    if operation == "capture_user_state":
        return "这条信息没有成功保存，我不会把它说成已经记住。"
    if operation == "search_memory":
        return "这次记忆查询没有成功完成。"
    if operation == "record_book_feedback":
        return "这条阅读反馈没有成功保存。"
    return "这次动作没有成功完成。"
