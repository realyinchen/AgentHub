from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.services.research.contracts import normalize_text


MAX_PUBLISHABLE_CLAIM_CHARS = 320

_MARKETPLACE_HOST_MARKERS = (
    "taobao.",
    "tmall.",
    "jd.com",
    "pinduoduo.",
    "dangdang.",
    "amazon.",
)
_REVIEW_HOST_MARKERS = ("douban.", "goodreads.", "book.douban.")
_SCHOLARLY_HOST_MARKERS = (
    "doi.org",
    "arxiv.org",
    "pubmed.",
    "semanticscholar.",
    "scholar.google.",
)
_SOCIAL_HOST_MARKERS = (
    "weibo.",
    "xiaohongshu.",
    "zhihu.",
    "reddit.",
)
_COMMERCIAL_MARKERS = (
    "正版",
    "现货",
    "包邮",
    "旗舰店",
    "购买",
    "销量",
    "折扣",
    "优惠",
    "到手价",
    "库存",
    "淘宝",
    "天猫",
    "京东",
)
_QUERY_STOP_TERMS = {
    "一下",
    "帮我",
    "请问",
    "深度",
    "搜索",
    "研究",
    "查找",
    "查询",
    "看看",
    "关于",
    "一个",
}


class EvidenceQualityAssessment(BaseModel):
    """Publishability assessment independent from evidence persistence."""

    provenance_valid: bool = False
    content_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    query_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    source_class: str = "unknown"
    publishable: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def assess_evidence_candidate(
    *,
    claim: str,
    query: str = "",
    source_title: str = "",
    source_url: str = "",
    published_date: str = "",
) -> EvidenceQualityAssessment:
    """Assess whether one source-backed string may enter answer synthesis."""

    normalized_claim = " ".join(normalize_text(claim).split())
    normalized_query = " ".join(normalize_text(query).split())
    normalized_title = " ".join(normalize_text(source_title).split())
    normalized_url = normalize_text(source_url)
    normalized_published_date = normalize_text(published_date)
    source_class = classify_source(normalized_url)
    reasons: list[str] = []

    provenance_valid = bool(normalized_title or normalized_url)
    if not provenance_valid:
        reasons.append("missing_source_metadata")

    claim_length = len(normalized_claim)
    if claim_length < 12:
        reasons.append("claim_too_short")
    if claim_length > MAX_PUBLISHABLE_CLAIM_CHARS:
        reasons.append("claim_too_long")

    sentence_count = len(
        [
            part
            for part in re.split(r"[.!?。！？；;]+", normalized_claim)
            if part.strip()
        ]
    )
    if sentence_count > 3:
        reasons.append("claim_not_atomic")

    commercial_hits = sum(
        normalized_claim.count(marker)
        for marker in _COMMERCIAL_MARKERS
    )
    separator_count = len(re.findall(r"[/|·•【】\[\]（）()]", normalized_claim))
    if commercial_hits >= 3 or separator_count >= 12:
        reasons.append("keyword_stuffing")

    if source_class == "marketplace":
        reasons.append("marketplace_source")

    query_relevance = _query_relevance(
        normalized_query,
        f"{normalized_title} {normalized_claim}",
        published_date=normalized_published_date,
    )
    if normalized_query and query_relevance <= 0:
        reasons.append("query_irrelevant")
    reasons.extend(
        _requirement_reasons(
            query=normalized_query,
            candidate_text=f"{normalized_title} {normalized_claim}",
            published_date=normalized_published_date,
        )
    )

    blocking = {
        "missing_source_metadata",
        "claim_too_short",
        "claim_too_long",
        "claim_not_atomic",
        "keyword_stuffing",
        "marketplace_source",
        "query_irrelevant",
        "missing_recency_evidence",
        "missing_review_evidence",
        "missing_book_evidence",
    }
    publishable = not blocking.intersection(reasons)
    content_penalty = (
        int("claim_too_short" in reasons) * 0.35
        + int("claim_too_long" in reasons) * 0.55
        + int("claim_not_atomic" in reasons) * 0.35
        + int("keyword_stuffing" in reasons) * 0.65
    )
    content_quality = max(0.0, min(1.0, 1.0 - content_penalty))
    return EvidenceQualityAssessment(
        provenance_valid=provenance_valid,
        content_quality=round(content_quality, 3),
        query_relevance=round(query_relevance, 3),
        source_class=source_class,
        publishable=publishable,
        reason_codes=_unique(reasons),
        metadata={
            "claim_chars": claim_length,
            "sentence_count": sentence_count,
            "commercial_marker_count": commercial_hits,
            "list_separator_count": separator_count,
            "published_date": normalized_published_date,
        },
    )


