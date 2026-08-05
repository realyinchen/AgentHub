"""Run and write one isolated developer Shadow preview."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.services.agent_core.evidence_artifact import EvidenceArtifactWriter
from scripts.developer_shadow_preview.contracts import (
    DeveloperShadowPreviewCommand,
)
from scripts.developer_shadow_preview.service import (
    DeveloperShadowPreviewService,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an isolated developer Shadow HTTP preview."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--remote-ref", default="origin/dev")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--golden-artifact", required=True)
    parser.add_argument("--turn-count", type=int, default=20)
    parser.add_argument("--http-timeout-seconds", type=float, default=120)
    parser.add_argument(
        "--observation-timeout-seconds",
        type=float,
        default=300,
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-output", required=True)
    return parser


async def _run(args: argparse.Namespace) -> int:
    writer = EvidenceArtifactWriter()
    writer.require_available(args.output)
    writer.require_available(args.review_output)
    command = DeveloperShadowPreviewCommand(
        base_url=args.base_url,
        commit_sha=args.commit_sha,
        remote_ref=args.remote_ref,
        model_id=args.model_id,
        golden_artifact=args.golden_artifact,
        turn_count=args.turn_count,
        http_timeout_seconds=args.http_timeout_seconds,
        observation_timeout_seconds=(
            args.observation_timeout_seconds
        ),
    )
    result = await DeveloperShadowPreviewService().run(
        command,
        repository_root=REPOSITORY_ROOT,
    )
    review_path = writer.write_json_new(
        args.review_output,
        result.review_queue,
    )
    review_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()
    if review_sha != result.preview.review_queue_sha256:
        raise RuntimeError("review_queue_hash_mismatch")
    writer.write_json_new(args.output, result.preview)
    print(
        json.dumps(
            result.preview.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
