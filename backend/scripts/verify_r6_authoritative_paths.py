"""Verify R6 authority, capability, and compatibility boundaries."""

# ruff: noqa: E402

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.config import Settings
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.controller_client import controller_tool_schemas
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)


def _source(relative: str) -> str:
    return (BACKEND_DIR / relative).read_text(encoding="utf-8")


def _imported_modules(relative: str) -> set[str]:
    tree = ast.parse(_source(relative), filename=relative)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _assert_default_flags() -> None:
    fields = Settings.model_fields
    for name in (
        "AGENT_CAPABILITY_CONVERSATION_V1",
        "AGENT_CAPABILITY_MEMORY_READ_V1",
        "AGENT_CAPABILITY_MEMORY_WRITE_V1",
        "AGENT_CAPABILITY_TASK_V1",
    ):
        assert fields[name].default is False, f"{name} must fail closed"
    assert fields["AGENT_LEGACY_MEMORY_WRITE_COMPAT"].default is False


def _assert_projection_matrix() -> None:
    disabled = CapabilityRegistry(
        core_availability=CoreCapabilityAvailability()
    )
    assert disabled.enabled_names == ()
    assert [
        item["function"]["name"]
        for item in controller_tool_schemas(disabled)
    ] == ["request_clarification"]

    read_only = CapabilityRegistry(
        core_availability=CoreCapabilityAvailability(
            conversation_read=True,
            memory_read=True,
        )
    )
    assert read_only.enabled_names == (
        "conversation_read",
        "search_memory",
    )
    names = {
        item["function"]["name"]
        for item in controller_tool_schemas(read_only)
    }
    assert "plan_task" not in names
    assert {"save_memory", "update_memory"}.isdisjoint(names)


def _assert_journal_authority() -> None:
    history_imports = _imported_modules("app/api/v1/chat/history.py")
    assert "app.agents" not in history_imports
    history_source = _source("app/api/v1/chat/history.py")
    assert "LegacyHistoryBackfillPolicy" not in history_source
    assert "read_legacy_checkpointer_history" not in history_source

    runtime_source = _source("app/services/agent_runtime/runtime.py")
    runtime_tree = ast.parse(runtime_source)
    reader = next(
        node
        for node in runtime_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_read_conversation"
    )
    reader_source = ast.get_source_segment(runtime_source, reader) or ""
    assert "JournalConversationReader" in reader_source
    assert "_conversation_window" not in reader_source
    assert "context.metadata" not in reader_source

    legacy_source = _source(
        "app/services/conversation/legacy_history_reader.py"
    )
    assert "get_agent" in legacy_source
    for forbidden in (".add(", ".commit(", ".flush(", ".execute("):
        assert forbidden not in legacy_source


def _assert_versioned_memory_path() -> None:
    compiler = _source("app/services/agent_core/compiler.py")
    assert 'operation="remember_memory_v2"' in compiler
    assert 'operation="search_memory_v2"' in compiler
    assert 'operation="forget_memory_v2"' in compiler

    runtime = _source("app/services/memory/version_runtime.py")
    assert "MemoryCanonicalizer().canonicalize" in runtime
    assert "canonical.status != \"ready\"" in runtime
    assert "MemoryVersionStore(session).commit" in runtime
    assert "MemoryVersionStore(session).forget" in runtime
    assert "MemoryVersionStore(session).list_current" in runtime
    assert "_source_event_id(context)" in runtime

    imports = _imported_modules(
        "app/services/memory/version_runtime.py"
    )
    assert "app.services.memory.orchestrator" not in imports
    assert "app.services.memory.user_state" not in imports

    system_runtime_imports = _imported_modules(
        "app/services/agent_runtime/runtime.py"
    )
    memory_imports = {
        item
        for item in system_runtime_imports
        if item.startswith("app.services.memory")
    }
    assert memory_imports == {
        "app.services.memory.version_contracts",
        "app.services.memory.version_runtime",
    }
    system_runtime = _source("app/services/agent_runtime/runtime.py")
    assert "legacy_memory_write_disabled_for_r6" not in system_runtime
    assert "legacy_operation_requires_routing_plan" not in system_runtime
    assert "memory_write_compat" not in system_runtime
    legacy_compatibility = _source(
        "app/services/agent_runtime/legacy_compatibility.py"
    )
    assert "legacy_memory_write_disabled_for_r6" in legacy_compatibility
    assert "memory_write_compat" in legacy_compatibility
    assert "LegacyRoutingRuntimeCompatibility" in legacy_compatibility


def _main() -> int:
    _assert_default_flags()
    _assert_projection_matrix()
    _assert_journal_authority()
    _assert_versioned_memory_path()
    print(
        json.dumps(
            {
                "contract": "r6-authoritative-paths-v1",
                "journal_is_formal_history_authority": True,
                "checkpointer_compatibility": "retired",
                "core_capability_matrix_shared": True,
                "core_capabilities_default_enabled": False,
                "model_memory_tools": [
                    "remember_memory",
                    "search_memory",
                    "forget_memory",
                ],
                "legacy_model_memory_tools_exposed": False,
                "memory_write_path": [
                    "canonicalizer",
                    "precommit",
                    "version_store",
                ],
                "schema_change_required": False,
                "status": "passed",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
