from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.agent_core.publication.contracts import (
    ReceiptEvidenceBundle,
)


_SIDE_EFFECT_SUCCESS_RE = re.compile(
    r"(?:已|已经|成功)(?:记录|保存|更新|修改|删除|忘记|创建|取消)"
    r"|(?:saved|updated|deleted|created|cancelled|canceled)\s+"
    r"(?:your|the|this)",
    re.IGNORECASE,
)
_TECHNICAL_LEAK_RE = re.compile(
    r"dependency did not complete"
    r"|controller-action-"
    r"|(?:^|\W)action-[0-9a-f-]{8,}"
    r"|<\s*tool_call\b"
    r"|<\s*function="
    r"|(?:^|\n)\s*Traceback \(most recent call last\)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
_MARKDOWN_STRUCTURE_RE = re.compile(
    r"(?m)^\s*(?:#{1,4}\s+|[-*]\s+|\d+[.)]\s+)"
)


def validate_direct_text(text: str) -> str:
    cleaned = _clean(text)
    _reject_technical_text(cleaned)
    if _SIDE_EFFECT_SUCCESS_RE.search(cleaned):
        raise ValueError(
            "side-effect success claims require a deterministic receipt"
        )
    return cleaned


def validate_synthesis(
    text: str,
    *,
    evidence: Sequence[ReceiptEvidenceBundle],
) -> str:
    cleaned = validate_direct_text(text)
    if not evidence:
        raise ValueError("model synthesis requires receipt evidence")
    for bundle in evidence:
        if bundle.plan.response_mode != "model":
            raise ValueError(
                "model synthesis requires model response-mode evidence"
            )
        if any(
            bool(action.metadata.get("side_effect"))
            for action in bundle.plan.actions
        ):
            raise ValueError(
                "model synthesis is restricted to read-only receipts"
            )

    allowed_urls = _evidence_urls(evidence)
    emitted_urls = set(_URL_RE.findall(cleaned))
    unknown_urls = emitted_urls - allowed_urls
    if unknown_urls:
        raise ValueError("model synthesis contains an unadmitted source URL")
    if allowed_urls and not emitted_urls:
        raise ValueError(
            "model synthesis must cite at least one admitted source URL"
        )
    if (
        len(cleaned) > 800
        and len(allowed_urls) >= 3
        and (
            cleaned.count("\n") < 2
            or _MARKDOWN_STRUCTURE_RE.search(cleaned) is None
        )
    ):
        raise ValueError(
            "long external synthesis must use structured readable Markdown"
        )
    return cleaned


def _evidence_urls(
    evidence: Sequence[ReceiptEvidenceBundle],
) -> set[str]:
    urls: set[str] = set()
    for bundle in evidence:
        for action in bundle.receipt.actions:
            output = action.output if isinstance(action.output, dict) else {}
            sources = output.get("sources")
            if not isinstance(sources, list):
                continue
            for source in sources:
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url") or "").strip()
                if url.lower().startswith(("https://", "http://")):
                    urls.add(url)
    return urls


def _reject_technical_text(text: str) -> None:
    if _TECHNICAL_LEAK_RE.search(text):
        raise ValueError(
            "technical runtime details cannot enter a published answer"
        )


def _clean(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("published answer cannot be empty")
    if len(cleaned) > 32_000:
        raise ValueError("published answer exceeds its contract")
    return cleaned


__all__ = [
    "validate_direct_text",
    "validate_synthesis",
]
