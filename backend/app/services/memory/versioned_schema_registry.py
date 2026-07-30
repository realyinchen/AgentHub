from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MemoryCardinality = Literal["single", "multi"]


@dataclass(frozen=True)
class VersionedMemorySchema:
    schema_key: str
    version: int
    predicates: frozenset[str]
    cardinality: MemoryCardinality
    required_value_fields: tuple[str, ...]
    identity_value_fields: tuple[str, ...]
    required_qualifier_fields: tuple[str, ...] = ()
    identity_qualifier_fields: tuple[str, ...] = ()
    self_subject_only: bool = False
    sensitive: bool = False


class VersionedMemorySchemaRegistry:
    """The sole authority that maps model predicates to storage schemas."""

    def __init__(self) -> None:
        schemas = (
            VersionedMemorySchema(
                schema_key="identity.self_reported_name",
                version=1,
                predicates=frozenset(
                    {"name", "self_reported_name", "identity.name"}
                ),
                cardinality="single",
                required_value_fields=("name",),
                identity_value_fields=(),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="identity.preferred_address",
                version=1,
                predicates=frozenset(
                    {"preferred_address", "call_me", "address_as"}
                ),
                cardinality="single",
                required_value_fields=("address",),
                identity_value_fields=(),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="identity.alias",
                version=1,
                predicates=frozenset({"alias", "also_known_as"}),
                cardinality="multi",
                required_value_fields=("alias",),
                identity_value_fields=("alias",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="preference.entity",
                version=1,
                predicates=frozenset(
                    {"preference", "likes", "dislikes", "prefers"}
                ),
                cardinality="multi",
                required_value_fields=("entity", "polarity"),
                identity_value_fields=("entity",),
                required_qualifier_fields=("entity_type",),
                identity_qualifier_fields=("entity_type",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="relationship.entity",
                version=1,
                predicates=frozenset(
                    {"relationship", "related_to", "knows"}
                ),
                cardinality="multi",
                required_value_fields=("entity", "relation"),
                identity_value_fields=("entity",),
                required_qualifier_fields=("entity_type",),
                identity_qualifier_fields=("entity_type",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="instruction.behavior",
                version=1,
                predicates=frozenset(
                    {"instruction", "behavior_instruction", "always_do"}
                ),
                cardinality="multi",
                required_value_fields=("instruction",),
                identity_value_fields=("instruction",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="feedback.outcome",
                version=1,
                predicates=frozenset({"feedback", "outcome_feedback"}),
                cardinality="multi",
                required_value_fields=("target", "outcome"),
                identity_value_fields=("target",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="temporary.state",
                version=1,
                predicates=frozenset({"temporary_state", "current_state"}),
                cardinality="multi",
                required_value_fields=("state", "value"),
                identity_value_fields=("state",),
                self_subject_only=True,
            ),
        )
        self._by_key = {item.schema_key: item for item in schemas}
        self._by_predicate = {
            predicate: item
            for item in schemas
            for predicate in item.predicates
        }

    def resolve_predicate(
        self,
        predicate: str,
    ) -> VersionedMemorySchema | None:
        return self._by_predicate.get(_normalize_predicate(predicate))

    def require_schema(self, schema_key: str) -> VersionedMemorySchema:
        schema = self._by_key.get(str(schema_key or "").strip().lower())
        if schema is None:
            raise ValueError(f"unknown memory schema: {schema_key}")
        return schema

    @property
    def schema_keys(self) -> tuple[str, ...]:
        return tuple(self._by_key)


def _normalize_predicate(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )
