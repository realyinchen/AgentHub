"""Single production-visible boundary for the pre-Controller chat runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.infra.config import get_settings
from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import PreparedRuntimeTurn

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

LegacyFallbackStatus = Literal["prepared", "disabled"]
LegacyTurnFactory = Callable[..., Awaitable[PreparedRuntimeTurn]]


@dataclass(frozen=True)
class LegacyChatRuntimeResult:
    status: LegacyFallbackStatus
    turn: PreparedRuntimeTurn | None = None
    reason: str = ""


class LegacyChatRuntimeBridge:
    """Gate and lazily load the complete legacy planner/runtime stack."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        turn_factory: LegacyTurnFactory | None = None,
    ) -> None:
        self._enabled = enabled
        self._turn_factory = turn_factory

    @property
    def enabled(self) -> bool:
        if self._enabled is not None:
            return self._enabled
        return bool(get_settings().AGENT_LEGACY_RUNTIME_FALLBACK)

    async def prepare(
        self,
        user_input: UserInput,
        *,
        model_name: str = "",
        agent: CompiledStateGraph | None = None,
    ) -> LegacyChatRuntimeResult:
        if not self.enabled:
            return LegacyChatRuntimeResult(
                status="disabled",
                reason="legacy_runtime_fallback_disabled",
            )
        factory = self._turn_factory or _load_legacy_turn_factory()
        turn = await factory(
            user_input,
            model_name=model_name,
            agent=agent,
        )
        return LegacyChatRuntimeResult(status="prepared", turn=turn)


def _load_legacy_turn_factory() -> LegacyTurnFactory:
    from app.services.agent_runtime.coordinator import (
        prepare_legacy_runtime_turn,
    )

    return prepare_legacy_runtime_turn


__all__ = [
    "LegacyChatRuntimeBridge",
    "LegacyChatRuntimeResult",
    "LegacyFallbackStatus",
]
