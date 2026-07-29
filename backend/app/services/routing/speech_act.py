"""Recognize the linguistic act of one user clause.

This module deliberately answers only *how the utterance is being used*.
It does not infer information dependencies, admit capabilities, or compile
operations.  In particular, words inside quoted examples are not treated as
requests addressed to the assistant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal


SpeechAct = Literal[
    "request",
    "explain",
    "summarize",
    "analyze_utterance",
    "translate",
    "classify_utterance",
    "generate_example",
    "compare",
    "social_response",
    "clarify_objective",
    "unknown",
]


_QUOTED_RE = re.compile(
    r"《[^》]*》|“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"]*\"|'[^']*'"
)
_ANALYZE_RE = re.compile(
    r"分析.+(?:这句话|意图|请求|表达)|(?:这句话|这个请求).*(?:为什么|意图|表达)",
    re.I,
)
_TRANSLATE_RE = re.compile(r"(?:翻译成|译成|translate\b)", re.I)
_CLASSIFY_RE = re.compile(r"(?:分类标签|归类|属于哪类|classif)", re.I)
_EXAMPLE_RE = re.compile(r"(?:代码示例|举例|示例里|example\b)", re.I)
_COMPARE_RE = re.compile(r"(?:比较|对比|区别|compare\b|difference\b)", re.I)
_SUMMARIZE_RE = re.compile(r"(?:概括|总结|摘要|summari[sz]e\b)", re.I)
_EXPLAIN_RE = re.compile(
    r"(?:^|[，,\s])(?:直接|只)?(?:解释|说明|告诉我).*(?:什么|如何|为什么|哪些|标准|区别)|"
    r"^(?:先)?(?:解释|说明)|(?:用一句话|简要)(?:解释|说明)|"
    r"^(?:什么是|为什么|为何|如何|怎么)|"
    r"\b(?:explain|what is|why|how)\b",
    re.I,
)
_GREETING_RE = re.compile(
    r"^(?:你好|您好|嗨|哈[喽啰]|早上好|下午好|晚上好|hello|hi|hey)[！!。.]*$",
    re.I,
)
_VAGUE_RE = re.compile(
    r"^(?:请)?(?:帮我)?(?:处理|弄|搞|查|查询)(?:一下)?[。.!！?？]*$|"
    r"^(?:请)?(?:给我)?推荐(?:点|一些)?(?:东西)?[。.!！?？]*$",
    re.I,
)
_GIBBERISH_ASCII_RE = re.compile(r"^(?:[a-z]{2,}\s+){2,}[a-z]{2,}$", re.I)


@dataclass(frozen=True)
class SpeechActAnalysis:
    act: SpeechAct
    outer_text: str
    metalinguistic: bool
    confidence: float
    reason: str


@lru_cache(maxsize=1024)
def analyze_speech_act(text: str) -> SpeechActAnalysis:
    normalized = " ".join(str(text or "").split()).strip()
    outer_text = _QUOTED_RE.sub("〈quoted〉", normalized)
    has_quote = outer_text != normalized

    # Meta-level acts must win before domain words inside quoted examples.
    if has_quote and _TRANSLATE_RE.search(outer_text):
        return _result("translate", outer_text, True, "quoted_translation_request")
    if has_quote and _EXAMPLE_RE.search(outer_text):
        return _result("generate_example", outer_text, True, "quoted_example_request")
    if has_quote and _COMPARE_RE.search(outer_text):
        return _result("compare", outer_text, True, "quoted_comparison_request")
    if has_quote and _ANALYZE_RE.search(outer_text):
        return _result(
            "analyze_utterance",
            outer_text,
            True,
            "quoted_utterance_analysis",
        )
    if has_quote and _CLASSIFY_RE.search(outer_text):
        return _result(
            "classify_utterance",
            outer_text,
            True,
            "quoted_classification_request",
        )
    if has_quote and re.search(r"(?:这句话|这个请求).*(?:为什么|意图|表达)", outer_text):
        return _result(
            "analyze_utterance",
            outer_text,
            True,
            "quoted_utterance_analysis",
        )

    if _GREETING_RE.fullmatch(normalized):
        return _result("social_response", outer_text, False, "social_greeting")
    if _VAGUE_RE.fullmatch(normalized):
        return _result(
            "clarify_objective",
            outer_text,
            False,
            "missing_request_object",
        )
    if _SUMMARIZE_RE.search(outer_text):
        return _result("summarize", outer_text, False, "explicit_summary_request")
    if _COMPARE_RE.search(outer_text):
        return _result("compare", outer_text, False, "explicit_comparison_request")
    if _EXPLAIN_RE.search(outer_text):
        return _result("explain", outer_text, False, "explicit_explanation_request")
    if _looks_unknown(normalized):
        return _result("unknown", outer_text, False, "uninterpretable_utterance", 0.98)
    return _result("request", outer_text, False, "ordinary_request", 0.90)


def _looks_unknown(text: str) -> bool:
    if not text:
        return True
    if _GIBBERISH_ASCII_RE.fullmatch(text):
        return True
    meaningful = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    return not meaningful


def _result(
    act: SpeechAct,
    outer_text: str,
    metalinguistic: bool,
    reason: str,
    confidence: float = 0.99,
) -> SpeechActAnalysis:
    return SpeechActAnalysis(
        act=act,
        outer_text=outer_text,
        metalinguistic=metalinguistic,
        confidence=confidence,
        reason=reason,
    )
