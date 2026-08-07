from __future__ import annotations

from datetime import datetime
from typing import Any


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
    statuses = {str(item.get("status") or "") for item in mutations}
    if statuses == {"noop_duplicate"}:
        labels = [
            _value_label(item.get("version"))
            for item in mutations
            if isinstance(item.get("version"), dict)
        ]
        labels = [label for label in labels if label]
        if not labels:
            return "这条事实已经在长期记忆中，无需重复保存。"
        return "我已经记得：" + "；".join(labels) + "，无需重复保存。"

    lines: list[str] = []
    for mutation in mutations:
        mutation_status = str(mutation.get("status") or "")
        version = mutation.get("version")
        previous = mutation.get("previous")
        version_payload = version if isinstance(version, dict) else {}
        new_label = _value_label(version_payload)
        if mutation_status == "revised" and isinstance(previous, dict):
            old_label = _value_label(previous)
            kind = _fact_kind(version_payload)
            if new_label and old_label:
                lines.append(f"已把你的{kind}从{old_label}更新为{new_label}。")
                continue
        if mutation_status in {"created", "revised"} and new_label:
            lines.append(f"已记录长期记忆：{new_label}。")
    if lines:
        return "\n".join(lines)
    return "已根据你的最新表述更新长期记忆。"


def render_memory_search(output: dict) -> str:
    scope = str(output.get("scope") or "current")
    memories = [
        item for item in output.get("memories", []) if isinstance(item, dict)
    ]
    if not memories:
        if scope == "previous":
            return "我还没有找到更早之前的长期记忆。"
        if scope == "earliest":
            return "我还没有找到最早的长期记忆。"
        return "我还没有找到符合条件的长期记忆。"
    if scope == "timeline":
        return _render_timeline(memories, bool(output.get("truncated")))
    if scope in {"previous", "earliest"}:
        return _render_history_points(memories, scope)
    return _render_current(memories)


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
        return "这条事实已经处于遗忘状态，无需重复处理。"
    return "已按你的要求将这条长期记忆标记为遗忘。"


def render_waiting(output: dict) -> str:
    for key in ("clarification_question", "question"):
        content = str(output.get(key) or "").strip()
        if content:
            return content
    return "本轮需要补充信息后才能继续。"


def _render_current(memories: list[dict]) -> str:
    lines: list[str] = []
    for item in memories[:8]:
        line = _current_line(item)
        if line:
            lines.append(line)
    if not lines:
        return "我找到了长期记忆，但没有可安全展示的内容。"
    return "我记得：\n\n" + "\n".join(f"- {line}" for line in lines)


def _render_history_points(memories: list[dict], scope: str) -> str:
    by_key: dict[str, list[dict]] = {}
    for item in memories:
        by_key.setdefault(str(item.get("memory_key") or ""), []).append(item)
    lines: list[str] = []
    for items in by_key.values():
        line = _history_line(items, scope)
        if line:
            lines.append(line)
    if not lines:
        if scope == "previous":
            return "我还没有找到更早之前的长期记忆。"
        return "我还没有找到最早的长期记忆。"
    return "\n".join(lines)


def _render_timeline(memories: list[dict], truncated: bool) -> str:
    by_key: dict[str, list[dict]] = {}
    for item in memories:
        by_key.setdefault(str(item.get("memory_key") or ""), []).append(item)
    lines: list[str] = []
    for items in by_key.values():
        ordered = sorted(
            items,
            key=lambda item: str(item.get("valid_from") or ""),
        )
        line = _timeline_line(ordered)
        if line:
            lines.append(line)
    if not lines:
        return "我还没有找到符合条件的历史记录。"
    body = "\n".join(lines)
    if truncated:
        body += "\n（仅显示最近记录）"
    return body


def _history_line(items: list[dict], scope: str) -> str:
    schema_key = str(items[0].get("schema_key") or "")
    ordered = sorted(
        items,
        key=lambda item: int(item.get("version_no") or 0),
        reverse=scope == "previous",
    )
    if schema_key == "identity.self_reported_name":
        names = [
            _value_label(item)
            for item in ordered
            if not item.get("is_tombstone")
        ]
        names = [name for name in names if name]
        if not names:
            return ""
        if scope == "earliest":
            return f"你最早叫{names[0]}。"
        if len(names) == 1:
            return f"你之前叫{names[0]}。"
        return "你之前叫" + names[0] + "；更早叫" + "、".join(names[1:]) + "。"
    entities = [
        _value_label(item)
        for item in ordered
        if not item.get("is_tombstone")
    ]
    entities = [entity for entity in entities if entity]
    if not entities:
        return ""
    if scope == "earliest":
        return f"你最早有{entities[0]}。"
    return "你之前有" + "、".join(entities) + "。"


