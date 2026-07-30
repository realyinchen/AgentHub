from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.agent_core.contracts import (
    ControllerOutput,
    ShadowRunEvidence,
)
from app.services.agent_core.prompt_contracts import ControllerModelRequest


def build_shadow_run_evidence(
    request: ControllerModelRequest,
    output: ControllerOutput,
) -> ShadowRunEvidence:
    return ShadowRunEvidence(
        context_snapshot_hash=_hash_json(
            request.context.model_dump(mode="json")
        ),
        input_evidence_hash=_hash_text(
            request.current_user_message
        ),
        output_mode=output.mode,
        proposal_summary=_proposal_summary(output),
    )


def _proposal_summary(output: ControllerOutput) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mode": output.mode,
        "progress_text_hash": (
            _hash_text(output.progress_text)
            if output.progress_text
            else None
        ),
    }
    if output.mode in {"direct_answer", "request_clarification"}:
        summary["text_hash"] = _hash_text(output.text)
    elif output.mode == "task_plan_proposal":
        draft = output.task_plan_proposal
        if draft is not None:
            summary["task"] = {
                "goal_hash": _hash_text(draft.goal),
                "success_criteria_count": len(
                    draft.success_criteria
                ),
                "steps": [
                    {
                        "capability": step.capability,
                        "argument_hash": _hash_json(
                            step.arguments
                        ),
                        "dependency_count": len(
                            step.depends_on
                        ),
                    }
                    for step in draft.steps
                ],
            }
    else:
        summary["capabilities"] = [
            {
                "name": call.name,
                "argument_hash": _hash_json(call.arguments),
                "dependency_count": len(call.depends_on),
            }
            for call in output.tool_calls
        ]
    return summary


def hash_shadow_text(value: str) -> str:
    return _hash_text(value)


def hash_shadow_json(value: Any) -> str:
    return _hash_json(value)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "build_shadow_run_evidence",
    "hash_shadow_json",
    "hash_shadow_text",
]
