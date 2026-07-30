from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import agent_capability_certification as certification_crud
from app.models.agent_capability_certification import (
    AgentCapabilityCertification,
)
from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
    AgentModeAdmission,
)
from app.services.agent_core.certification_probe import AgentCapabilityProbe
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.release_identity import (
    AgentReleaseIdentityError,
    require_release_commit_sha,
)
from app.services.agent_core.evidence_source import GitSourceState
from app.services.model_probe.configuration import (
    ProbeTargetResolutionError,
    resolve_probe_target,
)


class AgentCertificationError(ValueError):
    """Raised when Agent certification cannot be started."""


async def validate_agent_capability(
    db: AsyncSession,
    model_id: uuid.UUID,
    *,
    source_state: GitSourceState,
    timeout_seconds: float = 45,
    probe: AgentCapabilityProbe | None = None,
) -> AgentCapabilityCertification:
    release_commit = _certification_source(source_state)
    target = await _resolve_agent_target(
        db,
        model_id,
        timeout_seconds=timeout_seconds,
    )
    outcome = await (probe or AgentCapabilityProbe()).run(target.config)
    controller_fingerprint = current_controller_fingerprint()
    return await certification_crud.create_certification(
        db,
        {
            "model_id": target.model_db_id,
            "provider": target.provider,
            "provider_model_id": target.provider_model_id,
            "configuration_fingerprint": target.configuration_fingerprint,
            "contract_version": outcome.contract_version,
            "controller_fingerprint": controller_fingerprint,
            "source_commit_sha": release_commit,
            "certified": outcome.certified,
            "latency_ms": outcome.latency_ms,
            "cases": [
                case.model_dump(mode="json")
                for case in outcome.cases
            ],
            "failure_cases": list(outcome.failure_cases),
            "error_type": (
                None if outcome.certified else "required_probe_failed"
            ),
            "last_error": (
                None
                if outcome.certified
                else "Failed required cases: "
                + ", ".join(outcome.failure_cases)
            ),
        },
    )


async def get_agent_mode_admission(
    db: AsyncSession,
    model_id: uuid.UUID,
    *,
    source_commit_sha: str,
) -> AgentModeAdmission:
    release_commit = _release_commit(source_commit_sha)
    target = await _resolve_agent_target(db, model_id, timeout_seconds=45)
    controller_fingerprint = current_controller_fingerprint()
    current = await certification_crud.get_latest_certification(
        db,
        model_id,
        configuration_fingerprint=target.configuration_fingerprint,
        contract_version=AGENT_CERTIFICATION_CONTRACT_VERSION,
        controller_fingerprint=controller_fingerprint,
        source_commit_sha=release_commit,
    )
    if current is not None:
        return AgentModeAdmission(
            admitted=bool(current.certified),
            certification_id=str(current.id),
            reason=None if current.certified else "certification_failed",
            configuration_fingerprint=target.configuration_fingerprint,
            controller_fingerprint=controller_fingerprint,
            source_commit_sha=release_commit,
        )

    latest = await certification_crud.get_latest_certification(db, model_id)
    if latest is None:
        reason = "certification_missing"
    elif latest.configuration_fingerprint != target.configuration_fingerprint:
        reason = "configuration_changed"
    elif latest.contract_version != AGENT_CERTIFICATION_CONTRACT_VERSION:
        reason = "contract_changed"
    elif latest.controller_fingerprint != controller_fingerprint:
        reason = "controller_changed"
    elif latest.source_commit_sha != release_commit:
        reason = "release_changed"
    else:
        reason = "certification_missing"
    return AgentModeAdmission(
        admitted=False,
        reason=reason,
        configuration_fingerprint=target.configuration_fingerprint,
        controller_fingerprint=controller_fingerprint,
        source_commit_sha=release_commit,
    )


def _release_commit(value: object) -> str:
    try:
        return require_release_commit_sha(value)
    except AgentReleaseIdentityError as exc:
        raise AgentCertificationError(str(exc)) from exc


def _certification_source(value: object) -> str:
    if not isinstance(value, GitSourceState):
        raise AgentCertificationError(
            "agent_certification_source_proof_required"
        )
    if value.dirty_worktree:
        raise AgentCertificationError(
            "agent_certification_source_dirty"
        )
    return value.commit_sha


async def _resolve_agent_target(
    db: AsyncSession,
    model_id: uuid.UUID,
    *,
    timeout_seconds: float,
):
    try:
        target = await resolve_probe_target(
            db,
            model_id,
            timeout_seconds=timeout_seconds,
            check_thinking=False,
        )
    except ProbeTargetResolutionError as exc:
        raise AgentCertificationError(str(exc)) from exc
    if target.model_type not in {"llm", "vlm"}:
        raise AgentCertificationError("agent_mode_requires_chat_model")
    return target


__all__ = [
    "AgentCertificationError",
    "get_agent_mode_admission",
    "validate_agent_capability",
]
