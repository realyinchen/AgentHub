from __future__ import annotations

import asyncio
import logging
from typing import Literal, Protocol

from pydantic import Field

from app.schemas.chat import UserInput
from app.services.agent_core.contracts import AgentCoreModel


logger = logging.getLogger(__name__)


class ShadowControllerCommand(AgentCoreModel):
    """Internal command. System identity is never projected to the model."""

    user_input: UserInput
    model_name: str = Field(min_length=1, max_length=256)
    journal_sequence_watermark: int = Field(ge=1)
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")


class ShadowDispatchReceipt(AgentCoreModel):
    status: Literal["queued", "dropped"]
    reason: Literal["queue_full", "not_started", "stopping"] | None = None


class ShadowDispatcherMetrics(AgentCoreModel):
    queued: int = Field(default=0, ge=0)
    dropped: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class ShadowCommandHandler(Protocol):
    async def handle(self, command: ShadowControllerCommand) -> None:
        """Evaluate and persist one isolated Shadow command."""


class ShadowRecoverySource(Protocol):
    async def pending(
        self,
        *,
        limit: int,
    ) -> list[ShadowControllerCommand]:
        """Return durable enrollments that still lack an observation."""


class ShadowObservationDispatcher:
    """Bounded, lifecycle-owned queue outside the user response path."""

    def __init__(
        self,
        *,
        handler: ShadowCommandHandler | None = None,
        recovery_source: ShadowRecoverySource | None = None,
        expected_source_commit_sha: str | None = None,
        queue_capacity: int = 1_000,
        worker_count: int = 1,
        recovery_interval_seconds: float = 5.0,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("queue_capacity must be positive")
        if worker_count < 1:
            raise ValueError("worker_count must be positive")
        if recovery_interval_seconds <= 0:
            raise ValueError(
                "recovery_interval_seconds must be positive"
            )
        self._handler = handler
        self._recovery_source = recovery_source
        self._expected_source_commit_sha = expected_source_commit_sha
        self._queue: asyncio.Queue[ShadowControllerCommand | None] = (
            asyncio.Queue(maxsize=queue_capacity)
        )
        self._worker_count = worker_count
        self._workers: list[asyncio.Task[None]] = []
        self._recovery_task: asyncio.Task[None] | None = None
        self._recovery_stop = asyncio.Event()
        self._recovery_interval_seconds = recovery_interval_seconds
        self._pending_keys: set[str] = set()
        self._state: Literal["new", "running", "stopping", "stopped"] = "new"
        self._queued = 0
        self._dropped = 0
        self._completed = 0
        self._failed = 0

    @property
    def metrics(self) -> ShadowDispatcherMetrics:
        return ShadowDispatcherMetrics(
            queued=self._queued,
            dropped=self._dropped,
            completed=self._completed,
            failed=self._failed,
        )

    async def start(self) -> None:
        if self._state == "running":
            return
        if self._state in {"stopping", "stopped"}:
            raise RuntimeError("stopped Shadow dispatcher cannot be restarted")
        if self._handler is None:
            from app.services.agent_core.shadow_observation import (
                ShadowObservationWorker,
            )

            if self._expected_source_commit_sha is None:
                raise RuntimeError(
                    "default Shadow worker requires a source commit"
                )
            self._handler = ShadowObservationWorker(
                expected_source_commit_sha=(
                    self._expected_source_commit_sha
                )
            )
        self._state = "running"
        self._workers = [
            asyncio.create_task(
                self._worker_loop(),
                name=f"agent-shadow-observer-{index + 1}",
            )
            for index in range(self._worker_count)
        ]
        if self._recovery_source is not None:
            self._recovery_task = asyncio.create_task(
                self._recovery_loop(),
                name="agent-shadow-enrollment-recovery",
            )

    def submit(
        self,
        command: ShadowControllerCommand,
    ) -> ShadowDispatchReceipt:
        if self._state == "new":
            self._dropped += 1
            return ShadowDispatchReceipt(
                status="dropped",
                reason="not_started",
            )
        if self._state != "running":
            self._dropped += 1
            return ShadowDispatchReceipt(
                status="dropped",
                reason="stopping",
            )
        key = self._command_key(command)
        if key in self._pending_keys:
            return ShadowDispatchReceipt(status="queued")
        try:
            self._queue.put_nowait(command)
        except asyncio.QueueFull:
            self._dropped += 1
            return ShadowDispatchReceipt(
                status="dropped",
                reason="queue_full",
            )
        self._pending_keys.add(key)
        self._queued += 1
        return ShadowDispatchReceipt(status="queued")

    async def stop(self, *, drain_timeout_seconds: float = 5) -> None:
        if self._state in {"stopping", "stopped"}:
            return
        if self._state == "new":
            self._state = "stopped"
            return
        self._state = "stopping"
        self._recovery_stop.set()
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            await asyncio.gather(
                self._recovery_task,
                return_exceptions=True,
            )
            self._recovery_task = None
        drained = False
        try:
            await asyncio.wait_for(
                self._queue.join(),
                timeout=max(0.001, drain_timeout_seconds),
            )
            drained = True
        except TimeoutError:
            logger.warning(
                "Shadow dispatcher drain timed out with %d queued commands",
                self._queue.qsize(),
            )
        if drained:
            for _ in self._workers:
                await self._queue.put(None)
            await asyncio.gather(*self._workers, return_exceptions=True)
        else:
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._state = "stopped"

    async def _worker_loop(self) -> None:
        if self._handler is None:
            raise RuntimeError("Shadow dispatcher has no handler")
        while True:
            command = await self._queue.get()
            try:
                if command is None:
                    return
                await self._handler.handle(command)
                self._completed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self._failed += 1
                logger.exception("Shadow observation command failed")
            finally:
                if command is not None:
                    self._pending_keys.discard(
                        self._command_key(command)
                    )
                self._queue.task_done()

    async def _recovery_loop(self) -> None:
        if self._recovery_source is None:
            return
        while self._state == "running":
            try:
                available = max(
                    0,
                    self._queue.maxsize - self._queue.qsize(),
                )
                if available:
                    commands = await self._recovery_source.pending(
                        limit=available,
                    )
                    for command in commands:
                        if self._state != "running":
                            break
                        self.submit(command)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Shadow enrollment recovery scan failed"
                )
            try:
                await asyncio.wait_for(
                    self._recovery_stop.wait(),
                    timeout=self._recovery_interval_seconds,
                )
            except TimeoutError:
                continue
            return

    @staticmethod
    def _command_key(command: ShadowControllerCommand) -> str:
        from app.services.agent_core.shadow_observation_key import (
            shadow_observation_key,
        )

        return shadow_observation_key(
            command,
            command.controller_fingerprint,
        )


