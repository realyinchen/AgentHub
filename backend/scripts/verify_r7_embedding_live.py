"""Non-mutating live canary for the configured R7 embedding generation."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")

from app.infra.database import dispose_database, init_database_connection
from app.infra.embedding_spaces.calibration_dataset import (
    load_default_calibration_dataset,
)
from app.infra.llm.embedding import (
    get_embedding_client,
    probe_embedding_runtime,
)
from app.infra.llm.embedding_config import resolve_embedding_config
from app.infra.llm.embedding_errors import (
    classify_embedding_error,
    safe_embedding_error,
)
from app.infra.llm.manager import get_model_manager
from app.services.routing.semantic_generation import (
    RoutingSemanticGenerationBuilder,
)
from app.services.routing.vector_recall import embedding_fingerprint


def _git_output(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        text=True,
    ).strip()


def _source_state() -> tuple[str, bool]:
    return _git_output("rev-parse", "HEAD"), bool(_git_output("status", "--porcelain"))


async def _run(timeout_seconds: float) -> dict:
    commit_sha, dirty = _source_state()
    artifact = load_default_calibration_dataset()
    evidence = {
        "schema_version": "r7-embedding-live-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_commit_sha": commit_sha,
        "source_dirty": dirty,
        "dataset_version": artifact.dataset.dataset_version,
        "dataset_sha256": artifact.sha256,
        "sample_count": len(artifact.dataset.samples),
        "declared_provider_model": "nvidia/nemotron-3-embed-1b:free",
        "provider_model": "",
        "configured_model_matches_declared": False,
        "observed_dimensions": None,
        "generation_fingerprint": "",
        "threshold": None,
        "precision_score": None,
        "recall_score": None,
        "f1_score": None,
        "status": "failed",
        "failure_category": "",
        "failure_message": "",
        "binding_mutated": False,
        "activation_result": "not_attempted_candidate_safety",
        "rollback_result": "not_attempted_candidate_safety",
        "release_gate_credit": False,
    }
    await init_database_connection()
    try:
        manager = get_model_manager()
        await manager.refresh()
        config = resolve_embedding_config(manager=manager)
        if config is None:
            raise RuntimeError("embedding_model_not_configured")
        evidence["provider_model"] = config.model
        evidence["configured_model_matches_declared"] = config.model.endswith(
            evidence["declared_provider_model"]
        )
        probe = await probe_embedding_runtime(
            config,
            timeout_seconds=timeout_seconds,
            text="R7 embedding generation dimension probe",
        )
        if not probe.probe_ok or probe.embedding_dimensions is None:
            raise RuntimeError(
                f"embedding_probe_failed:{probe.error_category}:{probe.message}"
            )
        evidence["observed_dimensions"] = probe.embedding_dimensions
        embeddings = get_embedding_client(config)
        if embeddings is None:
            raise RuntimeError("embedding_client_unavailable")
        async with asyncio.timeout(timeout_seconds):
            generation = await RoutingSemanticGenerationBuilder().build(
                embeddings=embeddings,
                model_fingerprint="",
                model_fingerprint_for_dimensions=lambda dimensions: (
                    embedding_fingerprint(
                        embeddings,
                        dimensions=dimensions,
                    )
                ),
                expected_dimensions=probe.embedding_dimensions,
                calibrated=True,
                compatibility_threshold=0.0,
            )
        calibration = generation.calibration
        if calibration is None:
            raise RuntimeError("calibration_result_missing")
        evidence.update(
            {
                "generation_fingerprint": generation.generation_fingerprint,
                "threshold": generation.threshold,
                "precision_score": calibration.precision_score,
                "recall_score": calibration.recall_score,
                "f1_score": calibration.f1_score,
                "status": calibration.status,
                "failure_message": ",".join(calibration.failure_codes),
            }
        )
    except Exception as exc:
        evidence["failure_category"] = classify_embedding_error(exc)
        evidence["failure_message"] = safe_embedding_error(exc, limit=240)
    finally:
        await dispose_database()
    return evidence


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--output")
    return parser.parse_args()


async def _main(arguments: argparse.Namespace) -> int:
    evidence = await _run(arguments.timeout_seconds)
    rendered = json.dumps(
        evidence,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if arguments.output:
        output = Path(arguments.output)
        if output.exists():
            raise FileExistsError(f"Evidence path already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_arguments())))
