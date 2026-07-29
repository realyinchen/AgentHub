"""Deterministic lexical recall over the immutable prototype catalog."""

from __future__ import annotations

import re

from app.services.routing.config import KEYWORD_CANDIDATE_THRESHOLD
from app.services.routing.contracts import IntentCandidate
from app.services.routing.semantic_prototypes import PROTOTYPES


def recall_keywords(text: str) -> list[IntentCandidate]:
    candidates: list[IntentCandidate] = []
    for prototype in PROTOTYPES:
        score, phrase = max(
            (
                (lexical_similarity(text, item), item)
                for item in prototype.phrases
            ),
            default=(0.0, ""),
        )
        if score < KEYWORD_CANDIDATE_THRESHOLD:
            continue
        candidates.append(
            IntentCandidate(
                intent=prototype.intent,
                confidence=min(0.88, 0.58 + score * 0.34),
                source="keyword",
                evidence=[f"prototype:{phrase}", f"lexical_score:{score:.3f}"],
                domain=prototype.domain,
            )
        )
    return candidates


def lexical_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens.intersection(right_tokens))
    union = len(left_tokens.union(right_tokens))
    jaccard = intersection / union if union else 0.0
    containment = intersection / min(len(left_tokens), len(right_tokens))
    normalized_left = "".join(str(left).lower().split())
    normalized_right = "".join(str(right).lower().split())
    phrase_match = 1.0 if (
        normalized_left in normalized_right or normalized_right in normalized_left
    ) else 0.0
    return max(jaccard, containment * 0.78, phrase_match)


def _tokens(text: str) -> set[str]:
    normalized = str(text or "").lower()
    ascii_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", normalized))
    cjk_bigrams = {
        cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))
    }
    if len(cjk) == 1:
        cjk_bigrams.add(cjk)
    return ascii_tokens.union(cjk_bigrams)