_dispatcher: ShadowObservationDispatcher | None = None


async def init_shadow_observation_dispatcher() -> None:
    global _dispatcher
    if _dispatcher is None:
        from app.infra.config import get_settings

        settings = get_settings()
        mode = getattr(settings, "AGENT_CONTROLLER_V1_MODE", "off")
        if mode in {"shadow", "live"}:
            from app.services.agent_core.release_identity import (
                require_release_commit_sha,
            )

            source_commit_sha = require_release_commit_sha(
                settings.AGENT_RELEASE_COMMIT_SHA
            )
        else:
            source_commit_sha = None
        if mode != "shadow":
            return
        from app.services.agent_core.shadow_recovery import (
            ShadowEnrollmentRecoverySource,
        )

        recovery_source = ShadowEnrollmentRecoverySource(
            source_commit_sha=source_commit_sha,
        )
        _dispatcher = ShadowObservationDispatcher(
            recovery_source=recovery_source,
            expected_source_commit_sha=source_commit_sha,
        )
    await _dispatcher.start()


def get_shadow_observation_dispatcher() -> ShadowObservationDispatcher:
    if _dispatcher is None:
        raise RuntimeError("Shadow observation dispatcher is not initialized")
    return _dispatcher


async def dispose_shadow_observation_dispatcher() -> None:
    global _dispatcher
    current = _dispatcher
    _dispatcher = None
    if current is not None:
        await current.stop()


__all__ = [
    "ShadowControllerCommand",
    "ShadowDispatchReceipt",
    "ShadowDispatcherMetrics",
    "ShadowObservationDispatcher",
    "ShadowRecoverySource",
    "dispose_shadow_observation_dispatcher",
    "get_shadow_observation_dispatcher",
    "init_shadow_observation_dispatcher",
]
