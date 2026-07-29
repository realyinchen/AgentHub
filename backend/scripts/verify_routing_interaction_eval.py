"""Validate and execute the adversarial InteractionDecision routing corpus.

The fixture is the durable contract.  The runtime adapter deliberately enters
through ``RoutingFunnel.decide`` so the same checks cover a first-class
``interaction_decision`` and the transitional ``RoutingDecision`` envelope.

Examples:

    python scripts/verify_routing_interaction_eval.py --contract-only
    python scripts/verify_routing_interaction_eval.py --report-only
    python scripts/verify_routing_interaction_eval.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_FIXTURE = (
    BACKEND_DIR
    / "tests"
    / "fixtures"
    / "routing_interaction_eval_v1.jsonl"
)

ALLOWED_STATUSES = {
    "accepted",
    "clarification_required",
    "safe_default",
}
ALLOWED_PLANNING = {
    "direct_answer",
    "static_workflow",
    "decomposition_required",
    "clarification_required",
}
ALLOWED_PERSISTENCE = {
    "forbidden",
    "not_proposed",
    "proposed",
}
REQUIREMENT_FIELDS = {
    "direct_answer_allowed",
    "memory_read_required",
    "memory_write_required",
    "weather_required",
    "external_search_required",
    "decomposition_required",
}
REQUIRED_CATEGORIES = {
    "prohibition": 8,
    "metalinguistic": 6,
    "weather_word_book": 6,
    "entity_vs_personal": 5,
    "compound": 8,
    "context_followup": 6,
    "unknown_ood": 6,
    "decision_axes": 10,
}
SYSTEM_FIELDS = {
    "user_id",
    "thread_id",
    "conversation_id",
    "request_id",
    "tenant_id",
    "workspace_id",
    "permissions",
    "credential",
    "credentials",
    "authorization",
    "api_key",
    "access_token",
    "refresh_token",
}
CAPABILITY_OPERATIONS = {
    "long_term_memory_read": {"search_memory"},
    "external_information": {
        "web_search",
        "start_research",
        "acquire_research_sources",
    },
    "current_information": {"web_search"},
    "memory_persistence": {"process_memory_write_request"},
    "business_state_change": {"record_book_feedback"},
    "book_catalog_search": {"search_books"},
    "decomposition": {"start_research"},
}
LEGACY_GOAL_ALIASES = {
    "explain": {"answer_question"},
    "summarize": {"answer_question"},
    "analyze_utterance": {"answer_question"},
    "translate": {"answer_question"},
    "classify_utterance": {"answer_question"},
    "generate_example": {"answer_question"},
    "compare": {"answer_question"},
    "acknowledge_constraint": {"answer_question"},
    "social_response": {"answer_question"},
    "retrieve_current_information": {"weather_lookup", "external_lookup"},
    "record_personal_context": {"memory_update"},
    "answer_personal_fact": {"memory_lookup"},
    "research": {"deep_research"},
    "record_reading_feedback": {"reading_feedback"},
    "find_books": {"recommend_books"},
}
INTERACTION_GOAL_ALIASES = {
    # The gold corpus keeps useful subtypes while the v1 production contract
    # intentionally exposes a smaller, tool-independent goal vocabulary.
    "explain": {"answer_question"},
    "summarize": {"answer_question"},
    "analyze_utterance": {"answer_question"},
    "translate": {"answer_question"},
    "classify_utterance": {"answer_question"},
    "generate_example": {"answer_question"},
    "compare": {"answer_question"},
    "acknowledge_constraint": {"express_constraint"},
    "retrieve_current_information": {"answer_current_question"},
    "record_personal_context": {"share_personal_information"},
    "answer_personal_fact": {"retrieve_personal_context"},
    "answer_question": {"answer_factual_question"},
    "research": {"research_topic"},
    "find_books": {"recommend_books"},
    "social_response": {"answer_question"},
    "resolve_constraint_conflict": {"express_constraint"},
    "refine_previous_goal": {"recommend_books"},
    "clarify_referent": {"answer_question"},
    "clarify_objective": {"answer_question"},
    "unknown": {"answer_question"},
}


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    text: str
    context: dict[str, Any]
    expected: dict[str, Any]


@dataclass
class NormalizedDecision:
    has_interaction_decision: bool
    status: str
    goals: list[str]
    planning: str
    requirements: dict[str, bool]
    memory_persistence: str
    business_state_change_required: bool
    operations: list[str]
    prohibited_operations: set[str]
    raw: dict[str, Any] = field(repr=False)


@dataclass
class CaseResult:
    case: EvalCase
    skipped: bool = False
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.skipped and not self.failures


def _assert_fixture(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_fixture(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        _validate_fixture_record(payload, line_number=line_number, path=path)
        input_payload = payload["input"]
        cases.append(
            EvalCase(
                case_id=payload["id"],
                category=payload["category"],
                text=input_payload["text"],
                context=dict(input_payload.get("context") or {}),
                expected=dict(payload["expected"]),
            )
        )

    _assert_fixture(len(cases) >= 40, "routing corpus must contain at least 40 cases")
    ids = [case.case_id for case in cases]
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    _assert_fixture(not duplicates, f"duplicate case ids: {duplicates}")

    category_counts = Counter(case.category for case in cases)
    for category, minimum in REQUIRED_CATEGORIES.items():
        _assert_fixture(
            category_counts[category] >= minimum,
            f"category {category!r} needs >= {minimum} cases; "
            f"found {category_counts[category]}",
        )

    statuses = Counter(case.expected["status"] for case in cases)
    _assert_fixture(
        set(statuses) == ALLOWED_STATUSES,
        f"corpus must exercise every status; found {sorted(statuses)}",
    )
    _assert_fixture(
        statuses["accepted"] < len(cases),
        "corpus cannot contain only positive accepted cases",
    )
    _assert_fixture(
        any(case.expected["must_not_operations"] for case in cases),
        "corpus must exercise explicit must_not_operations",
    )
    return cases


def _validate_fixture_record(
    payload: Any,
    *,
    line_number: int,
    path: Path,
) -> None:
    where = f"{path}:{line_number}"
    _assert_fixture(isinstance(payload, dict), f"{where}: record must be an object")
    _assert_fixture(
        set(payload) == {"id", "category", "input", "expected"},
        f"{where}: unexpected top-level fields: {sorted(set(payload) - {'id', 'category', 'input', 'expected'})}",
    )
    _assert_fixture(
        isinstance(payload["id"], str) and payload["id"].strip(),
        f"{where}: id must be non-empty",
    )
    _assert_fixture(
        isinstance(payload["category"], str) and payload["category"].strip(),
        f"{where}: category must be non-empty",
    )
    input_payload = payload["input"]
    _assert_fixture(isinstance(input_payload, dict), f"{where}: input must be an object")
    _assert_fixture(
        isinstance(input_payload.get("text"), str)
        and input_payload["text"].strip(),
        f"{where}: input.text must be non-empty",
    )
    _assert_fixture(
        not _find_system_fields(input_payload),
        f"{where}: input contains system-owned fields",
    )

    expected = payload["expected"]
    _assert_fixture(isinstance(expected, dict), f"{where}: expected must be an object")
    _assert_fixture(
        expected.get("status") in ALLOWED_STATUSES,
        f"{where}: invalid status {expected.get('status')!r}",
    )
    _assert_fixture(
        isinstance(expected.get("goal"), str) and expected["goal"].strip(),
        f"{where}: expected.goal must be non-empty",
    )
    _assert_fixture(
        expected.get("planning") in ALLOWED_PLANNING,
        f"{where}: invalid planning mode {expected.get('planning')!r}",
    )
    _assert_fixture(
        expected.get("memory_persistence") in ALLOWED_PERSISTENCE,
        f"{where}: invalid memory_persistence",
    )
    _assert_fixture(
        isinstance(expected.get("business_state_change_required"), bool),
        f"{where}: business_state_change_required must be boolean",
    )
    requirements = expected.get("requirements")
    _assert_fixture(
        isinstance(requirements, dict),
        f"{where}: requirements must be an object",
    )
    unknown_requirements = set(requirements) - REQUIREMENT_FIELDS
    _assert_fixture(
        not unknown_requirements,
        f"{where}: unknown requirement fields: {sorted(unknown_requirements)}",
    )
    _assert_fixture(
        all(isinstance(value, bool) for value in requirements.values()),
        f"{where}: requirement values must be boolean",
    )
    for field_name in (
        "required_operations",
        "must_not_operations",
        "forbidden_operations",
    ):
        operations = expected.get(field_name)
        _assert_fixture(
            isinstance(operations, list)
            and all(isinstance(item, str) and item for item in operations),
            f"{where}: {field_name} must be a string list",
        )
        _assert_fixture(
            len(operations) == len(set(operations)),
            f"{where}: {field_name} contains duplicates",
        )
    required = set(expected["required_operations"])
    forbidden = set(expected["forbidden_operations"])
    must_not = set(expected["must_not_operations"])
    _assert_fixture(
        not required.intersection(forbidden | must_not),
        f"{where}: required operations conflict with forbidden operations",
    )
    if expected["status"] != "accepted":
        _assert_fixture(
            not required,
            f"{where}: non-accepted cases cannot require execution",
        )


async def evaluate_runtime(cases: list[EvalCase]) -> list[CaseResult]:
    from app.services.routing.contracts import RoutingQuery
    from app.services.routing.funnel import RoutingFunnel
    from app.services.routing.semantic import InMemorySemanticRecall

    class NoLiveVectorSemantic(InMemorySemanticRecall):
        async def _vector_candidates(self, text: str):
            del text
            return []

    funnel = RoutingFunnel(semantic_provider=NoLiveVectorSemantic())
    results: list[CaseResult] = []
    for case in cases:
        query_payload: dict[str, Any] = {"text": case.text}
        if case.context:
            context_field = next(
                (
                    field_name
                    for field_name in (
                        "context",
                        "business_context",
                        "routing_context",
                    )
                    if field_name in RoutingQuery.model_fields
                ),
                None,
            )
            if context_field is None:
                results.append(
                    CaseResult(
                        case=case,
                        skipped=True,
                        failures=[
                            "RoutingQuery has no identity-free business context field"
                        ],
                    )
                )
                continue
            query_payload[context_field] = _adapt_context(case.context)

        try:
            raw_decision = await funnel.decide(RoutingQuery(**query_payload))
            normalized = _normalize_decision(raw_decision)
            failures = _compare(case, normalized)
        except Exception as exc:  # verifier must attribute each bad case
            failures = [f"runtime raised {type(exc).__name__}: {exc}"]
        results.append(CaseResult(case=case, failures=failures))
    return results


def _adapt_context(context: dict[str, Any]) -> dict[str, Any]:
    """Map fixture vocabulary to the identity-free business context contract."""

    recent = []
    previous_text = str(context.get("previous_user_text") or "").strip()
    if previous_text:
        recent.append(previous_text)
    subject = context.get("active_subject")
    if subject is None:
        referents = context.get("referents") or []
        if referents:
            subject = str(referents[0])
        elif context.get("location"):
            subject = str(context["location"])
    return {
        "recent_user_messages": recent,
        "previous_primary_intent": context.get("previous_goal"),
        "active_subject": subject,
        "previous_constraints": [],
    }


def _model_dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return dumper(mode="json")
    raise TypeError(f"decision is not serializable: {type(value).__name__}")


def _normalize_decision(value: Any) -> NormalizedDecision:
    outer = _model_dump(value)
    interaction = outer.get("interaction_decision")
    if interaction is None:
        metadata = outer.get("metadata") or {}
        interaction = metadata.get("interaction_decision")
    inner = _model_dump(interaction) if interaction is not None else {}
    has_interaction = bool(inner)

    actions = list(outer.get("proposed_actions") or [])
    operations = [
        str(action.get("operation") or "")
        for action in actions
        if str(action.get("operation") or "")
    ]
    invalid_action_fields = _find_system_fields(actions)
    if invalid_action_fields:
        raise AssertionError(
            "routing proposed system-owned action fields: "
            + ", ".join(sorted(invalid_action_fields))
        )

    clause_payloads = list(inner.get("clauses") or [])
    goals = [
        str((clause.get("goal") or {}).get("kind") or "")
        for clause in clause_payloads
    ]
    goals = [goal for goal in goals if goal]
    if not goals:
        primary = str(
            outer.get("primary_goal")
            or outer.get("primary_intent")
            or "answer_question"
        )
        goals = [primary]

    requirements = _requirements_from_outer(outer)
    prohibited_capabilities = set(inner.get("prohibited_capabilities") or [])
    for clause in clause_payloads:
        prohibited_capabilities.update(clause.get("prohibited_capabilities") or [])
    prohibited_operations = {
        operation
        for capability in prohibited_capabilities
        for operation in CAPABILITY_OPERATIONS.get(str(capability), set())
    }

    if has_interaction:
        requirements.update(
            _requirements_from_interaction(inner, clause_payloads, outer)
        )
        planning = str((inner.get("planning") or {}).get("mode") or "")
        status = str(inner.get("status") or "accepted")
        persistence = _persistence_from_clauses(clause_payloads)
        state_change = any(
            str((clause.get("business_state") or {}).get("disposition"))
            in {"proposed", "explicitly_requested"}
            for clause in clause_payloads
        )
    else:
        status = str(outer.get("status") or "accepted")
        planning = _legacy_planning(outer, requirements, operations, status)
        persistence = (
            (
                "proposed"
                if "process_memory_write_request" in operations
                else "not_proposed"
            )
        )
        state_change = "record_book_feedback" in operations

    return NormalizedDecision(
        has_interaction_decision=has_interaction,
        status=status,
        goals=goals,
        planning=planning,
        requirements=requirements,
        memory_persistence=persistence,
        business_state_change_required=state_change,
        operations=operations,
        prohibited_operations=prohibited_operations,
        raw=outer,
    )


def _requirements_from_outer(outer: dict[str, Any]) -> dict[str, bool]:
    payload = outer.get("requirements") or {}
    return {
        field_name: bool(payload.get(field_name, False))
        for field_name in REQUIREMENT_FIELDS
    }


def _requirements_from_interaction(
    inner: dict[str, Any],
    clauses: list[dict[str, Any]],
    outer: dict[str, Any],
) -> dict[str, bool]:
    long_term_levels = {
        str((clause.get("existing_information") or {}).get("long_term_memory"))
        for clause in clauses
    }
    current_levels = {
        str((clause.get("external_information") or {}).get("current_information"))
        for clause in clauses
    }
    external_levels = {
        str((clause.get("external_information") or {}).get("external_information"))
        for clause in clauses
    }
    persistence = {
        str((clause.get("memory_persistence") or {}).get("disposition"))
        for clause in clauses
    }
    domains = {
        str((clause.get("goal") or {}).get("domain") or "")
        for clause in clauses
    }
    planning = str((inner.get("planning") or {}).get("mode") or "")
    legacy = _requirements_from_outer(outer)
    return {
        "direct_answer_allowed": bool(inner.get("direct_answer_allowed", False)),
        "memory_read_required": "required" in long_term_levels,
        "memory_write_required": bool(
            persistence.intersection({"candidate", "explicitly_requested"})
        ),
        "weather_required": (
            legacy["weather_required"]
            or (
                "weather" in domains
                and bool(current_levels.intersection({"required"}))
            )
        ),
        "external_search_required": bool(
            current_levels.intersection({"required"})
            or external_levels.intersection({"required"})
        ),
        "decomposition_required": planning == "decomposition_required",
    }


def _persistence_from_clauses(clauses: list[dict[str, Any]]) -> str:
    dispositions = {
        str((clause.get("memory_persistence") or {}).get("disposition"))
        for clause in clauses
    }
    if "forbidden" in dispositions:
        return "forbidden"
    if dispositions.intersection({"candidate", "explicitly_requested"}):
        return "proposed"
    return "not_proposed"


def _legacy_planning(
    outer: dict[str, Any],
    requirements: dict[str, bool],
    operations: list[str],
    status: str,
) -> str:
    if status == "clarification_required":
        return "clarification_required"
    if bool(outer.get("planner_required")) or requirements["decomposition_required"]:
        return "decomposition_required"
    if operations:
        return "static_workflow"
    return "direct_answer"


def _compare(case: EvalCase, actual: NormalizedDecision) -> list[str]:
    expected = case.expected
    failures: list[str] = []
    if actual.status != expected["status"]:
        failures.append(
            f"status expected={expected['status']} actual={actual.status}"
        )

    expected_goal = expected["goal"]
    if actual.has_interaction_decision:
        goal_matches = (
            expected_goal == "compound" and len(actual.goals) >= 2
        ) or expected_goal in actual.goals or bool(
            set(actual.goals).intersection(
                INTERACTION_GOAL_ALIASES.get(expected_goal, set())
            )
        )
    else:
        goal_matches = expected_goal in actual.goals or bool(
            set(actual.goals).intersection(
                LEGACY_GOAL_ALIASES.get(expected_goal, set())
            )
        )
    if not goal_matches:
        failures.append(
            f"goal expected={expected_goal} actual={actual.goals}"
        )

    if actual.planning != expected["planning"]:
        failures.append(
            f"planning expected={expected['planning']} actual={actual.planning}"
        )

    for field_name, expected_value in expected["requirements"].items():
        actual_value = actual.requirements.get(field_name)
        if actual_value is not expected_value:
            failures.append(
                f"requirements.{field_name} "
                f"expected={expected_value} actual={actual_value}"
            )

    if actual.memory_persistence != expected["memory_persistence"]:
        failures.append(
            "memory_persistence "
            f"expected={expected['memory_persistence']} "
            f"actual={actual.memory_persistence}"
        )
    if (
        actual.business_state_change_required
        is not expected["business_state_change_required"]
    ):
        failures.append(
            "business_state_change_required "
            f"expected={expected['business_state_change_required']} "
            f"actual={actual.business_state_change_required}"
        )

    actual_operations = set(actual.operations)
    required_operations = set(expected["required_operations"])
    missing = sorted(required_operations - actual_operations)
    if missing:
        failures.append(f"missing required operations={missing}")
    forbidden = sorted(
        actual_operations.intersection(expected["forbidden_operations"])
    )
    if forbidden:
        failures.append(f"present forbidden operations={forbidden}")
    must_not_present = sorted(
        actual_operations.intersection(expected["must_not_operations"])
    )
    if must_not_present:
        failures.append(f"present must_not operations={must_not_present}")
    if actual.has_interaction_decision:
        undeclared_prohibitions = sorted(
            set(expected["must_not_operations"]) - actual.prohibited_operations
        )
        if undeclared_prohibitions:
            failures.append(
                "must_not operations lack prohibited capability="
                f"{undeclared_prohibitions}"
            )
    return failures


def _find_system_fields(value: Any, *, prefix: str = "value") -> set[str]:
    invalid: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}"
            if str(key).lower() in SYSTEM_FIELDS:
                invalid.add(path)
            invalid.update(_find_system_fields(nested, prefix=path))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            invalid.update(
                _find_system_fields(nested, prefix=f"{prefix}[{index}]")
            )
    return invalid


def _print_contract_summary(cases: list[EvalCase]) -> None:
    categories = Counter(case.category for case in cases)
    statuses = Counter(case.expected["status"] for case in cases)
    must_not_count = sum(
        bool(case.expected["must_not_operations"]) for case in cases
    )
    print(
        "routing interaction corpus valid: "
        f"{len(cases)} cases, "
        f"statuses={dict(sorted(statuses.items()))}, "
        f"must_not_cases={must_not_count}"
    )
    print("category coverage:")
    for category, count in sorted(categories.items()):
        print(f"  {category}: {count}")


def _print_runtime_summary(results: list[CaseResult]) -> None:
    passed = sum(result.passed for result in results)
    failed = sum(bool(result.failures) and not result.skipped for result in results)
    skipped = sum(result.skipped for result in results)
    print(
        f"routing interaction runtime: passed={passed}, "
        f"failed={failed}, skipped={skipped}, total={len(results)}"
    )
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        outcome = (
            "skipped"
            if result.skipped
            else ("passed" if result.passed else "failed")
        )
        by_category[result.case.category][outcome] += 1
    for category, outcomes in sorted(by_category.items()):
        print(f"  {category}: {dict(sorted(outcomes.items()))}")
    for result in results:
        if result.passed:
            continue
        label = "SKIP" if result.skipped else "FAIL"
        print(f"[{label}] {result.case.case_id}")
        for failure in result.failures:
            print(f"  - {failure}")


async def _run(args: argparse.Namespace) -> int:
    fixture = Path(args.fixture).resolve()
    cases = load_fixture(fixture)
    _print_contract_summary(cases)
    if args.contract_only:
        return 0
    results = await evaluate_runtime(cases)
    _print_runtime_summary(results)
    has_failure = any(result.failures and not result.skipped for result in results)
    has_skip = any(result.skipped for result in results)
    if args.report_only:
        return 0
    return 1 if has_failure or has_skip else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify InteractionDecision adversarial routing corpus."
    )
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE),
        help="JSONL evaluation fixture path",
    )
    parser.add_argument(
        "--contract-only",
        action="store_true",
        help="validate fixture shape and coverage without importing production code",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="run the implementation and print failures without returning non-zero",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parse_args())))
