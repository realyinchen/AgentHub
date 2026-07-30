from __future__ import annotations

import re

from app.services.agent_core.contracts import ControllerOutput, PublishedAnswer
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.tasks.contracts import (
    CancellationReceipt,
    TaskCreationReceipt,
    TaskPlanMutationReceipt,
)


_SUCCESS_CLAIM_RE = re.compile(
    r"(?:已|已经)(?:记录|保存|更新|修改|删除|忘记|创建)"
)


class ResponsePublisher:
    """Publish only direct text or claims proven by runtime receipts."""

    def publish_direct(self, output: ControllerOutput) -> PublishedAnswer:
        if output.mode not in {"direct_answer", "request_clarification"}:
            raise ValueError("direct publication requires a text controller mode")
        if _SUCCESS_CLAIM_RE.search(output.text):
            raise ValueError(
                "side-effect success claims require a runtime receipt"
            )
        return PublishedAnswer(
            status=(
                "clarification_required"
                if output.mode == "request_clarification"
                else "completed"
            ),
            content=output.text.strip(),
            receipt_backed=False,
        )

    def publish_receipt(
        self,
        plan: ActionPlan,
        receipt: PlanReceipt,
        *,
        draft: str = "",
    ) -> PublishedAnswer:
        if receipt.plan_id != plan.plan_id:
            raise ValueError("receipt does not belong to the supplied plan")
        refs = [
            item.action_id
            for item in receipt.actions
            if item.status == "completed"
        ]
        if draft.strip():
            if _SUCCESS_CLAIM_RE.search(draft) and not _proves_mutation(
                receipt
            ):
                raise ValueError(
                    "draft contains an unreceipted side-effect success claim"
                )
            return PublishedAnswer(
                status=(
                    "completed"
                    if receipt.status in {"completed", "partial"}
                    else "failed"
                ),
                content=draft.strip(),
                receipt_backed=True,
                receipt_refs=refs,
        )

        for action in reversed(receipt.actions):
            if action.operation == "plan_task_v1" and isinstance(
                action.output,
                dict,
            ):
                mutation = _parse_task_mutation(action.output)
                if mutation is not None and mutation.status == "blocked":
                    return PublishedAnswer(
                        status="failed",
                        content=_render_task_mutation(mutation),
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.operation == "cancel_active_task_v1" and isinstance(
                action.output,
                dict,
            ):
                cancellation = _parse_task_cancellation(action.output)
                if (
                    cancellation is not None
                    and cancellation.status == "blocked"
                ):
                    return PublishedAnswer(
                        status="failed",
                        content=_render_task_cancellation(cancellation),
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.operation == "create_task_v1" and isinstance(
                action.output,
                dict,
            ):
                task_receipt = _parse_task_creation(action.output)
                if task_receipt is not None and task_receipt.status == "blocked":
                    return PublishedAnswer(
                        status="failed",
                        content=_render_task_creation(task_receipt),
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.status == "waiting" and isinstance(action.output, dict):
                if action.operation == "remember_memory_v2":
                    content = _render_memory_mutation(action.output)
                elif action.operation == "forget_memory_v2":
                    content = _render_memory_forget(action.output)
                else:
                    content = _render_waiting(action.output)
                return PublishedAnswer(
                    status="clarification_required",
                    content=content,
                    receipt_backed=True,
                    receipt_refs=[action.action_id],
                )
            if action.status != "completed" or not isinstance(action.output, dict):
                continue
            if action.operation == "conversation_read":
                answer = str(action.output.get("answer") or "").strip()
                if answer:
                    return PublishedAnswer(
                        status="completed",
                        content=answer,
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.operation == "remember_memory_v2":
                content = _render_memory_mutation(action.output)
                if content:
                    return PublishedAnswer(
                        status=(
                            "clarification_required"
                            if action.output.get("status")
                            == "clarification_required"
                            else "completed"
                        ),
                        content=content,
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.operation == "search_memory_v2":
                return PublishedAnswer(
                    status="completed",
                    content=_render_memory_search(action.output),
                    receipt_backed=True,
                    receipt_refs=[action.action_id],
                )
            if action.operation == "forget_memory_v2":
                content = _render_memory_forget(action.output)
                if content:
                    return PublishedAnswer(
                        status=(
                            "clarification_required"
                            if action.output.get("status")
                            == "clarification_required"
                            else "completed"
                        ),
                        content=content,
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.operation == "create_task_v1":
                task_receipt = _parse_task_creation(action.output)
                if task_receipt is not None:
                    return PublishedAnswer(
                        status="completed",
                        content=_render_task_creation(task_receipt),
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.operation == "plan_task_v1":
                mutation = _parse_task_mutation(action.output)
                if mutation is not None:
                    return PublishedAnswer(
                        status="completed",
                        content=_render_task_mutation(mutation),
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )
            if action.operation == "cancel_active_task_v1":
                cancellation = _parse_task_cancellation(action.output)
                if cancellation is not None:
                    return PublishedAnswer(
                        status="completed",
                        content=_render_task_cancellation(cancellation),
                        receipt_backed=True,
                        receipt_refs=[action.action_id],
                    )

        return PublishedAnswer(
            status="failed",
            content="本轮操作没有形成可发布的完整结果。",
            receipt_backed=True,
            receipt_refs=refs,
        )


def _proves_mutation(receipt: PlanReceipt) -> bool:
    mutation_operations = {
        "remember_memory",
        "remember_memory_v2",
        "process_memory_write_request",
        "forget_memory",
        "forget_memory_v2",
        "create_task_v1",
        "plan_task_v1",
        "cancel_active_task_v1",
    }
    return any(
        item.status == "completed" and item.operation in mutation_operations
        for item in receipt.actions
    )


def _render_memory_mutation(output: dict) -> str:
    status = str(output.get("status") or "")
    if status == "clarification_required":
        return str(output.get("clarification_question") or "").strip() or (
            "我还不能确定要保存的完整事实，请再说明一下。"
        )
    if status == "rejected":
        return "这条信息未通过长期记忆校验，因此没有保存。"
    mutations = [
        item for item in output.get("mutations", []) if isinstance(item, dict)
    ]
    if not mutations:
        return ""
    summaries: list[str] = []
    for mutation in mutations:
        version = mutation.get("version")
        version_payload = version if isinstance(version, dict) else {}
        quote = str(version_payload.get("evidence_quote") or "").strip()
        if quote and quote not in summaries:
            summaries.append(quote)
    rendered = "；".join(summaries)
    mutation_statuses = {
        str(item.get("status") or "") for item in mutations
    }
    if mutation_statuses == {"noop_duplicate"}:
        return (
            f"我已经记得：{rendered}，不需要重复保存。"
            if rendered
            else "这条事实已经在长期记忆中，不需要重复保存。"
        )
    if "revised" in mutation_statuses:
        return (
            f"已根据你的最新表述更新长期记忆：{rendered}。"
            if rendered
            else "已根据你的最新表述更新长期记忆。"
        )
    return (
        f"已记录长期记忆：{rendered}。"
        if rendered
        else "已记录这条长期记忆。"
    )


def _render_memory_search(output: dict) -> str:
    memories = [
        item for item in output.get("memories", []) if isinstance(item, dict)
    ]
    if not memories:
        return "我还没有找到符合条件的长期记忆。"
    lines: list[str] = []
    for item in memories[:8]:
        schema_key = str(item.get("schema_key") or "")
        value = item.get("value")
        payload = value if isinstance(value, dict) else {}
        if schema_key == "identity.self_reported_name":
            name = str(payload.get("name") or "").strip()
            if name:
                lines.append(f"你的名字是{name}")
                continue
        if schema_key == "identity.preferred_address":
            address = str(payload.get("address") or "").strip()
            if address:
                lines.append(f"你希望我称呼你为{address}")
                continue
        quote = str(item.get("evidence_quote") or "").strip()
        if quote:
            lines.append(quote)
    if not lines:
        return "我找到了长期记忆，但没有可安全展示的内容。"
    return "我记得：\n\n" + "\n".join(f"- {line}" for line in lines)


def _render_memory_forget(output: dict) -> str:
    status = str(output.get("status") or "")
    if status == "clarification_required":
        return str(output.get("clarification_question") or "").strip() or (
            "我还不能唯一确定你希望忘记的事实。"
        )
    if status == "rejected":
        return "这次遗忘请求没有通过来源与目标校验。"
    mutations = [
        item for item in output.get("mutations", []) if isinstance(item, dict)
    ]
    if not mutations:
        return ""
    if all(
        str(item.get("status") or "") == "noop_duplicate"
        for item in mutations
    ):
        return "这条事实已经处于遗忘状态，不需要重复处理。"
    return "已按你的要求将这条长期记忆标记为遗忘。"


def _render_waiting(output: dict) -> str:
    for key in ("clarification_question", "question"):
        content = str(output.get(key) or "").strip()
        if content:
            return content
    return "本轮需要补充信息后才能继续。"


def _parse_task_creation(output: dict) -> TaskCreationReceipt | None:
    try:
        return TaskCreationReceipt.model_validate(output)
    except Exception:
        return None


def _render_task_creation(receipt: TaskCreationReceipt) -> str:
    if receipt.status == "blocked":
        if receipt.reason == "origin_request_conflict":
            return "同一请求已经对应另一个任务计划，因此没有创建新任务。"
        return "当前对话的所有权校验未通过，因此没有创建任务。"
    if receipt.created:
        return f"已创建任务，共 {receipt.step_count} 个步骤。"
    return f"本请求的任务已经存在，已复用原任务，共 {receipt.step_count} 个步骤。"


def _parse_task_mutation(output: dict) -> TaskPlanMutationReceipt | None:
    try:
        return TaskPlanMutationReceipt.model_validate(output)
    except Exception:
        return None


def _render_task_mutation(receipt: TaskPlanMutationReceipt) -> str:
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
    return f"本请求对应的任务计划已存在，已安全复用，共 {receipt.step_count} 个步骤。"


def _parse_task_cancellation(output: dict) -> CancellationReceipt | None:
    try:
        return CancellationReceipt.model_validate(output)
    except Exception:
        return None


def _render_task_cancellation(receipt: CancellationReceipt) -> str:
    if receipt.status == "completed":
        return "已取消当前活动任务。"
    if receipt.reason == "no_active_task":
        return "当前没有可取消的活动任务。"
    if receipt.reason == "multiple_active_tasks":
        return "检测到多个活动任务，暂未执行取消。"
    return "当前对话的所有权校验未通过，因此没有取消任务。"
