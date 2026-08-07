from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.services.memory import (
    ForgetMemoryTargetProposal,
    MemoryAssertionProposal,
    MemoryCanonicalizer,
    MemoryVersionRecord,
    SearchMemoryRequest,
    VersionedMemorySchemaRegistry,
)
from app.services.memory.version_search import VersionedMemorySearch


def _assertion(
    *,
    predicate: str,
    value: dict,
    evidence: str,
    qualifiers: dict | None = None,
) -> MemoryAssertionProposal:
    return MemoryAssertionProposal(
        subject="self",
        predicate=predicate,
        value=value,
        qualifiers=qualifiers or {},
        evidence_quote=evidence,
    )


def _name_version(
    *,
    version_no: int,
    name: str,
    valid_from: datetime,
    previous_version_id=None,
    operation: str = "create",
) -> MemoryVersionRecord:
    return MemoryVersionRecord(
        id=uuid4(),
        user_id=uuid4(),
        chain_id=uuid4(),
        schema_key="identity.self_reported_name",
        memory_key="identity.self_reported_name:self",
        version_no=version_no,
        operation=operation,
        previous_version_id=previous_version_id,
        source_event_id=uuid4(),
        receipt_id=f"receipt-{version_no}",
        canonical_hash="0" * 64,
        schema_version=1,
        subject="self",
        predicate="name",
        value={"name": name},
        qualifiers={},
        evidence_quote=f"I am {name}",
        valid_from=valid_from,
    )


class MemoryCanonicalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canonicalizer = MemoryCanonicalizer()

    def test_registry_contains_only_controlled_v1_schemas(self) -> None:
        self.assertEqual(
            VersionedMemorySchemaRegistry().schema_keys,
            (
                "identity.self_reported_name",
                "identity.preferred_address",
                "identity.alias",
                "preference.entity",
                "relationship.entity",
                "possession.entity",
                "instruction.behavior",
                "feedback.outcome",
                "temporary.state",
            ),
        )

    def test_predicate_variants_classify_into_categories(self) -> None:
        registry = VersionedMemorySchemaRegistry()
        self.assertEqual(
            registry.resolve_predicate("养").schema_key,
            "possession.entity",
        )
        self.assertEqual(
            registry.resolve_predicate("我的物品").schema_key,
            "possession.entity",
        )
        self.assertEqual(
            registry.resolve_predicate("名字").schema_key,
            "identity.self_reported_name",
        )
        self.assertEqual(
            registry.resolve_predicate("想要").schema_key,
            "preference.entity",
        )

    def test_possession_entities_form_independent_chains(self) -> None:
        cat = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="has",
                    value={"entity": "猫"},
                    qualifiers={"entity_type": "pet"},
                    evidence="我有一只猫",
                )
            ],
            source_text="我有一只猫",
        )
        dog = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="养",
                    value={"entity": "狗"},
                    qualifiers={"entity_type": "pet"},
                    evidence="我还有一只狗",
                )
            ],
            source_text="我还有一只狗",
        )
        same_cat = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="have",
                    value={"entity": "猫"},
                    qualifiers={"entity_type": "pet"},
                    evidence="我养了一只猫",
                )
            ],
            source_text="我养了一只猫",
        )
        self.assertEqual(cat.status, "ready")
        self.assertEqual(dog.status, "ready")
        self.assertEqual(same_cat.status, "ready")
        self.assertEqual(cat.facts[0].schema_key, "possession.entity")
        self.assertNotEqual(cat.facts[0].memory_key, dog.facts[0].memory_key)
        self.assertEqual(
            cat.facts[0].memory_key,
            same_cat.facts[0].memory_key,
        )
        self.assertEqual(
            cat.facts[0].canonical_hash,
            same_cat.facts[0].canonical_hash,
        )

    def test_entity_type_is_optional_qualifier(self) -> None:
        result = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="likes",
                    value={"entity": "科幻小说", "polarity": "like"},
                    evidence="我喜欢科幻小说",
                )
            ],
            source_text="我喜欢科幻小说",
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.facts[0].schema_key, "preference.entity")

    def test_unknown_predicate_still_clarifies_when_unclassifiable(
        self,
    ) -> None:
        result = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="invented_schema",
                    value={"value": "x"},
                    evidence="记住 x",
                )
            ],
            source_text="记住 x",
        )
        self.assertEqual(result.status, "clarification_required")
        self.assertIn("unknown_memory_predicate", result.reason_codes)
        self.assertIn("invented_schema", result.clarification_question)

    def test_history_scopes_select_expected_versions(self) -> None:
        v1 = _name_version(
            version_no=1,
            name="小红",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        v2 = _name_version(
            version_no=2,
            name="小白",
            valid_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
            previous_version_id=v1.id,
            operation="correct",
        )
        v3 = _name_version(
            version_no=3,
            name="小红",
            valid_from=datetime(2026, 3, 1, tzinfo=timezone.utc),
            previous_version_id=v2.id,
            operation="correct",
        )
        v1.superseded_by = v2.id
        v2.superseded_by = v3.id
        records = [v1, v2, v3]

        previous = VersionedMemorySearch().search(
            records,
            SearchMemoryRequest(query="", predicate="name", scope="previous"),
        )
        self.assertEqual(
            [item.value["name"] for item in previous.memories],
            ["小白"],
        )
        earliest = VersionedMemorySearch().search(
            records,
            SearchMemoryRequest(query="", predicate="name", scope="earliest"),
        )
        self.assertEqual(
            [item.value["name"] for item in earliest.memories],
            ["小红"],
        )
        timeline = VersionedMemorySearch().search(
            records,
            SearchMemoryRequest(query="", predicate="name", scope="timeline"),
        )
        self.assertEqual(len(timeline.memories), 3)
        self.assertEqual(timeline.scope, "timeline")

    def test_model_assertion_rejects_storage_identity(self) -> None:
        with self.assertRaises(ValidationError):
            MemoryAssertionProposal.model_validate(
                {
                    "subject": "self",
                    "predicate": "name",
                    "value": {"name": "冰露"},
                    "qualifiers": {},
                    "evidence_quote": "I am 冰露",
                    "memory_key": "model-must-not-choose",
                }
            )

    def test_name_corrections_share_key_but_change_hash(self) -> None:
        first = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="name",
                    value={"name": "冰露"},
                    evidence="I am 冰露",
                )
            ],
            source_text="I am 冰露",
        )
        second = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="self_reported_name",
                    value={"name": "小露"},
                    evidence="I am 小露",
                )
            ],
            source_text="I am 小露",
        )
        self.assertEqual(first.status, "ready")
        self.assertEqual(second.status, "ready")
        self.assertEqual(first.facts[0].memory_key, second.facts[0].memory_key)
        self.assertNotEqual(
            first.facts[0].canonical_hash,
            second.facts[0].canonical_hash,
        )

    def test_preference_polarity_changes_one_entity_chain(self) -> None:
        like = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="likes",
                    value={"entity": "科幻", "polarity": "like"},
                    qualifiers={"entity_type": "book_genre"},
                    evidence="我喜欢科幻",
                )
            ],
            source_text="我喜欢科幻",
        )
        avoid = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="dislikes",
                    value={"entity": "科幻", "polarity": "avoid"},
                    qualifiers={"entity_type": "book_genre"},
                    evidence="我现在想避开科幻",
                )
            ],
            source_text="我现在想避开科幻",
        )
        self.assertEqual(like.facts[0].memory_key, avoid.facts[0].memory_key)
        self.assertNotEqual(
            like.facts[0].canonical_hash,
            avoid.facts[0].canonical_hash,
        )

    def test_unknown_predicate_requires_clarification(self) -> None:
        result = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="invented_schema",
                    value={"value": "x"},
                    evidence="记住 x",
                )
            ],
            source_text="记住 x",
        )
        self.assertEqual(result.status, "clarification_required")

    def test_evidence_must_match_user_source(self) -> None:
        result = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="name",
                    value={"name": "冰露"},
                    evidence="I am 冰露",
                )
            ],
            source_text="I am 小露",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn(
            "evidence_not_found_in_user_source",
            result.reason_codes,
        )

    def test_credentials_are_never_canonicalized(self) -> None:
        result = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="instruction",
                    value={
                        "instruction": "use this",
                        "credentials": {"api_key": "sk-secret-123456789"},
                    },
                    evidence="记住 api_key=sk-secret-123456789",
                )
            ],
            source_text="记住 api_key=sk-secret-123456789",
        )
        self.assertEqual(result.status, "rejected")
        self.assertIn("secret_or_credential_forbidden", result.reason_codes)

    def test_conflicting_batch_is_all_or_nothing(self) -> None:
        result = self.canonicalizer.canonicalize(
            [
                _assertion(
                    predicate="name",
                    value={"name": "冰露"},
                    evidence="我是冰露",
                ),
                _assertion(
                    predicate="name",
                    value={"name": "小露"},
                    evidence="也是小露",
                ),
            ],
            source_text="我是冰露，也是小露",
        )
        self.assertEqual(result.status, "clarification_required")
        self.assertEqual(result.facts, [])

    def test_singleton_forget_target_never_needs_model_memory_key(self) -> None:
        result = self.canonicalizer.resolve_targets(
            [
                ForgetMemoryTargetProposal(
                    subject="self",
                    predicate="name",
                    evidence_quote="忘记我的名字",
                )
            ],
            source_text="忘记我的名字",
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.targets[0].memory_key,
            "identity.self_reported_name:self",
        )

    def test_multi_forget_target_requires_identity(self) -> None:
        result = self.canonicalizer.resolve_targets(
            [
                ForgetMemoryTargetProposal(
                    subject="self",
                    predicate="preference",
                    evidence_quote="忘记这个偏好",
                )
            ],
            source_text="忘记这个偏好",
        )
        self.assertEqual(result.status, "clarification_required")


if __name__ == "__main__":
    unittest.main()