def _timeline_line(ordered: list[dict]) -> str:
    schema_key = str(ordered[0].get("schema_key") or "")
    if schema_key == "identity.self_reported_name":
        segments: list[str] = []
        for item in ordered:
            label = _value_label(item)
            if not label:
                continue
            if item.get("is_tombstone"):
                continue
            if item.get("superseded_by") is None:
                segments.append(f"{label}（当前）")
            else:
                segments.append(label)
        if not segments:
            return ""
        return "你的名字变更：" + " → ".join(segments) + "。"

    lines: list[str] = []
    for item in ordered:
        label = _value_label(item)
        if not label:
            continue
        started = _short_date(item.get("valid_from"))
        ended = _short_date(item.get("valid_to"))
        if item.get("is_tombstone"):
            lines.append(f"{label}（{started} 起，已不再持有）")
        elif ended:
            lines.append(f"{label}（{started} 至 {ended}）")
        else:
            lines.append(f"{label}（{started} 起）")
    return "；".join(lines)


def _current_line(item: dict) -> str:
    schema_key = str(item.get("schema_key") or "")
    value = item.get("value") if isinstance(item.get("value"), dict) else {}
    qualifiers = (
        item.get("qualifiers") if isinstance(item.get("qualifiers"), dict) else {}
    )
    if schema_key == "identity.self_reported_name":
        name = str(value.get("name") or "").strip()
        return f"你的名字是{name}。" if name else ""
    if schema_key == "identity.preferred_address":
        address = str(value.get("address") or "").strip()
        return f"你希望我称呼你为{address}。" if address else ""
    if schema_key == "identity.alias":
        alias = str(value.get("alias") or "").strip()
        return f"你的别名是{alias}。" if alias else ""
    if schema_key == "possession.entity":
        entity = str(value.get("entity") or qualifiers.get("entity") or "").strip()
        return f"你有{entity}。" if entity else ""
    if schema_key == "preference.entity":
        entity = str(value.get("entity") or "").strip()
        polarity = str(value.get("polarity") or "").lower()
        verb = {
            "like": "喜欢",
            "dislike": "不喜欢",
            "want": "想要",
            "avoid": "想避免",
            "neutral": "偏好",
        }.get(polarity, "偏好")
        return f"你{verb}{entity}。" if entity else ""
    if schema_key == "relationship.entity":
        entity = str(value.get("entity") or "").strip()
        relation = str(value.get("relation") or "").strip()
        if entity and relation:
            return f"你和{entity}的关系：{relation}。"
    quote = str(item.get("evidence_quote") or "").strip()
    return quote


def _fact_kind(version: dict) -> str:
    schema_key = str(version.get("schema_key") or "")
    if schema_key == "identity.self_reported_name":
        return "名字"
    if schema_key == "identity.preferred_address":
        return "称呼"
    if schema_key == "identity.alias":
        return "别名"
    if schema_key == "possession.entity":
        return "拥有记录"
    if schema_key == "preference.entity":
        return "喜好"
    if schema_key == "relationship.entity":
        return "关系"
    if schema_key == "instruction.behavior":
        return "行为约定"
    if schema_key == "feedback.outcome":
        return "反馈"
    return "状态"


def _value_label(version: dict) -> str:
    if not isinstance(version, dict):
        return ""
    schema_key = str(version.get("schema_key") or "")
    value = version.get("value") if isinstance(version.get("value"), dict) else {}
    qualifiers = (
        version.get("qualifiers")
        if isinstance(version.get("qualifiers"), dict)
        else {}
    )
    if schema_key == "identity.self_reported_name":
        return str(value.get("name") or "").strip()
    if schema_key == "identity.preferred_address":
        return str(value.get("address") or "").strip()
    if schema_key == "identity.alias":
        return str(value.get("alias") or "").strip()
    entity = str(value.get("entity") or qualifiers.get("entity") or "").strip()
    if entity:
        return entity
    for key in ("instruction", "target", "state", "outcome"):
        label = str(value.get(key) or "").strip()
        if label:
            return label
    return str(version.get("evidence_quote") or "").strip()


def _short_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value or "")
    return text[:10] if text else ""


__all__ = [
    "render_memory_forget",
    "render_memory_mutation",
    "render_memory_search",
    "render_waiting",
]
