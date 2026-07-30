from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.services.memory import (
    ForgetMemoryTargetProposal,
    MemoryAssertionProposal,
    MemoryCanonicalizer,
    VersionedMemorySchemaRegistry,
)


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
                "instruction.behavior",
                "feedback.outcome",
                "temporary.state",
            ),
        )

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
