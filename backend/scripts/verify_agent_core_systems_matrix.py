"""Aggregate current-commit evidence for the local Agent Core systems."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class CoreSystemSpec:
    domain_id: str
    verifier: str
    verification_level: str
    required_markers: tuple[str, ...]


SYSTEM_SPECS = (
    CoreSystemSpec(
        domain_id="planning",
        verifier="verify_task_plan_coordination_flow.py",
        verification_level="real_harness_postgres_task_coordinator",
        required_markers=(
            "task plan coordination verification passed",
            "fixture_registry=all_enabled_explicit",
            "plan_task_model_tools=1",
            "new_version_resume=completed",
        ),
    ),
    CoreSystemSpec(
        domain_id="execution",
        verifier="verify_task_runner_flow.py",
        verification_level="real_postgres_task_runner",
        required_markers=(
            "task runner verification passed",
            "fixture_registry=all_enabled_explicit",
            "waiting_implicit_resumes=0",
            "bounded_final_cursor=2",
        ),
    ),
    CoreSystemSpec(
        domain_id="tool_invocation",
        verifier="verify_tool_admission_flow.py",
        verification_level="real_system_runtime_admission",
        required_markers=("tool admission verification passed",),
    ),
    CoreSystemSpec(
        domain_id="state_management",
        verifier="verify_working_state_rebuild.py",
        verification_level="real_journal_checkpoint_rebuild",
        required_markers=(
            "working state rebuild verification passed",
            "checkpoint_messages=0",
            "terminal_events_per_request=1",
        ),
    ),
    CoreSystemSpec(
        domain_id="long_term_memory",
        verifier="verify_memory_version_chain_flow.py",
        verification_level="real_journal_postgres_memory_runtime",
        required_markers=(
            "memory version chain verification passed",
            "concurrent_revision=linear",
            "forget=tombstone",
        ),
    ),
    CoreSystemSpec(
        domain_id="short_term_memory",
        verifier="verify_conversation_exchange_recall.py",
        verification_level="real_conversation_journal_runtime",
        required_markers=(
            "conversation exchange recall verification passed",
            "current_request_excluded=true",
            "unsafe_metadata_persisted=false",
        ),
    ),
    CoreSystemSpec(
        domain_id="context_compression",
        verifier="verify_context_compression_flow.py",
        verification_level="real_journal_derived_summary",
        required_markers=(
            "context compression verification passed",
            "summary_source=conversation_journal",
            "summary_is_derived_cache=true",
            "journal_events_preserved=43",
        ),
    ),
    CoreSystemSpec(
        domain_id="failure_recovery",
        verifier="verify_task_recovery_flow.py",
        verification_level="real_postgres_receipt_reconciliation",
        required_markers=(
            "task recovery verification passed",
            "fixture_registry=all_enabled_explicit",
            "action_1_recovery_executions=0",
            "terminal_reacquire=blocked",
        ),
    ),
)

PRODUCTION_CAPABILITY_FLAGS = (
    "AGENT_CAPABILITY_CONVERSATION_V1",
    "AGENT_CAPABILITY_MEMORY_READ_V1",
    "AGENT_CAPABILITY_MEMORY_WRITE_V1",
    "AGENT_CAPABILITY_TASK_V1",
)


def run_core_systems_matrix() -> dict[str, Any]:
    _require_exact_specs()
    flags = _effective_capability_flags()
    enabled = sorted(name for name, value in flags.items() if value)
    if enabled:
        raise AssertionError(
            "production capability flags must remain disabled: "
            + ",".join(enabled)
        )
    env_path = BACKEND_ROOT / ".env"
    config_before = _optional_sha256(env_path)
    results = [_run_verifier(spec) for spec in SYSTEM_SPECS]
    config_after = _optional_sha256(env_path)
    if config_before != config_after:
        raise AssertionError("a core systems verifier changed backend/.env")
    return build_report(
        results,
        production_flags=flags,
        production_config_unchanged=True,
    )


def build_report(
    results: list[dict[str, Any]],
    *,
    production_flags: dict[str, bool] | None = None,
    production_config_unchanged: bool = True,
) -> dict[str, Any]:
    required_ids = {spec.domain_id for spec in SYSTEM_SPECS}
    observed_ids = [str(item.get("domain_id") or "") for item in results]
    passed = (
        len(observed_ids) == len(required_ids)
        and set(observed_ids) == required_ids
        and len(set(observed_ids)) == len(observed_ids)
        and all(item.get("status") == "passed" for item in results)
        and production_config_unchanged
        and not any((production_flags or {}).values())
    )
    return {
        "contract": "agent-core-systems-matrix-v1",
        "domain_count": len(SYSTEM_SPECS),
        "domains": results,
        "online_model_calls": 0,
        "production_capability_flags": production_flags or {},
        "production_flags_changed": False,
        "production_config_unchanged": production_config_unchanged,
        "status": "passed" if passed else "failed",
        "fixture_or_local_core_loop_passed": passed,
        "release_gate_credit": False,
    }


def bind_evidence(
    report: dict[str, Any],
    *,
    source_state,
    task_document: Path,
) -> dict[str, Any]:
    return {
        **report,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_state": source_state.model_dump(mode="json"),
        "task_document": str(
            task_document.resolve().relative_to(WORKSPACE_ROOT.resolve())
        ).replace("\\", "/"),
        "task_document_sha256": hashlib.sha256(
            task_document.read_bytes()
        ).hexdigest(),
    }


def validate_verifier_output(spec: CoreSystemSpec, output: str) -> None:
    missing = [marker for marker in spec.required_markers if marker not in output]
    if missing:
        raise AssertionError(
            f"core systems verifier markers missing: {spec.verifier}:"
            + ",".join(missing)
        )


def _run_verifier(spec: CoreSystemSpec) -> dict[str, Any]:
    path = (BACKEND_ROOT / "scripts" / spec.verifier).resolve()
    path.relative_to((BACKEND_ROOT / "scripts").resolve())
    if not path.is_file():
        raise AssertionError(f"core systems verifier is missing: {spec.verifier}")
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(path)],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=environment,
    )
    duration_ms = int((time.perf_counter() - started) * 1_000)
    if completed.returncode != 0:
        raise AssertionError(
            f"core systems verifier failed: {spec.verifier}:"
            f"exit={completed.returncode}"
        )
    validate_verifier_output(spec, completed.stdout)
    return {
        "domain_id": spec.domain_id,
        "verifier": spec.verifier,
        "verification_level": spec.verification_level,
        "status": "passed",
        "duration_ms": duration_ms,
    }


def _effective_capability_flags() -> dict[str, bool]:
    values = dotenv_values(BACKEND_ROOT / ".env")
    return {
        name: _truthy(os.environ.get(name, values.get(name)))
        for name in PRODUCTION_CAPABILITY_FLAGS
    }


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _require_exact_specs() -> None:
    domain_ids = [spec.domain_id for spec in SYSTEM_SPECS]
    verifiers = [spec.verifier for spec in SYSTEM_SPECS]
    if len(domain_ids) != 8 or len(set(domain_ids)) != 8:
        raise AssertionError("core systems matrix must contain eight unique domains")
    if len(set(verifiers)) != len(verifiers):
        raise AssertionError("each core systems domain must own one verifier")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--task-document",
        type=Path,
        default=WORKSPACE_ROOT / "local-dev/AGENT_CORE_ARCHITECTURE.md",
    )
    return parser.parse_args()


def main() -> int:
    from app.services.agent_core.evidence_artifact import EvidenceArtifactWriter
    from app.services.agent_core.evidence_source import GitSourceStateReader

    arguments = _arguments()
    writer = EvidenceArtifactWriter()
    writer.require_available(arguments.output)
    source_state = GitSourceStateReader().require_release_state(
        WORKSPACE_ROOT,
        expected_commit_sha=arguments.commit_sha,
    )
    report = bind_evidence(
        run_core_systems_matrix(),
        source_state=source_state,
        task_document=arguments.task_document,
    )
    writer.write_json_new(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
