from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.controller_golden_contracts import (
    ControllerGoldenReport,
)


@dataclass(frozen=True)
class DeveloperShadowModelProfile:
    model_type: str
    configured_thinking: bool
    is_active: bool


@dataclass(frozen=True)
class DeveloperShadowAdmissionCandidate:
    admission: AgentModeAdmission
    model_profile: DeveloperShadowModelProfile | None


@dataclass(frozen=True)
class DeveloperPreviewAdmission:
    admission_profile: Literal["developer_preview"]
    admission: AgentModeAdmission
    configured_thinking: bool


class DeveloperPreviewAdmissionError(RuntimeError):
    """Fail-closed developer-preview policy error."""


class DeveloperPreviewAdmissionPolicy:
    """Admit exact-certified chat models without granting release credit."""

    def require(
        self,
        candidate: DeveloperShadowAdmissionCandidate,
        *,
        golden: ControllerGoldenReport,
    ) -> DeveloperPreviewAdmission:
        admission = candidate.admission
        profile = candidate.model_profile
        if (
            not admission.admitted
            or profile is None
            or profile.model_type not in {"llm", "vlm"}
            or not profile.is_active
        ):
            raise DeveloperPreviewAdmissionError(
                "developer_preview_model_admission_missing"
            )
        if (
            admission.certification_id != golden.certification_id
            or admission.configuration_fingerprint
            != golden.configuration_fingerprint
            or admission.controller_fingerprint
            != golden.controller_fingerprint
            or admission.source_commit_sha != golden.commit_sha
        ):
            raise DeveloperPreviewAdmissionError(
                "golden_admission_binding_mismatch"
            )
        return DeveloperPreviewAdmission(
            admission_profile="developer_preview",
            admission=admission,
            configured_thinking=profile.configured_thinking,
        )


__all__ = [
    "DeveloperPreviewAdmission",
    "DeveloperPreviewAdmissionError",
    "DeveloperPreviewAdmissionPolicy",
    "DeveloperShadowAdmissionCandidate",
    "DeveloperShadowModelProfile",
]
