from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.memory.contracts import MemoryEvent


_NAME_VALUE = r"[\w\u4e00-\u9fff\u00b7\.\-]{1,32}"
_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"(?:我现在)?不叫{_NAME_VALUE}(?:了)?[，,\s]*(?:我现在)?叫(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:我的名字)?(?:改成|改为|改叫)(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:以后|今后)(?:请)?叫我(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|(?:你好|您好|嗨|哈喽)[，,\s]*)我是"
        rf"(?P<name>{_NAME_VALUE})(?=$|[，,。.!！?？\s])",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^\s*我是(?P<name>{_NAME_VALUE})\s*(?:[.!?。！？])?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:我叫|我的名字(?:叫|是))(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(rf"叫我(?P<name>{_NAME_VALUE})", re.IGNORECASE),
    re.compile(
        rf"我是(?P<name>{_NAME_VALUE})(?:\s|,|，)*(?:你)?(?:记住|记一下|记下)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:remember\s+(?:that\s+)?)?my\s+name\s+is\s+(?P<name>{_NAME_VALUE})",
        re.IGNORECASE,
    ),
    re.compile(rf"call\s+me\s+(?P<name>{_NAME_VALUE})", re.IGNORECASE),
)
_TRAILING_NOISE = re.compile(r"(?:你)?(?:记住|记一下|记下)$|你$", re.IGNORECASE)
_INVALID_NAMES = {
    "user",
    "me",
    "myself",
    "what",
    "who",
    "我",
    "用户",
    "一个人",
    "一个",
    "一名",
    "学生",
    "老师",
    "医生",
    "程序员",
    "工程师",
    "读者",
    "作者",
    "什么",
    "啥",
    "谁",
}


def extract_declared_name(text: str) -> str:
    """Extract the new asserted name, including explicit corrections."""

    normalized = " ".join(str(text or "").split()).strip()
    for pattern in _NAME_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        name = _TRAILING_NOISE.sub("", str(match.group("name") or "")).strip()
        name = name.strip(" \t\r\n,.;:!?，。！？；：“”‘’（）()[]{}")
        if is_valid_person_name(name):
            return name
    return ""


def is_valid_person_name(name: str) -> bool:
    normalized = str(name or "").strip()
    if not normalized or len(normalized) > 32:
        return False
    lowered = normalized.lower()
    if lowered.startswith(("一个", "一名")):
        return False
    return lowered not in _INVALID_NAMES


def resolve_current_name(memories: list[MemoryEvent]) -> str:
    """Select the newest committed, active name."""

    candidates: list[tuple[datetime, str]] = []
    for memory in memories:
        if (
            memory.forgotten
            or memory.superseded_by is not None
            or memory.state_status != "active"
        ):
            continue
        name = ""
        if memory.metadata.get("profile_key") == "name":
            name = memory.value.split(":", 1)[-1].strip()
        if not name:
            name = extract_declared_name(memory.raw_text or memory.value)
        if not is_valid_person_name(name):
            continue
        timestamp = (
            memory.updated_at
            or memory.created_at
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        candidates.append((timestamp, name))
    return max(
        candidates,
        default=(datetime.min.replace(tzinfo=timezone.utc), ""),
    )[1]
