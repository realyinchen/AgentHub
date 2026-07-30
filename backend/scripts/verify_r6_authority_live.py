"""Run a clean-source LongCat R6 Controller dry canary."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.contracts import ControllerOutput
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.evidence_artifact import EvidenceArtifactWriter
from app.services.agent_core.evidence_source import GitSourceStateReader
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ControllerModelRequest,
    ConversationContextTurn,
)
from app.services.agent_core.shadow import ShadowValidator
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.canary import _failure_code
from app.services.model_probe.configuration import resolve_probe_target
from app.services.tasks.draft_validator import TaskPlanDraftValidator
from app.services.agent_core.proposal_validator import ProposalValidator


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    return parser.parse_args()


def _registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        availability=ExternalCapabilityAvailability(),
        core_availability=CoreCapabilityAvailability(
            conversation_read=True,
            memory_read=True,
            memory_write=True,
            task_control=False,
        ),
    )


def _cases() -> tuple[dict, ...]:
    return (
        {
            "case_id": "whole_conversation_exact_recall",
            "current_user_message": (
                "What did I just say, and how did you reply?"
            ),
            "context": ControllerContextSnapshot(
                conversation=[
                    ConversationContextTurn(
                        role="user",
                        content="Hello, I am Binglu.",
                    ),
                    ConversationContextTurn(
                        role="assistant",
                        content="Hello, Binglu.",
                    ),
                ]
            ),
            "required_capability": "conversation_read",
        },
        {
            "case_id": "complete_durable_memory",
            "current_user_message": (
                "Please remember this durable fact: my name is Binglu."
            ),
            "context": ControllerContextSnapshot(),
            "required_capability": "remember_memory",
        },
    )


def _capabilities(output: ControllerOutput) -> list[str]:
    if output.mode == "task_plan_proposal":
        draft = output.task_plan_proposal
        return [
            step.capability
            for step in (draft.steps if draft is not None else [])
        ]
    return [call.name for call in output.tool_calls]


async def _main(arguments: argparse.Namespace) -> int:
    writer = EvidenceArtifactWriter()
    writer.require_available(arguments.output)
    source = GitSourceStateReader().require_release_state(
        REPOSITORY_ROOT,
        expected_commit_sha=arguments.commit_sha,
    )
    registry = _registry()
    validator = ShadowValidator(
        validator=ProposalValidator(registry),
        task_plan_validator=TaskPlanDraftValidator(registry),
    )
    model_uuid = uuid.UUID(arguments.model_id)
    provider_model_id = ""
    configuration_fingerprint = ""
    results: list[dict] = []

    from app.infra.database import (
        dispose_database,
        get_database,
        init_database_connection,
    )
    from app.infra.llm.manager import get_model_manager
    from app.models.model import Model
    from scripts.init_database import _init_postgres

    _init_postgres()
    await init_database_connection()
    database = get_database()
    try:
        async with database.session() as session:
            model = (
                await session.execute(
                    select(Model).where(
                        Model.id == model_uuid,
                        Model.model_type.in_(("llm", "vlm")),
                        Model.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if model is None:
                raise AssertionError("explicit active chat model was not found")
            provider_model_id = str(model.model_id)
            target = await resolve_probe_target(
                session,
                model_uuid,
                timeout_seconds=arguments.timeout_seconds,
                check_thinking=False,
            )
            configuration_fingerprint = target.configuration_fingerprint
        await get_model_manager().refresh()
        client = ControllerClient(registry=registry)
        for case in _cases():
            status = "failed"
            failure_code = ""
            observed_mode = ""
            observed_capabilities: list[str] = []
            shadow_valid = False
            try:
                output = await client.decide(
                    ControllerModelRequest(
                        model_name=str(model_uuid),
                        current_user_message=case[
                            "current_user_message"
                        ],
                        context=case["context"],
                        admission=AgentModeAdmission(
                            admitted=True,
                            certification_id=(
                                "candidate-canary-no-release-credit"
                            ),
                            configuration_fingerprint=(
                                configuration_fingerprint
                            ),
                            controller_fingerprint=(
                                current_controller_fingerprint(registry)
                            ),
                            source_commit_sha=source.commit_sha,
                        ),
                        timeout_seconds=arguments.timeout_seconds,
                    )
                )
                observed_mode = output.mode
                observed_capabilities = _capabilities(output)
                shadow = validator.evaluate(
                    output,
                    goal=case["current_user_message"],
                )
                shadow_valid = shadow.valid
                if (
                    case["required_capability"]
                    in observed_capabilities
                    and shadow_valid
                ):
                    status = "passed"
                else:
                    failure_code = "controller_decision_mismatch"
            except Exception as exc:
                failure_code = _failure_code(exc)
            results.append(
                {
                    "case_id": case["case_id"],
                    "status": status,
                    "failure_code": failure_code,
                    "observed_mode": observed_mode,
                    "observed_capabilities": observed_capabilities,
                    "shadow_valid": shadow_valid,
                    "runtime_calls": 0,
                    "memory_writes": 0,
                }
            )
            if failure_code == "model_provider_capacity":
                break
    except Exception as exc:
        results.append(
            {
                "case_id": "model_setup",
                "status": "failed",
                "failure_code": _failure_code(exc),
                "observed_mode": "",
                "observed_capabilities": [],
                "shadow_valid": False,
                "runtime_calls": 0,
                "memory_writes": 0,
            }
        )
    finally:
        await dispose_database()

    passed = len(results) == len(_cases()) and all(
        item["status"] == "passed" for item in results
    )
    evidence = {
        "evidence_version": "r6-authority-canary-v1",
        "source_commit_sha": source.commit_sha,
        "model_id": str(model_uuid),
        "provider_model_id": provider_model_id,
        "configuration_fingerprint": configuration_fingerprint,
        "controller_fingerprint": current_controller_fingerprint(registry),
        "cases": results,
        "dry_run": True,
        "runtime_calls": 0,
        "memory_writes": 0,
        "raw_provider_error_exposed": False,
        "release_gate_credit": passed,
        "status": "passed" if passed else "failed",
    }
    writer.write_json_new(arguments.output, evidence)
    print(
        json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_arguments())))
