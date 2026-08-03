from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
    AGENT_PROBE_CASE_NAMES,
    AgentModeAdmission,
    AgentModeDenialReason,
    AgentProbeCaseName,
    AgentProbeCaseResult,
)
from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.evidence_source import GitSourceState
from app.services.model_probe.contracts import ProbeErrorCategory


AGENT_CERTIFICATION_EVIDENCE_VERSION = (
    "agent-certification-evidence-v1"
)


class AgentCertificationCaseEvidence(AgentCoreModel):
    name: AgentProbeCaseName
    required: bool
    passed: bool
    latency_ms: int = Field(ge=0)
    executed: bool = True
    error_category: ProbeErrorCategory | None = None
    short_circuited_by: AgentProbeCaseName | None = None

    @model_validator(mode="after")
    def validate_execution_state(
        self,
    ) -> "AgentCertificationCaseEvidence":
        if self.passed and not self.executed:
            raise ValueError("an unexecuted certification case cannot pass")
        if not self.executed and (
            self.error_category is None
            or self.short_circuited_by is None
        ):
            raise ValueError(
                "short-circuited certification evidence is incomplete"
            )
        if self.executed and self.short_circuited_by is not None:
            raise ValueError(
                "an executed certification case cannot be short-circuited"
            )
        return self


class AgentCertificationEvidenceArtifact(AgentCoreModel):
    """Immutable, redacted evidence for one real certification run."""

    evidence_version: Literal[
        "agent-certification-evidence-v1"
    ] = AGENT_CERTIFICATION_EVIDENCE_VERSION
    generated_at: datetime
    source_state: GitSourceState
    certification_id: UUID
    model_id: UUID
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    configuration_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    certification_contract_version: Literal[
        "agent-capability-v4"
    ] = AGENT_CERTIFICATION_CONTRACT_VERSION
    status: Literal["passed", "failed"]
    certified: bool
    admission_admitted: bool
    admission_reason: AgentModeDenialReason | None = None
    cases: list[AgentCertificationCaseEvidence] = Field(
        min_length=len(AGENT_PROBE_CASE_NAMES),
        max_length=len(AGENT_PROBE_CASE_NAMES),
    )
    failure_cases: list[AgentProbeCaseName] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_evidence(
        self,
    ) -> "AgentCertificationEvidenceArtifact":
        if self.generated_at.tzinfo is None:
            raise ValueError(
                "certification evidence time must be timezone-aware"
            )
        if self.source_state.dirty_worktree:
            raise ValueError(
                "certification evidence requires clean source"
            )
        if self.source_state.commit_sha != self.source_commit_sha:
            raise ValueError(
                "certification evidence source commit mismatch"
            )
        names = [case.name for case in self.cases]
        if (
            len(set(names)) != len(names)
            or set(names) != set(AGENT_PROBE_CASE_NAMES)
        ):
            raise ValueError(
                "certification evidence must contain every probe case once"
            )
        failed_required = sorted(
            case.name
            for case in self.cases
            if case.required and not case.passed
        )
        if sorted(self.failure_cases) != failed_required:
            raise ValueError(
                "certification evidence failure cases are inconsistent"
            )
        passed = not failed_required
        if self.certified != passed:
            raise ValueError(
                "certification evidence certified flag is inconsistent"
            )
        if self.admission_admitted != passed:
            raise ValueError(
                "certification evidence admission is inconsistent"
            )
        if self.status != ("passed" if passed else "failed"):
            raise ValueError(
                "certification evidence status is inconsistent"
            )
        if passed and self.admission_reason is not None:
            raise ValueError(
                "passed certification cannot have an admission reason"
            )
        if not passed and self.admission_reason is None:
            raise ValueError(
                "failed certification requires an admission reason"
            )
        return self

    @classmethod
    def build(
        cls,
        *,
        source_state: GitSourceState,
        certification,
        admission: AgentModeAdmission,
        generated_at: datetime,
    ) -> "AgentCertificationEvidenceArtifact":
        source_commit_sha = str(
            certification.source_commit_sha or ""
        )
        if admission.certification_id != str(certification.id):
            raise ValueError(
                "certification evidence admission id differs"
            )
        if admission.source_commit_sha != source_commit_sha:
            raise ValueError(
                "certification and admission source commits differ"
            )
        if (
            admission.configuration_fingerprint
            != certification.configuration_fingerprint
        ):
            raise ValueError(
                "certification and admission configurations differ"
            )
        if (
            admission.controller_fingerprint
            != certification.controller_fingerprint
        ):
            raise ValueError(
                "certification and admission Controllers differ"
            )
        if (
            certification.contract_version
            != AGENT_CERTIFICATION_CONTRACT_VERSION
        ):
            raise ValueError(
                "certification evidence contract is not current"
            )
        cases = [
            AgentProbeCaseResult.model_validate(item)
            for item in list(certification.cases or [])
        ]
        return cls(
            generated_at=generated_at,
            source_state=source_state,
            certification_id=certification.id,
            model_id=certification.model_id,
            source_commit_sha=source_commit_sha,
            configuration_fingerprint=(
                certification.configuration_fingerprint
            ),
            controller_fingerprint=(
                certification.controller_fingerprint
            ),
            status=(
                "passed"
                if certification.certified
                else "failed"
            ),
            certified=bool(certification.certified),
            admission_admitted=admission.admitted,
            admission_reason=admission.reason,
            cases=[
                AgentCertificationCaseEvidence(
                    name=case.name,
                    required=case.required,
                    passed=case.passed,
                    latency_ms=case.latency_ms,
                    executed=bool(
                        case.observations.get("executed", True)
                    ),
                    error_category=case.observations.get(
                        "error_category"
                    ),
                    short_circuited_by=case.observations.get(
                        "triggered_by"
                    ),
                )
                for case in cases
            ],
            failure_cases=list(certification.failure_cases or []),
        )


__all__ = [
    "AGENT_CERTIFICATION_EVIDENCE_VERSION",
    "AgentCertificationCaseEvidence",
    "AgentCertificationEvidenceArtifact",
]
