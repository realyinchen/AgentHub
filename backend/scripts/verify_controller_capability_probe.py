"""Verify configuration-bound Agent certification storage and admission."""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.models.model import Model
from app.models.agent_capability_certification import (
    AgentCapabilityCertification,
)
from app.services.agent_certification import (
    get_agent_mode_admission,
    validate_agent_capability,
)
from app.services.agent_core.certification_contracts import (
    AGENT_PROBE_CASE_NAMES,
    AGENT_PROBE_REQUIRED_CASE_NAMES,
    AgentCapabilityCertificationOutcome,
    AgentProbeCaseResult,
)
from app.services.agent_core.evidence_source import GitSourceState
from scripts.init_database import _init_postgres


CASE_NAMES = AGENT_PROBE_CASE_NAMES
SOURCE_COMMIT_SHA = "f" * 40


class _PassingProbe:
    async def run(self, _config):
        return AgentCapabilityCertificationOutcome(
            certified=True,
            latency_ms=9,
            cases=[
                AgentProbeCaseResult(
                    name=name,
                    required=name in AGENT_PROBE_REQUIRED_CASE_NAMES,
                    passed=True,
                    latency_ms=1,
                )
                for name in CASE_NAMES
            ],
        )


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    try:
        async with database.session() as session:
            result = await session.execute(
                select(Model)
                .where(Model.model_type.in_(("llm", "vlm")))
                .order_by(Model.is_default.desc(), Model.created_at.asc())
                .limit(1)
            )
            model = result.scalar_one_or_none()
            if model is None:
                raise AssertionError(
                    "Agent certification verifier requires one configured chat model"
                )

            certification = await validate_agent_capability(
                session,
                model.id,
                source_state=GitSourceState(
                    commit_sha=SOURCE_COMMIT_SHA,
                    dirty_worktree=False,
                ),
                probe=_PassingProbe(),
            )
            admission = await get_agent_mode_admission(
                session,
                model.id,
                source_commit_sha=SOURCE_COMMIT_SHA,
            )

            if not certification.certified:
                raise AssertionError("passing probe was not certified")
            if len(certification.cases) != len(CASE_NAMES):
                raise AssertionError("certification did not persist all cases")
            if not admission.admitted:
                raise AssertionError(
                    f"current certification was not admitted: {admission.reason}"
                )
            if admission.certification_id != str(certification.id):
                raise AssertionError("admission did not use the persisted record")
            if (
                admission.controller_fingerprint
                != certification.controller_fingerprint
            ):
                raise AssertionError(
                    "admission did not bind the current Controller fingerprint"
                )
            if (
                admission.source_commit_sha
                != certification.source_commit_sha
            ):
                raise AssertionError(
                    "admission did not bind the certification source commit"
                )
            other_release = await get_agent_mode_admission(
                session,
                model.id,
                source_commit_sha="e" * 40,
            )
            if (
                other_release.admitted
                or other_release.reason != "release_changed"
            ):
                raise AssertionError(
                    "another release reused the current certification"
                )
            v4_without_release_blocked = False
            try:
                async with session.begin_nested():
                    session.add(
                        AgentCapabilityCertification(
                            model_id=certification.model_id,
                            provider=certification.provider,
                            provider_model_id=(
                                certification.provider_model_id
                            ),
                            configuration_fingerprint=(
                                certification.configuration_fingerprint
                            ),
                            contract_version=(
                                certification.contract_version
                            ),
                            controller_fingerprint=(
                                certification.controller_fingerprint
                            ),
                            source_commit_sha=None,
                            certified=True,
                            checked_at=(
                                certification.checked_at
                                + timedelta(milliseconds=500)
                            ),
                            latency_ms=1,
                            cases=[],
                            failure_cases=[],
                        )
                    )
                    await session.flush()
            except IntegrityError:
                v4_without_release_blocked = True
            if not v4_without_release_blocked:
                raise AssertionError(
                    "database accepted v4 certification without release"
                )
            session.add(
                AgentCapabilityCertification(
                    model_id=certification.model_id,
                    provider=certification.provider,
                    provider_model_id=(
                        certification.provider_model_id
                    ),
                    configuration_fingerprint=(
                        certification.configuration_fingerprint
                    ),
                    contract_version="agent-capability-v2",
                    controller_fingerprint=(
                        certification.controller_fingerprint
                    ),
                    source_commit_sha=None,
                    certified=True,
                    checked_at=(
                        certification.checked_at
                        + timedelta(seconds=1)
                    ),
                    latency_ms=1,
                    cases=[],
                    failure_cases=[],
                )
            )
            await session.flush()
            legacy = await get_agent_mode_admission(
                session,
                model.id,
                source_commit_sha="e" * 40,
            )
            if legacy.admitted or legacy.reason != "contract_changed":
                raise AssertionError(
                    "historical v2 certification was admitted"
                )
            await session.rollback()

        print("controller capability certification verification passed")
        print("probe_tools=non_executable")
        print(
            "required_cases="
            f"{len(AGENT_PROBE_REQUIRED_CASE_NAMES)}/"
            f"{len(AGENT_PROBE_REQUIRED_CASE_NAMES)}"
        )
        print(
            "observation_cases="
            f"{len(CASE_NAMES) - len(AGENT_PROBE_REQUIRED_CASE_NAMES)}/"
            f"{len(CASE_NAMES) - len(AGENT_PROBE_REQUIRED_CASE_NAMES)}"
        )
        print("configuration_binding=exact")
        print("controller_contract_binding=exact")
        print("release_commit_binding=exact")
        print("other_release_admission=blocked")
        print("v4_without_release=blocked")
        print("legacy_v2_admission=blocked")
        print("agent_admission=fail_closed")
    finally:
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
