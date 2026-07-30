from __future__ import annotations

from time import perf_counter

from app.infra.database import get_database
from app.services.agent_core.gateway import AgentControllerGateway
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.release_identity import (
    require_release_commit_sha,
)
from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
)
from app.services.agent_core.shadow_observation_projector import (
    ShadowObservationProjector,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_audit_request_id,
    shadow_observation_key,
)
from app.services.agent_core.shadow_observation_repository import (
    ShadowObservationRepository,
)


class ShadowObservationWorker:
    """Execute one dry Controller decision and append its telemetry."""

    def __init__(
        self,
        *,
        expected_source_commit_sha: str,
        gateway: AgentControllerGateway | None = None,
        projector: ShadowObservationProjector | None = None,
        repository: ShadowObservationRepository | None = None,
        database_provider=None,
    ) -> None:
        self._expected_source_commit_sha = require_release_commit_sha(
            expected_source_commit_sha
        )
        self._gateway = gateway or AgentControllerGateway()
        self._projector = (
            projector or ShadowObservationProjector()
        )
        self._repository = (
            repository or ShadowObservationRepository()
        )
        self._database_provider = database_provider or get_database

    async def handle(
        self,
        command: ShadowControllerCommand,
    ) -> None:
        started = perf_counter()
        if (
            command.controller_fingerprint
            != current_controller_fingerprint()
        ):
            raise RuntimeError(
                "Shadow command belongs to a different Controller build"
            )
        if (
            command.source_commit_sha
            != self._expected_source_commit_sha
        ):
            raise RuntimeError(
                "Shadow command belongs to a different source release"
            )
        observation_key = shadow_observation_key(
            command,
            command.controller_fingerprint,
        )
        database = self._database_provider()
        async with database.session() as db:
            attempt = await self._gateway.evaluate(
                db,
                user_input=command.user_input,
                model_name=command.model_name,
                mode="shadow",
                journal_sequence_watermark=(
                    command.journal_sequence_watermark
                ),
                execution_request_id=shadow_audit_request_id(
                    observation_key
                ),
            )
            elapsed_ms = max(
                0,
                int((perf_counter() - started) * 1_000),
            )
            candidate = self._projector.project(
                command,
                attempt,
                latency_ms=elapsed_ms,
            )
            await self._repository.append(db, candidate)


__all__ = ["ShadowObservationWorker"]
