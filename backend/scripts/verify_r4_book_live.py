"""Run one clean-source LongCat book canary with isolated phases."""

from __future__ import annotations

import argparse
import asyncio
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
from app.services.agent_core.evidence_source import GitSourceStateReader
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.book import BookSearchRuntimeAdapter
from app.services.external_capabilities.canary import CapabilityCanarySpec
from app.services.external_capabilities.live_canary_runner import (
    run_configured_capability_canary,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--query",
        default="适合八岁孩子的中文气象科普书",
    )
    parser.add_argument("--timeout-seconds", type=float, default=60)
    return parser.parse_args()


async def _main(arguments: argparse.Namespace) -> int:
    writer = EvidenceArtifactWriter()
    writer.require_available(arguments.output)
    source = GitSourceStateReader().require_release_state(
        REPOSITORY_ROOT,
        expected_commit_sha=arguments.commit_sha,
    )
    availability = ExternalCapabilityAvailability(book_search=True)
    evidence = await run_configured_capability_canary(
        source=source,
        model_id=arguments.model_id,
        timeout_seconds=arguments.timeout_seconds,
        spec=CapabilityCanarySpec(
            capability="book_search",
            operation="book_search_v1",
            user_message=f"请推荐：{arguments.query}",
            arguments={
                "query": arguments.query,
                "limit": 5,
                "language": "zh-CN",
                "genres": ["科普"],
                "audience": "8岁儿童",
            },
            expected_result_mode="book_evidence",
        ),
        availability=availability,
        external_runtime=ExternalCapabilityRuntime(
            availability=availability,
            adapters=[BookSearchRuntimeAdapter()],
        ),
    )
    writer.write_json_new(arguments.output, evidence)
    print(
        json.dumps(
            evidence.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
    )
    return 0 if evidence.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_arguments())))
