"""Finite cosine similarity for embedding calibration and recall."""

from __future__ import annotations

import math
from collections.abc import Sequence


def cosine_similarity(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    if not left or len(left) != len(right):
        return 0.0
    if not all(math.isfinite(value) for value in (*left, *right)):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


__all__ = ["cosine_similarity"]
