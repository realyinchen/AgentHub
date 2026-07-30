from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.schemas.chat import UserInput
from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
    ShadowObservationDispatcher,
    dispose_shadow_observation_dispatcher,
    init_shadow_observation_dispatcher,
)
from app.services.agent_core.release_identity import (
    AgentReleaseIdentityError,
)
from app.services.agent_core.controller_fingerprint import (
    current_controller_fingerprint,
)


def _command(request_id: str) -> ShadowControllerCommand:
    return ShadowControllerCommand(
        user_input=UserInput(
            content="What did I just say?",
            user_id=uuid4(),
            thread_id=uuid4(),
            request_id=request_id,
            model_uuid=str(uuid4()),
        ),
        model_name="fixture-controller",
        journal_sequence_watermark=1,
        controller_fingerprint=current_controller_fingerprint(),
        source_commit_sha="c" * 40,
    )


class _BlockingHandler:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.handled: list[str] = []

    async def handle(self, command: ShadowControllerCommand) -> None:
        self.handled.append(command.user_input.request_id)
        self.started.set()
        await self.release.wait()


class _OneShotRecovery:
    def __init__(self, command: ShadowControllerCommand) -> None:
        self.command = command
        self.calls = 0

    async def pending(self, *, limit: int):
        self.calls += 1
        return [self.command] if self.calls == 1 else []


class _RecordingHandler:
    def __init__(self) -> None:
        self.handled = asyncio.Event()
        self.request_ids: list[str] = []

    async def handle(self, command: ShadowControllerCommand) -> None:
        self.request_ids.append(command.user_input.request_id)
        self.handled.set()


class ShadowObservationDispatcherTests(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncTearDown(self) -> None:
        await dispose_shadow_observation_dispatcher()

    async def test_release_commit_is_required_only_for_agent_modes(
        self,
    ) -> None:
        with patch(
            "app.infra.config.get_settings",
            return_value=SimpleNamespace(
                AGENT_CONTROLLER_V1_MODE="off",
                AGENT_RELEASE_COMMIT_SHA=None,
            ),
        ):
            await init_shadow_observation_dispatcher()
        await dispose_shadow_observation_dispatcher()

        for mode in ("shadow", "live"):
            with self.subTest(mode=mode):
                with patch(
                    "app.infra.config.get_settings",
                    return_value=SimpleNamespace(
                        AGENT_CONTROLLER_V1_MODE=mode,
                        AGENT_RELEASE_COMMIT_SHA=None,
                    ),
                ):
                    with self.assertRaises(
                        AgentReleaseIdentityError
                    ):
                        await init_shadow_observation_dispatcher()

    async def test_submit_is_non_blocking_and_queue_full_drops(self) -> None:
        handler = _BlockingHandler()
        dispatcher = ShadowObservationDispatcher(
            handler=handler,
            queue_capacity=1,
            worker_count=1,
        )
        await dispatcher.start()
        first = dispatcher.submit(_command("shadow-1"))
        await asyncio.wait_for(handler.started.wait(), timeout=1)
        second = dispatcher.submit(_command("shadow-2"))
        third = dispatcher.submit(_command("shadow-3"))

        self.assertEqual(first.status, "queued")
        self.assertEqual(second.status, "queued")
        self.assertEqual(third.status, "dropped")
        self.assertEqual(third.reason, "queue_full")
        self.assertEqual(dispatcher.metrics.queued, 2)
        self.assertEqual(dispatcher.metrics.dropped, 1)

        handler.release.set()
        await dispatcher.stop(drain_timeout_seconds=1)
        self.assertEqual(
            handler.handled,
            ["shadow-1", "shadow-2"],
        )

    async def test_not_started_and_stopped_dispatcher_fail_open(self) -> None:
        dispatcher = ShadowObservationDispatcher(
            handler=_BlockingHandler(),
            queue_capacity=1,
            worker_count=1,
        )
        before = dispatcher.submit(_command("before-start"))
        self.assertEqual(before.status, "dropped")
        self.assertEqual(before.reason, "not_started")

        await dispatcher.start()
        await dispatcher.stop(drain_timeout_seconds=0.01)
        after = dispatcher.submit(_command("after-stop"))
        self.assertEqual(after.status, "dropped")
        self.assertEqual(after.reason, "stopping")

    async def test_durable_recovery_source_refills_the_queue(self) -> None:
        command = _command("recovered-shadow")
        handler = _RecordingHandler()
        source = _OneShotRecovery(command)
        dispatcher = ShadowObservationDispatcher(
            handler=handler,
            recovery_source=source,
            queue_capacity=2,
            worker_count=1,
            recovery_interval_seconds=0.01,
        )

        await dispatcher.start()
        await asyncio.wait_for(handler.handled.wait(), timeout=1)
        await dispatcher.stop(drain_timeout_seconds=1)

        self.assertEqual(
            handler.request_ids,
            ["recovered-shadow"],
        )
        self.assertGreaterEqual(source.calls, 1)


if __name__ == "__main__":
    unittest.main()
