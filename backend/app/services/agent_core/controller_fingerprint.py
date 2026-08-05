from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
)
from app.services.agent_core.contracts import (
    AGENT_CORE_CONTRACT_VERSION,
    ControllerOutput,
)
from app.services.agent_core.controller_client import (
    controller_tool_schemas,
)
from app.services.agent_core.prompt_composer import PromptComposer
from app.services.agent_core.task_plan_proposal import (
    CONTROLLER_TASK_PLAN_PROPOSAL_VERSION,
    ControllerTaskPlanProposal,
)
from app.services.tasks.contracts import TASK_PLAN_CONTRACT_VERSION


def build_controller_fingerprint(
    *,
    core_prompt: str,
    controller_schema: Mapping[str, Any],
    task_schema: Mapping[str, Any],
    tool_schemas: Sequence[Mapping[str, Any]],
    contract_versions: Mapping[str, str],
) -> str:
    """Hash every model-visible Controller contract component."""

    canonical_tools = sorted(
        (
            json.dumps(
                schema,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            for schema in tool_schemas
        )
    )
    material = {
        "core_prompt": core_prompt,
        "controller_schema": controller_schema,
        "task_schema": task_schema,
        "tool_schemas": canonical_tools,
        "contract_versions": dict(contract_versions),
    }
    encoded = json.dumps(
        material,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def current_controller_fingerprint(
    registry: CapabilityRegistry | None = None,
) -> str:
    """Return the fingerprint required by certification and admission."""

    capability_registry = registry or CapabilityRegistry()
    return build_controller_fingerprint(
        core_prompt=PromptComposer(
            capability_registry
        ).core_prompt(),
        controller_schema=ControllerOutput.model_json_schema(),
        task_schema=ControllerTaskPlanProposal.model_json_schema(),
        tool_schemas=controller_tool_schemas(capability_registry),
        contract_versions={
            "agent_core": AGENT_CORE_CONTRACT_VERSION,
            "agent_certification": AGENT_CERTIFICATION_CONTRACT_VERSION,
            "task_plan": TASK_PLAN_CONTRACT_VERSION,
            "controller_task_plan_proposal": (
                CONTROLLER_TASK_PLAN_PROPOSAL_VERSION
            ),
        },
    )


__all__ = [
    "build_controller_fingerprint",
    "current_controller_fingerprint",
]
