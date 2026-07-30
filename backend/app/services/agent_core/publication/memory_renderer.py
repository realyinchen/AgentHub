from __future__ import annotations


def render_memory_mutation(output: dict) -> str:
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


def render_memory_search(output: dict) -> str:
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


def render_memory_forget(output: dict) -> str:
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


def render_waiting(output: dict) -> str:
    for key in ("clarification_question", "question"):
        content = str(output.get(key) or "").strip()
        if content:
            return content
    return "本轮需要补充信息后才能继续。"


__all__ = [
    "render_memory_forget",
    "render_memory_mutation",
    "render_memory_search",
    "render_waiting",
]
