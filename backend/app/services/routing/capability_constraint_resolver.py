from __future__ import annotations

import re

from app.services.routing.interaction_contracts import (
    AbstractCapability,
    GoalClause,
)


_BOOK_CATALOG_PROHIBITION_RE = re.compile(
    r"不要(?:替我)?(?:找书|推荐)|别(?:找书|推荐)|不用(?:找书|推荐)|"
    r"无需(?:找书|推荐)|do not recommend|don't recommend|without recommendations",
    re.I,
)
_DECOMPOSITION_PROHIBITION_RE = re.compile(
    r"(?:不用|无需|不要|禁止)(?:做)?(?:深度研究|深度搜索|拆解|分解|分步骤)|"
    r"do not (?:research deeply|decompose)|without (?:deep research|decomposition)",
    re.I,
)
_EXTERNAL_PROHIBITION_RE = re.compile(
    r"(?:不要|别|无需|不用|禁止|请勿).*(?:搜索|联网|查网|查天气)|"
    r"(?:不用|无需|不要).*(?:深度研究|深度搜索)|用常识|"
    r"do not (?:search|browse)|don't (?:search|browse)|without browsing",
    re.I,
)
_MEMORY_READ_PROHIBITION_RE = re.compile(
    r"(?:不要|别|禁止|请勿).*(?:读取|查询|查|使用).*(?:记忆|偏好|历史|身份)|"
    r"do not (?:read|use|search).*(?:memory|preference|history)",
    re.I,
)
_MEMORY_WRITE_PROHIBITION_RE = re.compile(
    r"(?:不要|别|禁止|请勿).*(?:记住|保存|写入记忆)|"
    r"(?:不要执行|别执行).*[“\"].*(?:记住|保存)|"
    r"do not (?:remember|save)|don't (?:remember|save)",
    re.I,
)


class CapabilityConstraintResolver:
    """Extract explicit abstract capability prohibitions from one clause."""

    def resolve(self, clause: GoalClause) -> list[AbstractCapability]:
        prohibited: list[AbstractCapability] = []
        if _EXTERNAL_PROHIBITION_RE.search(clause.text):
            prohibited.extend(["external_information", "current_information"])
        if _MEMORY_READ_PROHIBITION_RE.search(clause.text):
            prohibited.append("long_term_memory_read")
        if _MEMORY_WRITE_PROHIBITION_RE.search(clause.text):
            prohibited.append("memory_persistence")
        if _BOOK_CATALOG_PROHIBITION_RE.search(clause.text):
            prohibited.append("book_catalog_search")
        if _DECOMPOSITION_PROHIBITION_RE.search(clause.text):
            prohibited.append("decomposition")
        return list(dict.fromkeys(prohibited))
