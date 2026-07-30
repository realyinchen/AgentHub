"""Build a real Shadow gate report from durable production evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)
from app.services.agent_core.evidence_artifact import (
    EvidenceArtifactWriter,
)
from app.services.agent_core.evidence_source import (
    GitSourceStateReader,
)
from app.services.agent_core.prompt_composer import (
    CONTROLLER_PROMPT_VERSION,
)
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateReadRequest,
)
from app.services.agent_core.shadow_gate_evidence import (
    ShadowGateEvidenceArtifact,
)
from app.services.agent_core.shadow_gate_service import (
    ShadowGateService,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read durable Shadow enrollments and emit a machine gate report."
        )
    )
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--configuration-fingerprint", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--review-artifact")
    parser.add_argument("--output", required=True)
    return parser


def _timestamp(value: str) -> datetime:
    candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if candidate.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "timestamps must include an explicit UTC offset"
        )
    return candidate


async def _run(args: argparse.Namespace) -> int:
    writer = EvidenceArtifactWriter()
    writer.require_available(args.output)
    source_state = GitSourceStateReader().require_release_state(
        BACKEND_DIR.parent,
        expected_commit_sha=args.commit_sha,
    )
    generated_at = datetime.now(timezone.utc)
    request = ShadowGateReadRequest(
        commit_sha=source_state.commit_sha,
        controller_fingerprint=current_controller_fingerprint(),
        configuration_fingerprint=args.configuration_fingerprint,
        prompt_version=CONTROLLER_PROMPT_VERSION,
        window_started_at=_timestamp(args.window_start),
        window_ended_at=_timestamp(args.window_end),
        collected_at=generated_at,
        timezone="Asia/Shanghai",
    )
    await init_database_connection()
    try:
        database = get_database()
        async with database.session() as db:
            result = await ShadowGateService().evaluate(
                db,
                request,
                review_artifact_path=args.review_artifact,
            )
        artifact = ShadowGateEvidenceArtifact.from_result(
            source_state=source_state,
            dataset=result.dataset,
            report=result.report,
        )
        rendered = json.dumps(
            artifact.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        writer.write_json_new(args.output, artifact)
        print(rendered)
        return 0 if result.report.status == "passed" else (
            1 if result.report.status == "failed" else 2
        )
    finally:
        await dispose_database()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
