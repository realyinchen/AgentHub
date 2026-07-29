from __future__ import annotations

import re

from app.services.routing.interaction_contracts import PendingMemoryWriteContext


_NAME_TARGET_RE = re.compile(
    r"^(?:我的)?(?:名字|姓名|称呼)$|\bmy\s+name\b",
    re.IGNORECASE,
)
_SIMPLE_NAME_RE = re.compile(
    r"^[\w\u4e00-\u9fff\u00b7.\-]{1,32}$",
    re.IGNORECASE,
)
_DIRECT_FACT_RE = re.compile(
    r"^(?:我|my\b|i\b).+",
    re.IGNORECASE,
)
_QUESTION_OR_TASK_RE = re.compile(
    r"[?？]|(?:帮我|请你|查询|搜索|推荐|天气|怎么|如何|为什么)|"
    r"\b(?:search|find|recommend|weather|how|why|what)\b",
    re.IGNORECASE,
)
_NON_ANSWER_RE = re.compile(
    r"^(?:你好|您好|嗨|哈喽|谢谢|好的|好|嗯|哦|是|不是|"
    r"hello|hi|hey|thanks|thank you|yes|no)$",
    re.IGNORECASE,
)


def might_be_memory_clarification_answer(text: str) -> bool:
    """Cheap guard for deciding whether a checkpoint read may be necessary."""

    normalized = " ".join(str(text or "").split()).strip(" ，,。.!！")
    return bool(
        normalized
        and not _NON_ANSWER_RE.fullmatch(normalized)
        and not _QUESTION_OR_TASK_RE.search(normalized)
        and _SIMPLE_NAME_RE.fullmatch(normalized)
    )
def is_memory_clarification_answer(
    text: str,
    pending: PendingMemoryWriteContext | None,
) -> bool:
    """Return whether this turn is an answer to the immediately pending prompt."""

    if pending is None:
        return False
    normalized = " ".join(str(text or "").split()).strip(" ，,。.!！")
    if not normalized or _QUESTION_OR_TASK_RE.search(normalized):
        return False
    if pending.kind == "conflict":
        return False
    if _NAME_TARGET_RE.fullmatch(pending.target_expression):
        return might_be_memory_clarification_answer(normalized)
    return bool(_DIRECT_FACT_RE.match(normalized))
