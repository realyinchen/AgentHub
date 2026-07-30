from __future__ import annotations

from app.services.tasks.contracts import (
    CancellationReceipt,
    TaskCreationReceipt,
    TaskPlanMutationReceipt,
)


def render_task_creation(output: dict) -> str:
    try:
        receipt = TaskCreationReceipt.model_validate(output)
    except Exception:
        return ""
    if receipt.status == "blocked":
        if receipt.reason == "origin_request_conflict":
            return "同一请求已经对应另一个任务计划，因此没有创建新任务。"
        return "当前对话的所有权校验未通过，因此没有创建任务。"
    if receipt.created:
        return f"已创建任务，共 {receipt.step_count} 个步骤。"
    return (
        "本请求的任务已经存在，已复用原任务，"
        f"共 {receipt.step_count} 个步骤。"
    )


def render_task_mutation(output: dict) -> str:
    try:
        receipt = TaskPlanMutationReceipt.model_validate(output)
    except Exception:
        return ""
    if receipt.status == "blocked":
        if receipt.reason == "active_task_running":
            return "当前任务正在执行，需先安全暂停后才能修改计划。"
        if receipt.reason == "origin_request_conflict":
            return "同一请求已对应另一份任务计划，因此没有修改任务。"
        if receipt.reason == "multiple_active_tasks":
            return "检测到多个活动任务，需先完成系统侧一致性处理。"
        if receipt.reason == "ownership_mismatch":
            return "当前对话的所有权校验未通过，因此没有修改任务。"
        return "当前任务状态不允许修改计划。"
    if receipt.mutation == "created":
        return f"已创建任务，共 {receipt.step_count} 个步骤。"
    if receipt.mutation == "revised":
        return f"已更新任务计划，共 {receipt.step_count} 个步骤。"
    return (
        "本请求对应的任务计划已存在，已安全复用，"
        f"共 {receipt.step_count} 个步骤。"
    )


def render_task_cancellation(output: dict) -> str:
    try:
        receipt = CancellationReceipt.model_validate(output)
    except Exception:
        return ""
    if receipt.status == "completed":
        return "已取消当前活动任务。"
    if receipt.reason == "no_active_task":
        return "当前没有可取消的活动任务。"
    if receipt.reason == "multiple_active_tasks":
        return "检测到多个活动任务，暂未执行取消。"
    return "当前对话的所有权校验未通过，因此没有取消任务。"


__all__ = [
    "render_task_cancellation",
    "render_task_creation",
    "render_task_mutation",
]
