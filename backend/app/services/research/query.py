from __future__ import annotations

import re


_ROUTING_PREFIX_RE = re.compile(
    r"^\s*(?:请|帮我|请帮我)?\s*(?:深度搜索|深度研究|搜索|搜一下|查一下|查询)"
    r"(?:一下|下)?\s*",
    re.IGNORECASE,
)
_ENGLISH_ROUTING_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:deep\s+(?:search|research)|search|look\s+up)\s+",
    re.IGNORECASE,
)


def normalize_research_query(text: str) -> str:
    """Remove routing commands while preserving the research subject."""

    normalized = " ".join(str(text or "").split()).strip()
    normalized = _ROUTING_PREFIX_RE.sub("", normalized, count=1)
    normalized = _ENGLISH_ROUTING_PREFIX_RE.sub("", normalized, count=1)
    return normalized.strip(" ，,。.!！?？") or " ".join(str(text or "").split()).strip()
