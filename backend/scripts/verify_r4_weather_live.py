"""Run one clean-source LongCat weather proposal and live provider canary."""

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
from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.evidence_artifact import EvidenceArtifactWriter
from app.services.agent_core.evidence_source import GitSourceStateReader
from app.services.agent_core.prompt_contracts import ControllerModelRequest
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.canary_contracts import (
    R4CapabilityCanaryEvidence,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.external_capabilities.weather import WeatherRuntimeAdapter
from app.services.model_probe.configuration import resolve_probe_target


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--location", default="杭州")
    parser.add_argument("--date", default="tomorrow")
    parser.add_argument("--timeout-seconds", type=float, default=60)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> R4CapabilityCanaryEvidence:
    from app.infra.database import (
        dispose_database,
        get_database,
        init_database_connection,
    )
    from app.infra.llm.manager import get_model_manager
    from app.models.model import Model
    from scripts.init_database import _init_postgres

    source = GitSourceStateReader().require_release_state(
        REPOSITORY_ROOT,
        expected_commit_sha=arguments.commit_sha,
    )
    model_uuid = uuid.UUID(arguments.model_id)
    enabled = ExternalCapabilityAvailability(weather_get=True)
    registry = CapabilityRegistry(availability=enabled)
    writer = EvidenceArtifactWriter()
    writer.require_available(arguments.output)

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
            target = await resolve_probe_target(
                session,
                model_uuid,
                timeout_seconds=arguments.timeout_seconds,
                check_thinking=False,
            )

        await get_model_manager().refresh()
        controller_fingerprint = current_controller_fingerprint(registry)
        request = ControllerModelRequest(
            model_name=str(model_uuid),
            current_user_message=(
                f"{arguments.location}{arguments.date}天气怎么样？"
            ),
            admission=AgentModeAdmission(
                admitted=True,
                certification_id="candidate-canary-no-release-credit",
                configuration_fingerprint=target.configuration_fingerprint,
                controller_fingerprint=controller_fingerprint,
                source_commit_sha=source.commit_sha,
            ),
            timeout_seconds=arguments.timeout_seconds,
        )
        output = await ControllerClient(registry=registry).decide(request)
        batch = ProposalValidator(registry).validate(output)
        plan = WorkflowCompiler().compile(
            batch,
            goal=request.current_user_message,
        )
        runtime = ExternalCapabilityRuntime(
            availability=enabled,
            adapters=[WeatherRuntimeAdapter()],
        )
        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id="00000000-0000-0000-0000-000000000001",
                thread_id="00000000-0000-0000-0000-000000000002",
                request_id="r4-weather-live-canary",
                model_name=str(model_uuid),
                timezone="Asia/Shanghai",
            ),
        )
        proposed = [item.capability for item in batch.proposals]
        operations = [item.operation for item in plan.actions]
        weather_outputs = [
            item.output
            for item in receipt.actions
            if item.operation == "weather_get_v1"
            and isinstance(item.output, dict)
        ]
        source_count = sum(
            len(item.get("sources", [])) for item in weather_outputs
        )
        serialized = json.dumps(weather_outputs, ensure_ascii=False)
        passed = (
            output.mode == "capability_proposals"
            and proposed == ["weather_get"]
            and operations == ["weather_get_v1"]
            and receipt.status == "completed"
            and source_count > 0
            and "provider" not in serialized.casefold()
        )
        evidence = R4CapabilityCanaryEvidence(
            capability="weather_get",
            status="passed" if passed else "failed",
            source_commit_sha=source.commit_sha,
            model_id=str(model_uuid),
            provider_model_id=str(model.model_id),
            controller_mode=output.mode,
            proposed_capabilities=proposed,
            compiled_operations=operations,
            plan_status=receipt.status,
            source_count=source_count,
            provider_identity_exposed="provider" in serialized.casefold(),
            raw_provider_dump_exposed=any(
                token in serialized
                for token in ("attempts", "content", "metadata")
            ),
            system_owned_fields_exposed=any(
                token in json.dumps(
                    [item.arguments for item in plan.actions],
                    ensure_ascii=False,
                )
                for token in ("user_id", "thread_id", "request_id")
            ),
            failure_code="" if passed else "weather_canary_incomplete",
        )
        writer.write_json_new(arguments.output, evidence)
        return evidence
    finally:
        await dispose_database()


async def _main(arguments: argparse.Namespace) -> int:
    evidence = await _run(arguments)
    print(
        json.dumps(
            evidence.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
    )
    return 0 if evidence.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_arguments())))