def classify_source(source_url: str) -> str:
    host = _source_host(source_url)
    if not host:
        return "unknown"
    if any(marker in host for marker in _MARKETPLACE_HOST_MARKERS):
        return "marketplace"
    if any(marker in host for marker in _REVIEW_HOST_MARKERS):
        return "review"
    if any(marker in host for marker in _SCHOLARLY_HOST_MARKERS):
        return "scholarly"
    if any(marker in host for marker in _SOCIAL_HOST_MARKERS):
        return "social"
    if host.endswith(".gov") or ".gov." in host:
        return "official"
    if host.endswith(".edu") or ".edu." in host:
        return "scholarly"
    return "editorial"


def source_quality(source_class: str) -> str:
    return {
        "official": "high",
        "scholarly": "high",
        "editorial": "medium",
        "review": "medium",
        "social": "low",
        "marketplace": "low",
        "unknown": "unknown",
    }.get(source_class, "unknown")


def source_host(source_url: str) -> str:
    return _source_host(source_url)


def _source_host(source_url: str) -> str:
    value = normalize_text(source_url).strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return str(parsed.hostname or "").lower()


def _query_relevance(
    query: str,
    candidate_text: str,
    *,
    published_date: str = "",
) -> float:
    if not query:
        return 1.0
    terms = _query_terms(query)
    if not terms:
        return 1.0
    lowered = candidate_text.lower()
    matches = sum(1 for term in terms if term in lowered)
    lexical = min(1.0, matches / max(1, min(len(terms), 4)))
    semantic = _requirement_relevance(
        query=query,
        candidate_text=candidate_text,
        published_date=published_date,
    )
    return max(lexical, semantic)


def _requirement_relevance(
    *,
    query: str,
    candidate_text: str,
    published_date: str,
) -> float:
    required: list[str] = []
    lowered_query = query.lower()
    if re.search(r"最新|近期|最近|新书|\blatest\b|\brecent\b|\bnew\b", lowered_query):
        required.append("missing_recency_evidence")
    if re.search(
        r"好评|高分|口碑|评分|评价|推荐|\breview|\brating|\bbest\b|well[- ]reviewed",
        lowered_query,
    ):
        required.append("missing_review_evidence")
    if re.search(r"图书|书籍|书单|书\b|\bbook", lowered_query):
        required.append("missing_book_evidence")
    if not required:
        return 0.0
    missing = set(
        _requirement_reasons(
            query=query,
            candidate_text=candidate_text,
            published_date=published_date,
        )
    )
    satisfied = sum(1 for reason in required if reason not in missing)
    return min(1.0, satisfied / len(required))


def _requirement_reasons(
    *,
    query: str,
    candidate_text: str,
    published_date: str,
) -> list[str]:
    lowered_query = query.lower()
    lowered_candidate = candidate_text.lower()
    reasons: list[str] = []
    if re.search(r"最新|近期|最近|新书|\blatest\b|\brecent\b|\bnew\b", lowered_query):
        years = [
            int(value)
            for value in re.findall(r"(20\d{2})", lowered_candidate)
        ]
        current_year = datetime.now().year
        recent_year = any(year >= current_year - 1 for year in years)
        explicit_recency = bool(
            re.search(
                r"最新|近期|最近|今年|新书|\blatest\b|\brecent\b|\bnew\b",
                lowered_candidate,
            )
        )
        dated_source = _published_year(published_date) >= current_year - 1
        if not recent_year and not (explicit_recency and dated_source):
            reasons.append("missing_recency_evidence")
    if re.search(
        r"好评|高分|口碑|评分|评价|推荐|\breview|\brating|\bbest\b|well[- ]reviewed",
        lowered_query,
    ):
        if not re.search(
            r"好评|高分|口碑|评分|评价|书评|推荐|榜单|星级|读者|评论|"
            r"\breview|\brating|\brated|\bbest\b|\brecommend",
            lowered_candidate,
        ):
            reasons.append("missing_review_evidence")
    if re.search(r"图书|书籍|书单|书\b|\bbook", lowered_query):
        if not re.search(
            r"图书|书籍|书单|著作|出版|作者|《|》|\bbook|\bauthor|\bpublisher",
            lowered_candidate,
        ):
            reasons.append("missing_book_evidence")
    return reasons


def _published_year(value: str) -> int:
    match = re.search(r"(20\d{2})", normalize_text(value))
    return int(match.group(1)) if match else 0


def _query_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = set(re.findall(r"[a-z0-9]{3,}", lowered))
    for segment in re.findall(r"[\u4e00-\u9fff]+", lowered):
        for stop in _QUERY_STOP_TERMS:
            segment = segment.replace(stop, " ")
        for part in segment.split():
            if len(part) <= 4:
                if len(part) >= 2:
                    terms.add(part)
                continue
            terms.update(
                part[index : index + 2]
                for index in range(len(part) - 1)
            )
    return terms


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
