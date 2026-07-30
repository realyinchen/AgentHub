from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.agent_capability_certification import (
    AgentCapabilityCertification,
)
from app.services.agent_certification import (
    get_agent_mode_admission,
    validate_agent_capability,
)
from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
    AgentCapabilityCertificationOutcome,
    AgentProbeCaseResult,
)
from app.services.agent_core.controller_fingerprint import (
    build_controller_fingerprint,
    current_controller_fingerprint,
)
from app.services.agent_core.evidence_source import GitSourceState
from app.services.model_probe.configuration import (
    ResolvedProbeTarget,
    _configuration_fingerprint,
)
from app.services.model_probe.contracts import ProbeConfig
from app.api.v1.models import _agent_release_source


def _target(*, fingerprint: str = "a" * 64) -> ResolvedProbeTarget:
    model_id = uuid.uuid4()
    return ResolvedProbeTarget(
        model_db_id=model_id,
        provider="openrouter",
        provider_model_id="test/chat-model",
        model_type="llm",
        configured_thinking=False,
        connection_id=uuid.uuid4(),
        configuration_fingerprint=fingerprint,
        config=ProbeConfig(
            provider="openrouter",
            provider_model_id="test/chat-model",
            api_key="secret",
            base_url="https://example.invalid/v1",
            is_openai_compatible=True,
            timeout_seconds=1,
            check_thinking=False,
        ),
    )


def _record(
    target: ResolvedProbeTarget,
    *,
    fingerprint: str | None = None,
    contract_version: str = AGENT_CERTIFICATION_CONTRACT_VERSION,
    controller_fingerprint: str | None = None,
    source_commit_sha: str | None = "e" * 40,
    certified: bool = True,
) -> AgentCapabilityCertification:
    return AgentCapabilityCertification(
        id=uuid.uuid4(),
        model_id=target.model_db_id,
        provider=target.provider,
        provider_model_id=target.provider_model_id,
        configuration_fingerprint=fingerprint or target.configuration_fingerprint,
        contract_version=contract_version,
        controller_fingerprint=(
            controller_fingerprint
            if controller_fingerprint is not None
            else current_controller_fingerprint()
        ),
        source_commit_sha=source_commit_sha,
        certified=certified,
        checked_at=datetime.now(timezone.utc),
        latency_ms=1,
        cases=[],
        failure_cases=[] if certified else ["strict_tool_schema"],
    )


class _Probe:
    async def run(self, config: ProbeConfig):
        return AgentCapabilityCertificationOutcome(
            certified=True,
            latency_ms=12,
            cases=[
                AgentProbeCaseResult(
                    name="basic_chat",
                    passed=True,
                    latency_ms=1,
                )
            ],
        )


class AgentCertificationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_api_missing_release_stops_before_git_probe(
        self,
    ) -> None:
        with (
            patch(
                "app.api.v1.models.get_settings",
                return_value=SimpleNamespace(
                    AGENT_RELEASE_COMMIT_SHA=None
                ),
            ),
            patch(
                "app.api.v1.models."
                "GitSourceStateReader.require_release_state",
            ) as source_reader,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "agent_release_commit_sha_missing_or_invalid",
            ):
                _agent_release_source()
        source_reader.assert_not_called()

    async def test_dirty_source_stops_before_target_resolution(
        self,
    ) -> None:
        resolver = AsyncMock()
        with patch(
            "app.services.agent_certification.resolve_probe_target",
            resolver,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "agent_certification_source_dirty",
            ):
                await validate_agent_capability(
                    object(),
                    uuid.uuid4(),
                    source_state=GitSourceState(
                        commit_sha="e" * 40,
                        dirty_worktree=True,
                    ),
                    probe=_Probe(),
                )
        resolver.assert_not_awaited()

    async def test_certification_persists_config_bound_result(self) -> None:
        target = _target()
        stored = _record(target)
        with (
            patch(
                "app.services.agent_certification.resolve_probe_target",
                AsyncMock(return_value=target),
            ),
            patch(
                "app.services.agent_certification."
                "certification_crud.create_certification",
                AsyncMock(return_value=stored),
            ) as create,
        ):
            result = await validate_agent_capability(
                object(),
                target.model_db_id,
                source_state=GitSourceState(
                    commit_sha="e" * 40,
                    dirty_worktree=False,
                ),
                probe=_Probe(),
            )

        self.assertIs(result, stored)
        payload = create.await_args.args[1]
        self.assertEqual(
            payload["configuration_fingerprint"],
            target.configuration_fingerprint,
        )
        self.assertEqual(
            payload["contract_version"],
            AGENT_CERTIFICATION_CONTRACT_VERSION,
        )
        self.assertEqual(
            payload["controller_fingerprint"],
            current_controller_fingerprint(),
        )
        self.assertEqual(payload["source_commit_sha"], "e" * 40)
        self.assertTrue(payload["certified"])
        self.assertEqual(payload["cases"][0]["name"], "basic_chat")

    async def test_admission_requires_exact_current_certification(self) -> None:
        target = _target()
        current = _record(target, certified=True)
        with (
            patch(
                "app.services.agent_certification.resolve_probe_target",
                AsyncMock(return_value=target),
            ),
            patch(
                "app.services.agent_certification."
                "certification_crud.get_latest_certification",
                AsyncMock(return_value=current),
            ) as latest,
        ):
            admission = await get_agent_mode_admission(
                object(),
                target.model_db_id,
                source_commit_sha="e" * 40,
            )

        self.assertTrue(admission.admitted)
        self.assertEqual(admission.certification_id, str(current.id))
        _, kwargs = latest.await_args
        self.assertEqual(
            kwargs["configuration_fingerprint"],
            target.configuration_fingerprint,
        )
        self.assertEqual(
            kwargs["contract_version"],
            AGENT_CERTIFICATION_CONTRACT_VERSION,
        )
        self.assertEqual(
            kwargs["controller_fingerprint"],
            current_controller_fingerprint(),
        )
        self.assertEqual(kwargs["source_commit_sha"], "e" * 40)
        self.assertEqual(
            admission.controller_fingerprint,
            current_controller_fingerprint(),
        )
        self.assertEqual(admission.source_commit_sha, "e" * 40)

    async def test_changed_configuration_fails_closed(self) -> None:
        target = _target(fingerprint="b" * 64)
        stale = _record(target, fingerprint="c" * 64)
        lookup = AsyncMock(side_effect=[None, stale])
        with (
            patch(
                "app.services.agent_certification.resolve_probe_target",
                AsyncMock(return_value=target),
            ),
            patch(
                "app.services.agent_certification."
                "certification_crud.get_latest_certification",
                lookup,
            ),
        ):
            admission = await get_agent_mode_admission(
                object(),
                target.model_db_id,
                source_commit_sha="e" * 40,
            )

        self.assertFalse(admission.admitted)
        self.assertEqual(admission.reason, "configuration_changed")

    async def test_legacy_certification_never_admits(self) -> None:
        target = _target()
        stale = _record(
            target,
            contract_version="agent-capability-v2",
            source_commit_sha=None,
        )
        lookup = AsyncMock(side_effect=[None, stale])
        with (
            patch(
                "app.services.agent_certification.resolve_probe_target",
                AsyncMock(return_value=target),
            ),
            patch(
                "app.services.agent_certification."
                "certification_crud.get_latest_certification",
                lookup,
            ),
        ):
            admission = await get_agent_mode_admission(
                object(),
                target.model_db_id,
                source_commit_sha="e" * 40,
            )

        self.assertFalse(admission.admitted)
        self.assertEqual(admission.reason, "contract_changed")

    def test_configuration_fingerprint_hides_and_tracks_credentials(self) -> None:
        common = {
            "provider": "openrouter",
            "provider_model_id": "test/chat-model",
            "model_type": "llm",
            "base_url": "https://example.invalid/v1",
            "is_openai_compatible": True,
            "connection_id": str(uuid.uuid4()),
            "extra_headers": {"X-Title": "test"},
        }
        first = _configuration_fingerprint(api_key="secret-one", **common)
        second = _configuration_fingerprint(api_key="secret-two", **common)

        self.assertEqual(len(first), 64)
        self.assertNotIn("secret-one", first)
        self.assertNotEqual(first, second)

    async def test_changed_controller_fingerprint_fails_closed(self) -> None:
        target = _target()
        stale = _record(
            target,
            controller_fingerprint="d" * 64,
        )
        lookup = AsyncMock(side_effect=[None, stale])
        with (
            patch(
                "app.services.agent_certification.resolve_probe_target",
                AsyncMock(return_value=target),
            ),
            patch(
                "app.services.agent_certification."
                "certification_crud.get_latest_certification",
                lookup,
            ),
        ):
            admission = await get_agent_mode_admission(
                object(),
                target.model_db_id,
                source_commit_sha="e" * 40,
            )

        self.assertFalse(admission.admitted)
        self.assertEqual(admission.reason, "controller_changed")
        self.assertEqual(
            admission.controller_fingerprint,
            current_controller_fingerprint(),
        )

    async def test_changed_release_fails_closed(self) -> None:
        target = _target()
        stale = _record(
            target,
            source_commit_sha="d" * 40,
        )
        lookup = AsyncMock(side_effect=[None, stale])
        with (
            patch(
                "app.services.agent_certification.resolve_probe_target",
                AsyncMock(return_value=target),
            ),
            patch(
                "app.services.agent_certification."
                "certification_crud.get_latest_certification",
                lookup,
            ),
        ):
            admission = await get_agent_mode_admission(
                object(),
                target.model_db_id,
                source_commit_sha="e" * 40,
            )

        self.assertFalse(admission.admitted)
        self.assertEqual(admission.reason, "release_changed")
        self.assertEqual(admission.source_commit_sha, "e" * 40)

    def test_controller_fingerprint_tracks_prompt_and_tool_schema(self) -> None:
        common = {
            "controller_schema": {"type": "object"},
            "task_schema": {"type": "object"},
            "contract_versions": {"agent_core": "v1"},
        }
        first = build_controller_fingerprint(
            core_prompt="prompt one",
            tool_schemas=[{"name": "one"}],
            **common,
        )
        prompt_changed = build_controller_fingerprint(
            core_prompt="prompt two",
            tool_schemas=[{"name": "one"}],
            **common,
        )
        tool_changed = build_controller_fingerprint(
            core_prompt="prompt one",
            tool_schemas=[{"name": "two"}],
            **common,
        )

        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, prompt_changed)
        self.assertNotEqual(first, tool_changed)


if __name__ == "__main__":
    unittest.main()
