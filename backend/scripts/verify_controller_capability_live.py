"""Run and persist Agent capability v4 for one explicit configured model."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
)
from app.services.agent_core.certification_evidence import (
    AgentCertificationEvidenceArtifact,
)
from app.services.agent_core.evidence_artifact import (
    EvidenceArtifactWriter,
)
from app.services.agent_core.evidence_source import (
    GitSourceState,
    GitSourceStateReader,
)


async def _select_model(session, model_id: str):
    from app.models.model import Model

    try:
        parsed = uuid.UUID(model_id)
    except ValueError as exc:
        raise AssertionError("--model-id must be a UUID") from exc
    query = select(Model).where(
        Model.model_type.in_(("llm", "vlm")),
        Model.is_active.is_(True),
        Model.id == parsed,
    )
    result = await session.execute(query.limit(1))
    model = result.scalar_one_or_none()
    if model is None:
        raise AssertionError("selected active chat model was not found")
    return model


async def _run(
    model_id: str,
    timeout_seconds: float,
    *,
    source_state: GitSourceState,
) -> AgentCertificationEvidenceArtifact:
    from app.infra.database import (
        dispose_database,
        get_database,
        init_database_connection,
    )
    from app.services.agent_certification import (
        get_agent_mode_admission,
        validate_agent_capability,
    )
    from scripts.init_database import _init_postgres

    _init_postgres()
    await init_database_connection()
    database = get_database()
    try:
        async with database.session() as session:
            model = await _select_model(session, model_id)
            certification = await validate_agent_capability(
                session,
                model.id,
                source_state=source_state,
                timeout_seconds=timeout_seconds,
            )
            admission = await get_agent_mode_admission(
                session,
                model.id,
                source_commit_sha=source_state.commit_sha,
            )
            if certification.contract_version != (
                AGENT_CERTIFICATION_CONTRACT_VERSION
            ):
                raise AssertionError("live probe persisted the wrong contract")
            if len(certification.cases) != 10:
                raise AssertionError("live probe did not run all 10 cases")
            artifact = AgentCertificationEvidenceArtifact.build(
                source_state=source_state,
                certification=certification,
                admission=admission,
                generated_at=datetime.now(timezone.utc),
            )
        return artifact
    finally:
        await dispose_database()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=45,
    )
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


async def _main(arguments: argparse.Namespace) -> int:
    writer = EvidenceArtifactWriter()
    writer.require_available(arguments.output)
    source_state = GitSourceStateReader().require_release_state(
        BACKEND_DIR.parent,
        expected_commit_sha=arguments.commit_sha,
    )
    artifact = await _run(
        arguments.model_id,
        arguments.timeout_seconds,
        source_state=source_state,
    )
    writer.write_json_new(arguments.output, artifact)
    print(
        json.dumps(
            artifact.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if artifact.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_arguments())))
