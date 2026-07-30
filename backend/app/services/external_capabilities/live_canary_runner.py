from __future__ import annotations

import uuid

from sqlalchemy import select

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.prompt_contracts import ControllerModelRequest
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.canary import (
    CapabilityCanarySpec,
    _failure_code,
    contains_forbidden_keys,
    run_capability_canary,
)
from app.services.external_capabilities.canary_contracts import (
    R4CapabilityCanaryEvidence,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.model_probe.configuration import resolve_probe_target


async def run_configured_capability_canary(
    *,
    source: GitSourceState,
    model_id: str,
    timeout_seconds: float,
    spec: CapabilityCanarySpec,
    availability: ExternalCapabilityAvailability,
    external_runtime: ExternalCapabilityRuntime,
) -> R4CapabilityCanaryEvidence:
    """Bind one two-phase canary to an exact configured model and source."""

    from app.infra.database import (
        dispose_database,
        get_database,
        init_database_connection,
    )
    from app.infra.llm.manager import get_model_manager
    from app.models.model import Model
    from scripts.init_database import _init_postgres

    model_uuid = uuid.UUID(model_id)
    registry = CapabilityRegistry(availability=availability)
    provider_model_id = ""

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
                timeout_seconds=timeout_seconds,
                check_thinking=False,
            )

        await get_model_manager().refresh()
        request = ControllerModelRequest(
            model_name=str(model_uuid),
            current_user_message=spec.user_message,
            admission=AgentModeAdmission(
                admitted=True,
                certification_id="candidate-canary-no-release-credit",
                configuration_fingerprint=target.configuration_fingerprint,
                controller_fingerprint=current_controller_fingerprint(
                    registry
                ),
                source_commit_sha=source.commit_sha,
            ),
            timeout_seconds=timeout_seconds,
        )
        run = await run_capability_canary(
            spec=spec,
            controller=ControllerClient(registry=registry),
            registry=registry,
            request=request,
            runtime=SystemRuntime(external_runtime=external_runtime),
            context=ExecutionContext(
                user_id="00000000-0000-0000-0000-000000000001",
                thread_id="00000000-0000-0000-0000-000000000002",
                request_id=f"r4-{spec.capability}-live-canary",
                model_name=str(model_uuid),
                timezone="Asia/Shanghai",
            ),
        )
        provider_exposed = contains_forbidden_keys(
            run.runtime_output,
            {"provider", "provider_name", "upstream_provider"},
        )
        raw_exposed = contains_forbidden_keys(
            run.runtime_output,
            {
                "attempts",
                "content",
                "metadata",
                "raw",
                "raw_response",
                "upstream_request_id",
            },
        )
        system_fields_exposed = contains_forbidden_keys(
            run.runtime_output,
            {"user_id", "thread_id", "request_id"},
        )
        passed = (
            run.model_phase_status == "passed"
            and run.runtime_phase_status == "passed"
            and not provider_exposed
            and not raw_exposed
            and not system_fields_exposed
        )
        return R4CapabilityCanaryEvidence(
            capability=spec.capability,
            status="passed" if passed else "failed",
            source_commit_sha=source.commit_sha,
            model_id=str(model_uuid),
            provider_model_id=provider_model_id,
            controller_mode=run.controller_mode,
            proposed_capabilities=run.proposed_capabilities,
            compiled_operations=run.compiled_operations,
            plan_status=run.plan_status,
            source_count=run.source_count,
            model_phase_status=run.model_phase_status,
            runtime_phase_status=run.runtime_phase_status,
            runtime_input_source=run.runtime_input_source,
            model_failure_code=run.model_failure_code,
            runtime_failure_code=run.runtime_failure_code,
            provider_identity_exposed=provider_exposed,
            raw_provider_dump_exposed=raw_exposed,
            system_owned_fields_exposed=system_fields_exposed,
            failure_code=(
                ""
                if passed
                else run.model_failure_code
                or run.runtime_failure_code
                or "capability_canary_incomplete"
            ),
        )
    except Exception as exc:
        failure_code = _failure_code(exc)
        return R4CapabilityCanaryEvidence(
            capability=spec.capability,
            status="failed",
            source_commit_sha=source.commit_sha,
            model_id=str(model_uuid),
            provider_model_id=provider_model_id,
            controller_mode="error",
            model_phase_status="failed",
            runtime_phase_status="not_run",
            runtime_input_source="not_run",
            model_failure_code=failure_code,
            failure_code=failure_code,
        )
    finally:
        await dispose_database()


__all__ = ["run_configured_capability_canary"]
