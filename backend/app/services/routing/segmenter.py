from __future__ import annotations

import re

from app.services.routing.interaction_contracts import (
    ClausePolarity,
    ClauseRelation,
    GoalClause,
)


_HARD_BOUNDARIES = frozenset("。！？!?；;\n")
_SOFT_BOUNDARIES = frozenset("，,")
_OPEN_TO_CLOSE = {"“": "”", '"': '"', "'": "'", "《": "》", "「": "」", "『": "』"}
_RELATION_PREFIXES: tuple[tuple[re.Pattern[str], ClauseRelation], ...] = (
    (re.compile(r"^(?:然后|接着|之后|随后|再|then\b)\s*", re.I), "then"),
    (re.compile(r"^(?:同时|并且|以及|而且|另外|and\b)\s*", re.I), "and"),
    (re.compile(r"^(?:但是|但请|但|不过|然而|but\b)\s*", re.I), "contrast"),
    (re.compile(r"^(?:如果|只要|when\b|if\b)\s*", re.I), "condition"),
)
_NEGATIVE_RE = re.compile(
    r"(?:^|\s)(?:先别|不要|别|无需|不用|不需要|禁止|请勿|不能|不必|"
    r"do\s+not\b|don't\b|never\b|without\b)",
    re.I,
)
_POSITIVE_AFTER_COMMA_RE = re.compile(
    r"^(?:直接|只解释|只说明|用常识|请|帮我|告诉我|解释|推荐|查|搜索|记住|"
    r"更新|修改|删除|添加|然后|接着|再|同时|并且|但是|但请|但|不过|"
    r"if\b|then\b|please\b)",
    re.I,
)
_QUOTED_RE = re.compile(r"《([^》]+)》|“([^”]+)”|「([^」]+)」|\"([^\"]+)\"")


class UtteranceSegmenter:
    """Quote-aware splitter. It extracts clauses but never assigns intent."""

    def segment(self, text: str) -> list[GoalClause]:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            raise ValueError("utterance cannot be empty")
        pieces = _split_quote_aware(normalized)
        return [
            _to_clause(piece, ordinal=index)
            for index, piece in enumerate(pieces)
            if piece.strip()
        ]


def segment_utterance(text: str) -> list[GoalClause]:
    return UtteranceSegmenter().segment(text)


def _split_quote_aware(text: str) -> list[str]:
    pieces: list[str] = []
    buffer: list[str] = []
    quote_stack: list[str] = []
    for index, char in enumerate(text):
        if char in _OPEN_TO_CLOSE:
            expected = _OPEN_TO_CLOSE[char]
            if quote_stack and char == expected:
                quote_stack.pop()
            elif char in {'"', "'"} and quote_stack and quote_stack[-1] == char:
                quote_stack.pop()
            else:
                quote_stack.append(expected)
            buffer.append(char)
            continue
        if quote_stack and char == quote_stack[-1]:
            quote_stack.pop()
            buffer.append(char)
            continue
        if quote_stack:
            buffer.append(char)
            continue
        if char in _HARD_BOUNDARIES:
            _flush(pieces, buffer)
            continue
        if char in _SOFT_BOUNDARIES:
            remainder = text[index + 1 :].lstrip()
            if _POSITIVE_AFTER_COMMA_RE.search(remainder):
                _flush(pieces, buffer)
                continue
        buffer.append(char)
    _flush(pieces, buffer)
    return pieces or [text]


def _flush(pieces: list[str], buffer: list[str]) -> None:
    value = "".join(buffer).strip()
    buffer.clear()
    if value:
        pieces.append(value)


def _to_clause(text: str, *, ordinal: int) -> GoalClause:
    relation: ClauseRelation = "root" if ordinal == 0 else "and"
    clean = text.strip()
    for pattern, candidate_relation in _RELATION_PREFIXES:
        match = pattern.search(clean)
        if match is None:
            continue
        relation = candidate_relation
        stripped = clean[match.end() :].strip()
        if stripped:
            clean = stripped
        break
    negative = bool(_NEGATIVE_RE.search(clean))
    affirmative = bool(
        re.search(r"(?:直接|需要|请|帮我|我要|想要|please|need|want)", clean, re.I)
    )
    polarity: ClausePolarity
    if negative and affirmative:
        polarity = "mixed"
    elif negative:
        polarity = "negative"
    else:
        polarity = "affirmative"
    quoted_spans = [
        next(group for group in match.groups() if group is not None)
        for match in _QUOTED_RE.finditer(clean)
    ]
    return GoalClause(
        clause_id=f"c{ordinal + 1:02d}",
        text=clean,
        ordinal=ordinal,
        relation=relation,
        polarity=polarity,
        quoted_spans=quoted_spans,
    )
