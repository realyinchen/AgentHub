"""Verify Agent Core leaf imports are independent of import order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _cold_import(label: str, statement: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", statement],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{label} cold import failed:\n"
            f"{result.stdout}\n{result.stderr}"
        )


def _run() -> None:
    _cold_import(
        "task_first",
        "from app.services.tasks.plan_compiler import TaskPlanCompiler; "
        "from app.services.agent_core.gateway import AgentControllerGateway",
    )
    _cold_import(
        "gateway_first",
        "from app.services.agent_core.gateway import AgentControllerGateway; "
        "from app.services.tasks.plan_compiler import TaskPlanCompiler",
    )
    forbidden = "from app.services." + "agent_core import"
    offenders = []
    for root in ("app", "scripts", "tests"):
        for path in (BACKEND_DIR / root).rglob("*.py"):
            if path.name == Path(__file__).name:
                continue
            if forbidden in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(BACKEND_DIR)))
    if offenders:
        raise AssertionError(
            "Agent Core aggregate imports remain: "
            + ", ".join(sorted(offenders))
        )
    print("Agent Core import boundary verification passed")
    print("task_plan_compiler_first=passed")
    print("agent_controller_gateway_first=passed")
    print("aggregate_agent_core_imports=0")


if __name__ == "__main__":
    _run()
