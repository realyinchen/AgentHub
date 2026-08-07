from __future__ import annotations

from app.services.agent_core.contracts import PublishedAnswer
from app.services.agent_core.publication.memory_renderer import (
    render_memory_forget,
    render_memory_mutation,
    render_memory_search,
    render_waiting,
)
from app.services.agent_core.publication.task_renderer import (
    render_task_cancellation,
    render_task_creation,
    render_task_mutation,
)
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    PlanReceipt,
)


class DeterministicReceiptRenderer:
    """Render typed receipts; it never interprets model prose."""

    def render(
        self,
        plan: ActionPlan,
        receipt: PlanReceipt,
    ) -> PublishedAnswer:
        if receipt.plan_id != plan.plan_id:
            raise ValueError("receipt does not belong to the supplied plan")
        if plan.response_mode not in {"deterministic", "receipt"}:
            raise ValueError(
                "deterministic renderer requires a receipt response mode"
            )
        waiting = next(
            (
                item
                for item in receipt.actions
                if item.status == "waiting"
            ),
            None,
        )
        if waiting is not None:
            return PublishedAnswer(
                status="clarification_required",
                content=_render_waiting_action(waiting),
                receipt_backed=True,
                receipt_refs=[waiting.action_id],
                publication_mode="deterministic_receipt",
            )

        rendered: list[tuple[str, str]] = []
        for action in receipt.actions:
            content = _render_action(action)
            if content:
                rendered.append((action.action_id, content))
        if rendered:
            rendered = _select_readable(rendered, receipt)
            status = (
                "completed"
                if receipt.status in {"completed", "partial"}
                else "failed"
            )
            return PublishedAnswer(
                status=status,
                content="\n\n".join(
                    dict.fromkeys(content for _, content in rendered)
                ),
                receipt_backed=True,
                receipt_refs=list(
                    dict.fromkeys(action_id for action_id, _ in rendered)
                ),
                publication_mode="deterministic_receipt",
            )

        refs = [
            item.action_id
            for item in receipt.actions
            if item.status == "completed"
        ]
        return PublishedAnswer(
            status="failed",
            content="本轮操作没有形成可发布的完整结果。",
            receipt_backed=True,
            receipt_refs=refs,
            publication_mode="deterministic_receipt",
        )


def _render_waiting_action(action: ActionReceipt) -> str:
    output = action.output if isinstance(action.output, dict) else {}
    if action.operation == "remember_memory_v2":
        return render_memory_mutation(output)
    if action.operation == "forget_memory_v2":
        return render_memory_forget(output)
    return render_waiting(output)


def _render_action(action: ActionReceipt) -> str:
    output = action.output if isinstance(action.output, dict) else {}
    if action.status == "waiting":
        return _render_waiting_action(action)
    if action.operation == "plan_task_v1":
        return render_task_mutation(output)
    if action.operation == "cancel_active_task_v1":
        return render_task_cancellation(output)
    if action.operation == "create_task_v1":
        return render_task_creation(output)
    if action.status != "completed":
        return ""
    if action.operation == "conversation_read":
        return str(output.get("answer") or "").strip()
    if action.operation == "remember_memory_v2":
        return render_memory_mutation(output)
    if action.operation == "search_memory_v2":
        return render_memory_search(output)
    if action.operation == "forget_memory_v2":
        return render_memory_forget(output)
    return ""


def _select_readable(
    rendered: list[tuple[str, str]],
    receipt: PlanReceipt,
) -> list[tuple[str, str]]:
    """Deterministic source priority for read-only combinations.

    Durable long-term memory answers win over recent-transcript reads so
    questions such as "我之前叫什么" never degrade into a raw concatenation
    of conversation_read plus search_memory receipts.
    """

    by_id = {item.action_id: item for item in receipt.actions}
    search_items = [
        (action_id, content)
        for action_id, content in rendered
        if by_id.get(action_id) is not None
        and by_id[action_id].operation == "search_memory_v2"
    ]
    if search_items and any(
        not _empty_memory_search(content) for _, content in search_items
    ):
        return search_items
    conversation_items = [
        (action_id, content)
        for action_id, content in rendered
        if by_id.get(action_id) is not None
        and by_id[action_id].operation == "conversation_read"
    ]
    if conversation_items:
        return conversation_items
    return rendered


def _empty_memory_search(content: str) -> bool:
    return str(content or "").startswith("我还没有找到")


__all__ = ["DeterministicReceiptRenderer"]
