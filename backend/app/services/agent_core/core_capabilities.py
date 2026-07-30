from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_CAPABILITY_FIELDS = {
    "conversation_read": "conversation_read",
    "remember_memory": "memory_write",
    "search_memory": "memory_read",
    "forget_memory": "memory_write",
    "cancel_active_task": "task_control",
}

_OPERATION_FIELDS = {
    "conversation_read": "conversation_read",
    "remember_memory_v2": "memory_write",
    "search_memory_v2": "memory_read",
    "forget_memory_v2": "memory_write",
    "create_task_v1": "task_control",
    "plan_task_v1": "task_control",
    "cancel_active_task_v1": "task_control",
}


@dataclass(frozen=True)
class CoreCapabilityAvailability:
    """One capability matrix shared by model projection and runtime admission."""

    conversation_read: bool = False
    memory_read: bool = False
    memory_write: bool = False
    task_control: bool = False

    @classmethod
    def from_settings(
        cls,
        settings: Any | None = None,
    ) -> "CoreCapabilityAvailability":
        if settings is None:
            from app.infra.config import get_settings

            settings = get_settings()
        return cls(
            conversation_read=bool(
                settings.AGENT_CAPABILITY_CONVERSATION_V1
            ),
            memory_read=bool(settings.AGENT_CAPABILITY_MEMORY_READ_V1),
            memory_write=bool(settings.AGENT_CAPABILITY_MEMORY_WRITE_V1),
            task_control=bool(settings.AGENT_CAPABILITY_TASK_V1),
        )

    @classmethod
    def all_enabled(cls) -> "CoreCapabilityAvailability":
        """Explicit test/harness fixture; production never calls this factory."""

        return cls(
            conversation_read=True,
            memory_read=True,
            memory_write=True,
            task_control=True,
        )

    def capability_enabled(self, capability: str) -> bool:
        field_name = _CAPABILITY_FIELDS.get(str(capability or "").strip())
        return bool(field_name and getattr(self, field_name))

    def operation_admission(
        self,
        operation: str,
    ) -> tuple[bool, str] | None:
        field_name = _OPERATION_FIELDS.get(str(operation or "").strip())
        if field_name is None:
            return None
        if bool(getattr(self, field_name)):
            return True, f"core_capability_{field_name}_enabled"
        return False, f"core_capability_{field_name}_disabled"


__all__ = ["CoreCapabilityAvailability"]
