from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.infra.database import dispose_database, init_database_connection
from app.services.agent_core.prompt_composer import CONTROLLER_PROMPT_VERSION
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawWindow,
    ShadowGateReadRequest,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_audit_request_id,
    shadow_observation_key_from_identity,
)
from app.services.agent_core.shadow_review_queue import (
    ShadowReviewQueueArtifact,
)
from scripts.developer_shadow_preview.contracts import (
    DeveloperShadowBusinessWrites,
    DeveloperShadowCleanup,
    DeveloperShadowCoverage,
    DeveloperShadowPreviewArtifact,
    DeveloperShadowPreviewCommand,
)
from scripts.developer_shadow_preview.admission import (
    DeveloperPreviewAdmissionPolicy,
)
from scripts.developer_shadow_preview.evaluation import (
    DeveloperShadowPreviewEvaluator,
)
from scripts.developer_shadow_preview.http_client import (
    DeveloperShadowHttpClient,
)
from scripts.developer_shadow_preview.repository import (
    DeveloperShadowPreviewRepository,
)
from scripts.developer_shadow_preview.source import (
    DeveloperShadowSourceVerifier,
)
from scripts.developer_shadow_preview.window import (
    DeveloperShadowWindowClock,
)


@dataclass(frozen=True)
class DeveloperShadowPreviewRunResult:
    preview: DeveloperShadowPreviewArtifact
    review_queue: ShadowReviewQueueArtifact


class DeveloperShadowServiceError(RuntimeError):
    """Raised when the orchestrated preview cannot form complete evidence."""


