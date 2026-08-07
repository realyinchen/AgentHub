from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MemoryCardinality = Literal["single", "multi"]
MemoryCategory = Literal[
    "identity",
    "possess",
    "prefer",
    "relate",
    "behave",
    "feedback",
    "state",
]


@dataclass(frozen=True)
class VersionedMemorySchema:
    schema_key: str
    version: int
    category: MemoryCategory
    predicates: frozenset[str]
    cardinality: MemoryCardinality
    required_value_fields: tuple[str, ...]
    identity_value_fields: tuple[str, ...]
    required_qualifier_fields: tuple[str, ...] = ()
    identity_qualifier_fields: tuple[str, ...] = ()
    self_subject_only: bool = False
    sensitive: bool = False


class VersionedMemorySchemaRegistry:
    """Broad relationship categories with open entities.

    Memory is modeled as "self -- relationship category -- object". Only the
    category and the self-scope are controlled; the object entity and its
    optional entity_type are open vocabulary and never registered. Unknown
    predicates are classified into a category before being rejected.
    """

    def __init__(self) -> None:
        schemas = (
            VersionedMemorySchema(
                schema_key="identity.self_reported_name",
                version=1,
                category="identity",
                predicates=frozenset(
                    {
                        "identity",
                        "name",
                        "self_reported_name",
                        "identity.name",
                        "called",
                        "is_called",
                        "名字",
                        "姓名",
                        "叫",
                    }
                ),
                cardinality="single",
                required_value_fields=("name",),
                identity_value_fields=(),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="identity.preferred_address",
                version=1,
                category="identity",
                predicates=frozenset(
                    {
                        "preferred_address",
                        "call_me",
                        "address_as",
                        "称呼",
                        "地址",
                    }
                ),
                cardinality="single",
                required_value_fields=("address",),
                identity_value_fields=(),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="identity.alias",
                version=1,
                category="identity",
                predicates=frozenset(
                    {"alias", "also_known_as", "别名", "昵称"}
                ),
                cardinality="multi",
                required_value_fields=("alias",),
                identity_value_fields=("alias",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="preference.entity",
                version=1,
                category="prefer",
                predicates=frozenset(
                    {
                        "prefer",
                        "preference",
                        "likes",
                        "dislikes",
                        "prefers",
                        "wants",
                        "喜欢",
                        "不喜欢",
                        "讨厌",
                        "偏好",
                        "想要",
                    }
                ),
                cardinality="multi",
                required_value_fields=("entity", "polarity"),
                identity_value_fields=("entity",),
                required_qualifier_fields=(),
                identity_qualifier_fields=(),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="relationship.entity",
                version=1,
                category="relate",
                predicates=frozenset(
                    {
                        "relate",
                        "relationship",
                        "related_to",
                        "knows",
                        "认识",
                        "朋友",
                        "同事",
                        "家人",
                        "关系",
                    }
                ),
                cardinality="multi",
                required_value_fields=("entity", "relation"),
                identity_value_fields=("entity",),
                required_qualifier_fields=(),
                identity_qualifier_fields=(),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="possession.entity",
                version=1,
                category="possess",
                predicates=frozenset(
                    {
                        "possess",
                        "possession",
                        "has",
                        "have",
                        "own",
                        "owns",
                        "has_a",
                        "pet",
                        "拥有",
                        "有",
                        "养",
                        "我的",
                        "物品",
                        "宠物",
                    }
                ),
                cardinality="multi",
                required_value_fields=("entity",),
                identity_value_fields=("entity",),
                required_qualifier_fields=(),
                identity_qualifier_fields=(),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="instruction.behavior",
                version=1,
                category="behave",
                predicates=frozenset(
                    {
                        "behave",
                        "instruction",
                        "behavior_instruction",
                        "always_do",
                        "希望",
                        "不要",
                        "请记住",
                        "规则",
                        "行为",
                    }
                ),
                cardinality="multi",
                required_value_fields=("instruction",),
                identity_value_fields=("instruction",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="feedback.outcome",
                version=1,
                category="feedback",
                predicates=frozenset(
                    {
                        "feedback",
                        "outcome_feedback",
                        "反馈",
                        "效果",
                        "结果",
                    }
                ),
                cardinality="multi",
                required_value_fields=("target", "outcome"),
                identity_value_fields=("target",),
                self_subject_only=True,
            ),
            VersionedMemorySchema(
                schema_key="temporary.state",
                version=1,
                category="state",
                predicates=frozenset(
                    {
                        "state",
                        "status",
                        "temporary_state",
                        "current_state",
                        "状态",
                        "当前",
                        "暂时",
                    }
                ),
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
        """Resolve a model predicate, classifying open synonyms by category."""

        schema = self._by_predicate.get(_normalize_predicate(predicate))
        if schema is not None:
            return schema
        key = _classify_predicate(predicate)
        if key is None:
            return None
        return self._by_key.get(key)

    def require_schema(self, schema_key: str) -> VersionedMemorySchema:
        schema = self._by_key.get(str(schema_key or "").strip().lower())
        if schema is None:
            raise ValueError(f"unknown memory schema: {schema_key}")
        return schema

    @property
    def schema_keys(self) -> tuple[str, ...]:
        return tuple(self._by_key)

    @property
    def categories(self) -> tuple[MemoryCategory, ...]:
        return tuple(dict.fromkeys(item.category for item in self._by_key.values()))


def _classify_predicate(predicate: str) -> str | None:
    """Open-vocabulary classification into a broad relationship category."""

    text = str(predicate or "").strip().lower().replace("_", " ").replace("-", " ")
    if not text:
        return None
    if any(token in text for token in ("alias", "also known as", "别名", "昵称")):
        return "identity.alias"
    if any(
        token in text
        for token in ("call me", "address", "称呼", "地址", "叫我")
    ):
        return "identity.preferred_address"
    if any(
        token in text
        for token in ("name", "called", "名字", "姓名", "叫做", "自称")
    ):
        return "identity.self_reported_name"
    if any(
        token in text
        for token in (
            "喜欢",
            "不喜欢",
            "讨厌",
            "偏好",
            "想要",
            "like",
            "dislike",
            "prefer",
            "want",
            "avoid",
            "喜好",
        )
    ):
        return "preference.entity"
    if any(
        token in text
        for token in (
            "拥有",
            "养",
            "我的",
            "物品",
            "宠物",
            "have",
            "has",
            "own",
            "possess",
            "pet",
            "持有",
        )
    ):
        return "possession.entity"
    if any(
        token in text
        for token in (
            "认识",
            "朋友",
            "同事",
            "家人",
            "亲戚",
            "关系",
            "related",
            "knows",
            "relate",
        )
    ):
        return "relationship.entity"
    if any(
        token in text
        for token in (
            "希望",
            "不要",
            "请记住",
            "规则",
            "始终",
            "instruction",
            "always",
            "behave",
            "行为",
        )
    ):
        return "instruction.behavior"
    if any(
        token in text
        for token in ("反馈", "效果", "feedback", "outcome", "结果")
    ):
        return "feedback.outcome"
    if any(
        token in text
        for token in ("状态", "当前", "暂时", "state", "status", "temporary")
    ):
        return "temporary.state"
    return None


def _normalize_predicate(value: str) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )
