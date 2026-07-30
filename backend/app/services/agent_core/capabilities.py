from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.services.conversation.contracts import ConversationReadRequest
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.contracts import WeatherGetInput
from app.services.memory.version_contracts import (
    ForgetMemoryRequest,
    MemoryAssertionProposal,
    RememberMemoryRequest,
    SearchMemoryRequest,
)


class CapabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationReadInput(ConversationReadRequest):
    pass


class RememberMemoryInput(RememberMemoryRequest):
    pass


class SearchMemoryInput(SearchMemoryRequest):
    pass


class ForgetMemoryInput(ForgetMemoryRequest):
    pass


class CancelActiveTaskInput(CapabilityInput):
    reason: str = Field(default="", max_length=1_000)


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    description: str
    input_model: type[BaseModel]
    side_effect: bool
    enabled: bool
    compiler_key: str


class CapabilityRegistry:
    """Small app-owned registry; it never validates or executes proposals."""

    def __init__(
        self,
        *,
        availability: ExternalCapabilityAvailability | None = None,
    ) -> None:
        external = availability or ExternalCapabilityAvailability.from_settings()
        self._specs = {
            "conversation_read": CapabilitySpec(
                name="conversation_read",
                description=(
                    "Read exact prior user messages, assistant replies, or exchanges "
                    "from the current conversation."
                ),
                input_model=ConversationReadInput,
                side_effect=False,
                enabled=True,
                compiler_key="conversation_read",
            ),
            "remember_memory": CapabilitySpec(
                name="remember_memory",
                description=(
                    "Propose complete user-authored facts for long-term memory. "
                    "Use only when the user expressed durable information."
                ),
                input_model=RememberMemoryInput,
                side_effect=True,
                enabled=True,
                compiler_key="remember_memory",
            ),
            "search_memory": CapabilitySpec(
                name="search_memory",
                description=(
                    "Search current, non-forgotten long-term facts about this "
                    "user. At least one of query or predicate must be non-empty."
                ),
                input_model=SearchMemoryInput,
                side_effect=False,
                enabled=True,
                compiler_key="search_memory",
            ),
            "forget_memory": CapabilitySpec(
                name="forget_memory",
                description=(
                    "Forget one or more existing long-term facts identified semantically."
                ),
                input_model=ForgetMemoryInput,
                side_effect=True,
                enabled=True,
                compiler_key="forget_memory",
            ),
            "cancel_active_task": CapabilitySpec(
                name="cancel_active_task",
                description=(
                    "Cancel the current conversation's active durable task. "
                    "Do not supply a task identifier."
                ),
                input_model=CancelActiveTaskInput,
                side_effect=True,
                enabled=True,
                compiler_key="cancel_active_task",
            ),
        }
        if external.weather_get:
            self._specs["weather_get"] = CapabilitySpec(
                name="weather_get",
                description=(
                    "Retrieve current weather evidence for one explicit location "
                    "and date. Supply business fields only."
                ),
                input_model=WeatherGetInput,
                side_effect=False,
                enabled=True,
                compiler_key="weather_get",
            )

    def get(self, name: str) -> CapabilitySpec | None:
        return self._specs.get(str(name or "").strip())

    def require_enabled(self, name: str) -> CapabilitySpec:
        spec = self.get(name)
        if spec is None:
            raise ValueError(f"unknown capability: {name}")
        if not spec.enabled:
            raise ValueError(f"capability is not enabled: {name}")
        return spec

    @property
    def enabled_names(self) -> tuple[str, ...]:
        return tuple(
            name for name, spec in self._specs.items() if spec.enabled
        )

    def tool_schemas(self) -> tuple[dict, ...]:
        """Project one authoritative input contract into inert model schemas."""

        schemas: list[dict] = []
        for name in self.enabled_names:
            spec = self._specs[name]
            parameters = spec.input_model.model_json_schema()
            parameters.setdefault("additionalProperties", False)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec.description,
                        "strict": True,
                        "parameters": parameters,
                    },
                }
            )
        return tuple(schemas)
