"""Export a safe, reviewable queue of durable Shadow decision differences."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
from app.services.agent_core.shadow_gate_repository import (
    ShadowGateRepository,
)
from app.services.agent_core.shadow_review_queue import (
    ShadowReviewQueueBuilder,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export allowlisted new/legacy signatures for Shadow review."
        )
    )
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--configuration-fingerprint", required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
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
    window_end = _timestamp(args.window_end)
    if generated_at < window_end:
        raise RuntimeError(
            "Shadow review queue requires a closed window"
        )
    request = ShadowGateReadRequest(
        commit_sha=source_state.commit_sha,
        controller_fingerprint=current_controller_fingerprint(),
        configuration_fingerprint=args.configuration_fingerprint,
        prompt_version=CONTROLLER_PROMPT_VERSION,
        window_started_at=_timestamp(args.window_start),
        window_ended_at=window_end,
        collected_at=generated_at,
        timezone="Asia/Shanghai",
    )
    await init_database_connection()
    try:
        database = get_database()
        async with database.session() as db:
            raw = await ShadowGateRepository().read(db, request)
        artifact = ShadowReviewQueueBuilder().build(
            raw,
            source_state=source_state,
        )
        output = writer.write_json_new(args.output, artifact)
        artifact_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        print(
            json.dumps(
                {
                    "artifact_version": artifact.artifact_version,
                    "artifact_hash": artifact_hash,
                    "candidate_count": len(artifact.candidates),
                    "commit_sha": artifact.commit_sha,
                    "controller_fingerprint": (
                        artifact.controller_fingerprint
                    ),
                    "configuration_fingerprint": (
                        artifact.configuration_fingerprint
                    ),
                    "prompt_version": artifact.prompt_version,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    finally:
        await dispose_database()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
