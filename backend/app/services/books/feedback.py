from __future__ import annotations

import re
from typing import Any


_TITLE = r"[^。！？?,，；;\n\r]{1,80}"
_QUOTED_TITLE_RE = re.compile(
    r"(?:《(?P<cjk>[^《》]{1,80})》|[\"'](?P<quoted>[^\"']{1,80})[\"'])"
)
_READ_RE = re.compile(
    r"看过|读过|已读|读完|已经读|already\s+read|finished\s+reading|read\s+it",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"不感兴趣|没兴趣|不喜欢|讨厌|not\s+interested|dislike|hate",
    re.IGNORECASE,
)
_TITLE_AFTER_READ_RE = re.compile(
    rf"(?:我)?(?:已经)?(?:看过|读过|读完|已读)(?:了|过)?(?P<title>{_TITLE})",
    re.IGNORECASE,
)
_TITLE_AFTER_EN_READ_RE = re.compile(
    rf"\bi\s+(?:already\s+)?(?:read|finished(?:\s+reading)?)\s+(?P<title>{_TITLE})",
    re.IGNORECASE,
)
_TITLE_BEFORE_NEGATIVE_RE = re.compile(
    rf"(?:我)?(?:对)?(?P<title>{_TITLE})(?:不感兴趣|没兴趣|不喜欢|讨厌)",
    re.IGNORECASE,
)
_TITLE_AFTER_NEGATIVE_RE = re.compile(
    rf"(?:我)?(?:不感兴趣|没兴趣|不喜欢|讨厌)(?:这本|这本书)?(?P<title>{_TITLE})",
    re.IGNORECASE,
)


def extract_book_feedback(text: str) -> dict[str, Any]:
    """Extract explicit feedback for one concrete book."""

    normalized = " ".join(str(text or "").split()).strip()
    if not normalized or _looks_like_history_question(normalized):
        return {}
    quoted = _quoted_title(normalized)
    if quoted and _READ_RE.search(normalized):
        return _payload(quoted, "read")
    if quoted and _NEGATIVE_RE.search(normalized):
        return _payload(
            quoted,
            "disliked" if _is_dislike(normalized) else "not_interested",
        )
    for pattern in (_TITLE_AFTER_READ_RE, _TITLE_AFTER_EN_READ_RE):
        match = pattern.search(normalized)
        if match:
            title = _clean_title(match.group("title"))
            if _valid_title(title):
                return _payload(title, "read")
    for pattern in (_TITLE_BEFORE_NEGATIVE_RE, _TITLE_AFTER_NEGATIVE_RE):
        match = pattern.search(normalized)
        if match:
            title = _clean_title(match.group("title"))
            if _valid_title(title):
                return _payload(
                    title,
                    "disliked" if _is_dislike(normalized) else "not_interested",
                )
    return {}


def _payload(book_title: str, event_type: str) -> dict[str, Any]:
    interaction_type = "read"
    polarity = "neutral"
    strength = 1.0
    if event_type == "disliked":
        interaction_type = "dislike"
        polarity = "negative"
        strength = 0.9
    elif event_type == "not_interested":
        interaction_type = "not_interested"
        polarity = "negative"
        strength = 0.8
    return {
        "book_title": book_title,
        "event_type": event_type,
        "interaction_type": interaction_type,
        "signal_polarity": polarity,
        "signal_strength": strength,
        "writes_long_term_memory": True,
    }


def _looks_like_history_question(text: str) -> bool:
    question = any(marker in text for marker in ("?", "？", "哪些", "什么", "吗"))
    return question and bool(_READ_RE.search(text) or _NEGATIVE_RE.search(text))


def _quoted_title(text: str) -> str:
    match = _QUOTED_TITLE_RE.search(text)
    if match is None:
        return ""
    return _clean_title(match.group("cjk") or match.group("quoted") or "")


def _clean_title(value: str) -> str:
    title = " ".join(str(value or "").split()).strip()
    title = re.sub(r"^(?:了|过|这本|这本书|这部|这部书)", "", title)
    title = re.sub(r"(?:这本|这本书|这部|这部书)$", "", title)
    return title.strip(" \t\r\n,.;:!?，。；：！？\"'“”‘’（）()[]{}")


def _valid_title(title: str) -> bool:
    return bool(title) and len(title) <= 80 and title.lower() not in {
        "这本",
        "这本书",
        "这书",
        "这部",
        "它",
        "这个",
        "什么",
        "this",
        "it",
        "book",
        "this book",
    }


def _is_dislike(text: str) -> bool:
    return bool(re.search(r"不喜欢|讨厌|dislike|hate", text, re.IGNORECASE))

