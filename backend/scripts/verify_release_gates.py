"""Aggregate exact-commit gate evidence into the sole release report."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
REQUIRED_GATES = (
    "G-ARCH-01",
    "G-CONTRACT-01",
    "G-JOURNAL-01",
    "G-MEMORY-01",
    "G-TASK-01",
    "G-MODEL-01",
    "G-CONTROLLER-01",
    "G-LOOP-01",
    "G-SHADOW-01",
    "G-PUBLISH-01",
    "G-SECURITY-01",
    "G-PERF-01",
    "G-MIGRATION-01",
    "G-EMBEDDING-01",
    "G-LEGACY-01",
    "G-UI-01",
    "G-E2E-01",
    "G-ROLLBACK-01",
    "G-REGRESSION-01",
)


def build_release_report(
    *,
    expected_commit_sha: str,
    task_document: Path,
    evidence_dir: Path,
) -> dict[str, Any]:
    actual_commit = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    task_hash = _sha256_file(task_document) if task_document.is_file() else ""
    generated_at = datetime.now(timezone.utc).isoformat()
    source_failure = ""
    if actual_commit != expected_commit_sha:
        source_failure = "source_commit_mismatch"
    elif dirty:
        source_failure = "dirty_worktree"
    elif not task_hash:
        source_failure = "task_document_missing"

    gate_records = [
        _load_gate(
            gate_id,
            evidence_dir=evidence_dir,
            expected_commit_sha=expected_commit_sha,
            task_document_sha256=task_hash,
            source_failure=source_failure,
        )
        for gate_id in REQUIRED_GATES
    ]
    _apply_legacy_flag_gate(gate_records)

    statuses = {record["status"] for record in gate_records}
    if source_failure or "failed" in statuses:
        overall = "failed"
    elif statuses == {"passed"}:
        overall = "release_ready"
    else:
        overall = "blocked"

    fingerprints = {
        str(record.get("config_fingerprint") or "")
        for record in gate_records
        if record["status"] == "passed"
    } - {""}
    if overall == "release_ready" and len(fingerprints) != 1:
        overall = "failed"
        gate_records.append(
            _generated_gate(
                gate_id="G-EVIDENCE-CONSISTENCY",
                status="failed",
                reason="passed_gate_config_fingerprints_do_not_match",
            )
        )

    return {
        "release_id": f"agent-core-{expected_commit_sha[:12]}",
        "commit_sha": actual_commit,
        "expected_commit_sha": expected_commit_sha,
        "dirty_worktree": dirty,
        "task_document_version": "1.3",
        "task_document_sha256": task_hash,
        "database_migration_head": _migration_head(),
        "database_schema_fingerprint": _shared_value(
            gate_records,
            "database_schema_fingerprint",
        ),
        "model_config_fingerprint": _shared_value(
            gate_records,
            "model_config_fingerprint",
        ),
        "prompt_version": "controller-prompt-v1",
        "capability_schema_version": _capability_schema_fingerprint(),
        "dataset_versions": _dataset_versions(),
        "generated_at": generated_at,
        "overall_status": overall,
        "source_failure": source_failure,
        "gates": gate_records,
    }


def _load_gate(
    gate_id: str,
    *,
    evidence_dir: Path,
    expected_commit_sha: str,
    task_document_sha256: str,
    source_failure: str,
) -> dict[str, Any]:
    path = evidence_dir / f"{gate_id}.json"
    if source_failure:
        return _generated_gate(gate_id, "blocked", source_failure)
    if not path.is_file():
        return _generated_gate(gate_id, "blocked", "evidence_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _generated_gate(gate_id, "failed", "evidence_invalid_json")
    if payload.get("gate_id") != gate_id:
        return _generated_gate(gate_id, "failed", "gate_identity_mismatch")
    if payload.get("commit_sha") != expected_commit_sha:
        return _generated_gate(gate_id, "blocked", "gate_commit_mismatch")
    if payload.get("task_document_sha256") != task_document_sha256:
        return _generated_gate(gate_id, "blocked", "task_document_hash_mismatch")
    status = str(payload.get("status") or "")
    if status not in {"passed", "failed", "blocked"}:
        return _generated_gate(gate_id, "failed", "gate_status_invalid")
    if status == "passed" and not _validate_passed_evidence(payload):
        return _generated_gate(gate_id, "failed", "passed_evidence_invalid")
    return {
        "gate_id": gate_id,
        "status": status,
        "verifier": str(payload.get("verifier") or ""),
        "command": str(payload.get("command") or ""),
        "evidence_paths": list(payload.get("evidence_paths") or []),
        "evidence_sha256": str(payload.get("evidence_sha256") or ""),
        "started_at": payload.get("started_at"),
        "completed_at": payload.get("completed_at"),
        "sample_count": int(payload.get("sample_count") or 0),
        "failure_count": int(payload.get("failure_count") or 0),
        "config_fingerprint": str(payload.get("config_fingerprint") or ""),
        "database_schema_fingerprint": str(
            payload.get("database_schema_fingerprint") or ""
        ),
        "model_config_fingerprint": str(payload.get("model_config_fingerprint") or ""),
        "reason": str(payload.get("reason") or ""),
    }


def _validate_passed_evidence(payload: dict[str, Any]) -> bool:
    if int(payload.get("failure_count") or 0) != 0:
        return False
    if int(payload.get("sample_count") or 0) < 1:
        return False
    if not str(payload.get("verifier") or "").strip():
        return False
    if not str(payload.get("command") or "").strip():
        return False
    if not str(payload.get("config_fingerprint") or "").strip():
        return False
    evidence_paths = payload.get("evidence_paths")
    expected_hash = str(payload.get("evidence_sha256") or "")
    if not isinstance(evidence_paths, list) or not evidence_paths:
        return False
    try:
        paths = [_workspace_path(str(item)) for item in evidence_paths]
    except ValueError:
        return False
    if any(not path.is_file() for path in paths):
        return False
    return expected_hash == _combined_sha256(paths)


def _apply_legacy_flag_gate(gates: list[dict[str, Any]]) -> None:
    from app.infra.config import get_settings

    settings = get_settings()
    blockers = [
        name
        for name in (
            "AGENT_LEGACY_RUNTIME_FALLBACK",
            "AGENT_LEGACY_MEMORY_WRITE_COMPAT",
            "AGENT_LEGACY_HISTORY_READ_FALLBACK",
        )
        if bool(getattr(settings, name))
    ]
    if not blockers:
        return
    gate = next(item for item in gates if item["gate_id"] == "G-LEGACY-01")
    gate.update(
        status="blocked",
        reason="legacy_flags_enabled:" + ",".join(blockers),
    )


def _generated_gate(gate_id: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": status,
        "verifier": "",
        "command": "",
        "evidence_paths": [],
        "evidence_sha256": "",
        "started_at": None,
        "completed_at": None,
        "sample_count": 0,
        "failure_count": 0 if status == "blocked" else 1,
        "config_fingerprint": "",
        "database_schema_fingerprint": "",
        "model_config_fingerprint": "",
        "reason": reason,
    }


def _workspace_path(value: str) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else WORKSPACE_ROOT / path).resolve()
    resolved.relative_to(WORKSPACE_ROOT.resolve())
    return resolved


def _combined_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path.relative_to(WORKSPACE_ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=WORKSPACE_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _migration_head() -> str:
    pattern = re.compile(r"^change_(\d+)")
    names = [path.name for path in (BACKEND_ROOT / "scripts/sql").glob("*.sql")]
    changes = [
        (int(match.group(1)), name)
        for name in names
        if (match := pattern.match(name)) is not None
    ]
    return max(changes)[1] if changes else ""


def _capability_schema_fingerprint() -> str:
    paths = [
        BACKEND_ROOT / "app/services/agent_core/capabilities.py",
        BACKEND_ROOT / "app/services/agent_core/contracts.py",
        BACKEND_ROOT / "app/services/agent_core/core_capabilities.py",
    ]
    return _combined_sha256(paths)


def _dataset_versions() -> list[str]:
    return sorted(path.stem for path in (BACKEND_ROOT / "evals").glob("*.json"))


def _shared_value(records: list[dict[str, Any]], field: str) -> str:
    values = {
        str(record.get(field) or "")
        for record in records
        if record["status"] == "passed"
    } - {""}
    return next(iter(values)) if len(values) == 1 else ""


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument(
        "--task-document",
        type=Path,
        default=WORKSPACE_ROOT / "local-dev/AGENT_CORE_ARCHITECTURE.md",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=WORKSPACE_ROOT / "local-dev/release-evidence",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit_sha):
        parser.error("--commit-sha must be a full lowercase Git SHA")
    report = build_release_report(
        expected_commit_sha=args.commit_sha,
        task_document=args.task_document,
        evidence_dir=args.evidence_dir,
    )
    _write_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == "release_ready" else 1


if __name__ == "__main__":
    sys.exit(main())
