from __future__ import annotations

from typing import Any


def evidence_was_admitted(result: Any) -> bool:
    """Project an add-evidence state receipt into one explicit admission fact."""

    if not isinstance(result, dict):
        return False
    steps = result.get("steps")
    if not isinstance(steps, list):
        return False
    for step in reversed(steps):
        if not isinstance(step, dict) or step.get("step_type") != "add_evidence":
            continue
        output = step.get("output")
        admission = (
            output.get("evidence_admission")
            if isinstance(output, dict)
            else None
        )
        return bool(
            step.get("status") == "completed"
            and isinstance(admission, dict)
            and admission.get("allowed") is True
        )
    return False
