"""Aggregate the modern Agent Core fixture acceptance cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@dataclass(frozen=True)
class AcceptanceCaseSpec:
    case_id: str
    user_input: str
    expected_capability: str
    verifier: str
    execution_level: str


CASE_SPECS = (
    AcceptanceCaseSpec(
        case_id="identity_read",
        user_input="我是谁？",
        expected_capability="search_memory",
        verifier="verify_memory_version_chain_flow.py",
        execution_level="real_journal_postgres_runtime",
    ),
    AcceptanceCaseSpec(
        case_id="identity_update",
        user_input="我现在不叫冰露，我现在叫鲁班",
        expected_capability="remember_memory",
        verifier="verify_memory_version_chain_flow.py",
        execution_level="real_journal_postgres_runtime",
    ),
    AcceptanceCaseSpec(
        case_id="weather_current",
        user_input="今天北京天气怎么样？",
        expected_capability="weather_get",
        verifier="verify_r4_weather_capability.py",
        execution_level="fixture_external_adapter_runtime",
    ),
    AcceptanceCaseSpec(
        case_id="simple_direct",
        user_input="什么是递归？",
        expected_capability="direct_answer",
        verifier="verify_turn_controller_loop.py",
        execution_level="bounded_controller_loop",
    ),
    AcceptanceCaseSpec(
        case_id="external_current_fact",
        user_input="法国总统是谁？",
        expected_capability="web_search",
        verifier="verify_r4_web_capability.py",
        execution_level="fixture_external_adapter_runtime",
    ),
    AcceptanceCaseSpec(
        case_id="deep_book_research",
        user_input="深度搜索下最新的好评图书",
        expected_capability="research_start",
        verifier="verify_r4_research_capability.py",
        execution_level="fixture_research_workflow_runtime",
    ),
)

CONVERSATION_SPEC = AcceptanceCaseSpec(
    case_id="conversation_recall",
    user_input="刚才我说什么了，你回复什么了？",
    expected_capability="conversation_read",
    verifier="verify_conversation_exchange_recall.py",
    execution_level="real_journal_runtime",
)


def run_acceptance_matrix() -> dict[str, Any]:
    specs = (*CASE_SPECS, CONVERSATION_SPEC)
    payloads: dict[str, dict[str, Any]] = {}
    process_results: list[dict[str, Any]] = []
    for verifier in dict.fromkeys(spec.verifier for spec in specs):
        payload, duration_ms = _run_verifier(verifier)
        process_results.append(
            {
                "verifier": verifier,
                "status": "passed",
                "duration_ms": duration_ms,
            }
        )
        for item in _case_payloads(payload):
            case_id = str(item.get("case_id") or "")
            if not case_id or case_id in payloads:
                raise AssertionError(
                    f"duplicate or empty acceptance case: {case_id}"
                )
            payloads[case_id] = item

    results = [
        _validated_result(spec, payloads.get(spec.case_id))
        for spec in specs
    ]
    unexpected = sorted(set(payloads) - {spec.case_id for spec in specs})
    if unexpected:
        raise AssertionError(f"unexpected acceptance cases: {unexpected}")
    return build_report(results, process_results=process_results)


def build_report(
    results: list[dict[str, Any]],
    *,
    process_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    required_ids = {spec.case_id for spec in (*CASE_SPECS, CONVERSATION_SPEC)}
    observed_ids = [str(item.get("case_id") or "") for item in results]
    passed = (
        len(observed_ids) == len(required_ids)
        and set(observed_ids) == required_ids
        and len(set(observed_ids)) == len(observed_ids)
        and all(item.get("status") == "passed" for item in results)
    )
    return {
        "contract": "agent-core-six-case-fixture-v1",
        "controller_decision_source": "fixture",
        "online_model_calls": 0,
        "legacy_router_cases": 0,
        "case_count": len(CASE_SPECS),
        "conversation_case_count": 1,
        "cases": [
            item for item in results if item["case_id"] != "conversation_recall"
        ],
        "conversation_recall": next(
            (
                item
                for item in results
                if item["case_id"] == "conversation_recall"
            ),
            None,
        ),
        "verifiers": list(process_results or []),
        "status": "passed" if passed else "failed",
        "local_core_loop_passed": passed,
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


def _run_verifier(verifier: str) -> tuple[dict[str, Any], int]:
    import time

    path = (BACKEND_ROOT / "scripts" / verifier).resolve()
    path.relative_to((BACKEND_ROOT / "scripts").resolve())
    if not path.is_file():
        raise AssertionError(f"acceptance verifier is missing: {verifier}")
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
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
            f"acceptance verifier failed: {verifier}:"
            f"exit={completed.returncode}"
        )
    return _last_json_object(completed.stdout, verifier=verifier), duration_ms


def _last_json_object(output: str, *, verifier: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise AssertionError(f"acceptance verifier emitted no JSON: {verifier}")


def _case_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cases = payload.get("cases")
    if isinstance(cases, list):
        return [item for item in cases if isinstance(item, dict)]
    return [payload]


def _validated_result(
    spec: AcceptanceCaseSpec,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if payload is None:
        raise AssertionError(f"acceptance case is missing: {spec.case_id}")
    expected = {
        "case_id": spec.case_id,
        "input": spec.user_input,
        "expected_capability": spec.expected_capability,
        "status": "passed",
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise AssertionError(
                f"acceptance case {spec.case_id} {field} mismatch"
            )
    return {
        **payload,
        "verifier": spec.verifier,
        "execution_level": spec.execution_level,
        "controller_decision_source": "fixture",
        "online_model_calls": 0,
        "release_gate_credit": False,
    }


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
    from app.services.agent_core.evidence_artifact import (
        EvidenceArtifactWriter,
    )
    from app.services.agent_core.evidence_source import (
        GitSourceStateReader,
    )

    arguments = _arguments()
    writer = EvidenceArtifactWriter()
    writer.require_available(arguments.output)
    source_state = GitSourceStateReader().require_release_state(
        WORKSPACE_ROOT,
        expected_commit_sha=arguments.commit_sha,
    )
    report = bind_evidence(
        run_acceptance_matrix(),
        source_state=source_state,
        task_document=arguments.task_document,
    )
    writer.write_json_new(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