class DeveloperShadowPreviewService:
    """Orchestrate one preview while delegating every domain operation."""

    def __init__(
        self,
        *,
        source: DeveloperShadowSourceVerifier | None = None,
        http: DeveloperShadowHttpClient | None = None,
        repository: DeveloperShadowPreviewRepository | None = None,
        evaluator: DeveloperShadowPreviewEvaluator | None = None,
        admission_policy: DeveloperPreviewAdmissionPolicy | None = None,
        window_clock: DeveloperShadowWindowClock | None = None,
    ) -> None:
        self._source = source or DeveloperShadowSourceVerifier()
        self._http = http or DeveloperShadowHttpClient()
        self._repository = repository or DeveloperShadowPreviewRepository()
        self._evaluator = evaluator or DeveloperShadowPreviewEvaluator()
        self._admission_policy = (
            admission_policy or DeveloperPreviewAdmissionPolicy()
        )
        self._window_clock = window_clock or DeveloperShadowWindowClock()

    async def run(
        self,
        command: DeveloperShadowPreviewCommand,
        *,
        repository_root: Path,
    ) -> DeveloperShadowPreviewRunResult:
        proof = self._source.verify(
            command,
            repository_root=repository_root,
        )
        user_id = uuid.uuid4()
        thread_id = uuid.uuid4()
        request_ids = self._http.new_request_ids(command.turn_count)
        window_started_at = self._window_clock.open()
        seeded = False
        admission = None
        preview_admission = None
        raw: ShadowGateRawWindow | None = None
        review_queue: ShadowReviewQueueArtifact | None = None
        coverage: DeveloperShadowCoverage | None = None
        writes: DeveloperShadowBusinessWrites | None = None
        cleanup: DeveloperShadowCleanup | None = None
        response_modes: dict[str, int] = {}
        audit_ids: list[str] = []
        difference_count = 0
        window_ended_at: datetime | None = None

        await init_database_connection()
        try:
            admission_candidate = (
                await self._repository.read_admission_candidate(
                    model_id=command.model_id,
                    source_state=proof.source_state,
                )
            )
            preview_admission = self._admission_policy.require(
                admission_candidate,
                golden=proof.golden,
            )
            admission = preview_admission.admission
            audit_ids = [
                shadow_audit_request_id(
                    shadow_observation_key_from_identity(
                        thread_id=thread_id,
                        request_id=request_id,
                        controller_fingerprint=(
                            admission.controller_fingerprint
                        ),
                    )
                )
                for request_id in request_ids
            ]
            await self._repository.seed_mock_user(user_id)
            seeded = True
            modes = await self._http.send(
                base_url=proof.base_url,
                timeout_seconds=command.http_timeout_seconds,
                user_id=user_id,
                thread_id=thread_id,
                model_id=command.model_id,
                configured_thinking=(
                    preview_admission.configured_thinking
                ),
                request_ids=request_ids,
            )
            response_modes = dict(modes)
            await self._repository.poll_observations(
                user_id=user_id,
                request_ids=request_ids,
                timeout_seconds=command.observation_timeout_seconds,
            )
            closed_window = self._window_clock.close(
                started_at=window_started_at
            )
            window_ended_at = closed_window.ended_at
            raw = await self._repository.read_window(
                ShadowGateReadRequest(
                    commit_sha=proof.source_state.commit_sha,
                    controller_fingerprint=(
                        admission.controller_fingerprint
                    ),
                    configuration_fingerprint=(
                        admission.configuration_fingerprint
                    ),
                    prompt_version=CONTROLLER_PROMPT_VERSION,
                    window_started_at=window_started_at,
                    window_ended_at=window_ended_at,
                    collected_at=closed_window.collected_at,
                    timezone="Asia/Shanghai",
                    thread_id=thread_id,
                    request_ids=request_ids,
                )
            )
            raw = self._evaluator.select_request_scope(
                raw,
                request_ids=request_ids,
                thread_id=thread_id,
                controller_fingerprint=(
                    admission.controller_fingerprint
                ),
            )
            coverage = self._evaluator.validate_window(
                raw,
                request_ids=request_ids,
                thread_id=thread_id,
                model_id=command.model_id,
                admission=admission,
            )
            writes = await self._repository.read_business_writes(
                user_id=user_id,
                request_ids=request_ids,
                raw=raw,
            )
            review_queue, difference_count = (
                self._evaluator.build_review_queue(
                    raw,
                    source_state=proof.source_state,
                )
            )
            self._evaluator.assert_no_raw_input_leakage(
                prompts=self._http.prompts(command.turn_count),
                payloads=[review_queue],
            )
        finally:
            try:
                if seeded:
                    cleanup = await self._repository.cleanup_mock_scope(
                        user_id=user_id,
                        request_ids=request_ids,
                        audit_ids=audit_ids,
                    )
            finally:
                await dispose_database()

        if any(
            item is None
            for item in (
                admission,
                preview_admission,
                raw,
                review_queue,
                coverage,
                writes,
                cleanup,
                window_ended_at,
            )
        ):
            raise DeveloperShadowServiceError("preview_result_incomplete")
        assert admission is not None
        assert preview_admission is not None
        assert review_queue is not None
        assert coverage is not None
        assert writes is not None
        assert cleanup is not None
        assert window_ended_at is not None

        preview = DeveloperShadowPreviewArtifact(
            generated_at=datetime.now(timezone.utc),
            source_state=proof.source_state,
            source_commit_sha=proof.source_state.commit_sha,
            remote_ref=proof.remote_ref,
            remote_commit_sha=proof.remote_commit_sha,
            model_id=command.model_id,
            admission_profile=preview_admission.admission_profile,
            configured_thinking=(
                preview_admission.configured_thinking
            ),
            certification_id=uuid.UUID(admission.certification_id),
            configuration_fingerprint=(
                admission.configuration_fingerprint
            ),
            controller_fingerprint=admission.controller_fingerprint,
            prompt_version=CONTROLLER_PROMPT_VERSION,
            golden_artifact_sha256=proof.golden_sha256,
            review_queue_sha256=hashlib.sha256(
                render_artifact_bytes(review_queue)
            ).hexdigest(),
            base_url=proof.base_url,
            window_started_at=window_started_at,
            window_ended_at=window_ended_at,
            coverage=coverage,
            business_writes=writes,
            response_modes=response_modes,
            difference_count=difference_count,
            review_queue_candidate_count=len(review_queue.candidates),
            cleanup=cleanup,
        )
        self._evaluator.assert_no_raw_input_leakage(
            prompts=self._http.prompts(command.turn_count),
            payloads=[preview, review_queue],
        )
        return DeveloperShadowPreviewRunResult(
            preview=preview,
            review_queue=review_queue,
        )


def render_artifact_bytes(payload) -> bytes:
    return (
        json.dumps(
            payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )


__all__ = [
    "DeveloperShadowPreviewRunResult",
    "DeveloperShadowPreviewService",
    "DeveloperShadowServiceError",
    "render_artifact_bytes",
]
