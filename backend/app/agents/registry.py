"""Agent factory registry and compiled graph store.

Each agent module calls register_factory() at module level to register
its compile-time factory.  At startup (and on any DB-triggered reload),
reload_agents() reads is_active=True rows from the agents table, calls
each factory with checkpointer/store, and populates a frozen snapshot.

Runtime lookups are plain dict reads on an immutable dataclass — zero overhead.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select

from app.infra.database import get_database
from app.models.agent import Agent as AgentModel

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────

# Factory signature: (checkpointer, store) → compiled graph
# Use Any to avoid invariance issues with LangGraph's generic CompiledStateGraph.
FactoryFn = Callable[[Any, Any], Any]

_factories: dict[str, FactoryFn] = {}

_reload_lock = asyncio.Lock()


@dataclass(frozen=True)
class RegistrySnapshot:
    """Immutable snapshot of compiled agents and their metadata.

    Frozen + single assignment ensures graphs and metadata are
    always consistent — no split-brain between the two dicts.
    """

    graphs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, AgentModel] = field(default_factory=dict)

    def get(self, agent_id: str) -> Any | None:
        return self.graphs.get(agent_id)

    def ids(self) -> list[str]:
        return list(self.graphs.keys())

    def list_metadata(self) -> list[AgentModel]:
        return list(self.metadata.values())

    def __len__(self) -> int:
        return len(self.graphs)


# Single atomic reference — CPython module-level assignment is atomic under GIL.
_snapshot: RegistrySnapshot = RegistrySnapshot()


def register_factory(agent_id: str, factory: FactoryFn) -> None:
    """Register an agent factory. Must be called at module import time.

    The factory signature is ``(checkpointer, store) -> compiled_graph``.
    These are injected by reload_agents / reload_agent.
    """
    _factories[agent_id] = factory
    logger.debug("Agent factory registered: %s", agent_id)


# ── Lifecycle ─────────────────────────────────────────────────────────


async def _compile_agents(
    rows: list[AgentModel],
    checkpointer: Any,
    store: Any,
) -> tuple[dict[str, Any], dict[str, AgentModel], list[str]]:
    """Shared compilation logic for both reload_agents and reload_agent."""
    graphs: dict[str, Any] = {}
    metadata: dict[str, AgentModel] = {}
    skipped: list[str] = []

    for row in rows:
        factory = _factories.get(row.agent_id)
        if factory is None:
            logger.warning(
                "Agent %r is active in DB but has no registered factory — skipping",
                row.agent_id,
            )
            skipped.append(row.agent_id)
            continue
        logger.info("Compiling agent: %s", row.agent_id)
        try:
            graphs[row.agent_id] = factory(checkpointer, store)
        except Exception:
            logger.exception("Failed to compile agent %r", row.agent_id)
            continue
        metadata[row.agent_id] = row

    return graphs, metadata, skipped


async def reload_agents() -> None:
    """Read is_active=True agents from DB, compile with checkpointer/store,
    atomically replace the snapshot.

    Called once at startup and on any agent-table mutation. Protected
    by asyncio.Lock — only one reload runs at a time.
    """
    async with _reload_lock:
        from app.infra.database import get_checkpointer, get_store

        checkpointer = get_checkpointer().get_saver()
        store_iface = get_store()
        store = store_iface.get_store() if store_iface is not None else None

        db = get_database()
        async with db.session() as session:
            result = await session.execute(
                select(AgentModel).where(AgentModel.is_active)
            )
            rows: list[AgentModel] = list(result.scalars().all())

        graphs, metadata, skipped = await _compile_agents(rows, checkpointer, store)

        # Atomic write — in-flight requests keep their old reference.
        global _snapshot
        _snapshot = RegistrySnapshot(graphs=graphs, metadata=metadata)

        if skipped:
            logger.warning(
                "Agent registry reloaded: %d active, %d factories missing: %s",
                len(graphs),
                len(skipped),
                skipped,
            )
        else:
            logger.info("Agent registry reloaded: %d agents active", len(graphs))

        # Log registered factories without DB entries (configuration drift).
        registered = set(_factories.keys())
        db_active = {r.agent_id for r in rows}
        orphan_factories = registered - db_active
        if orphan_factories:
            logger.info(
                "Factories registered but not active in DB: %s — "
                "these agents are available for activation",
                sorted(orphan_factories),
            )


async def reload_agent(agent_id: str) -> None:
    """Incremental reload: recompile a single agent (add, update, or remove).

    Reads the agent row from DB, recompiles if active + factory exists,
    removes from snapshot if inactive or factory missing. Protected by
    the same asyncio.Lock as reload_agents().
    """
    async with _reload_lock:
        from app.infra.database import get_checkpointer, get_store

        checkpointer = get_checkpointer().get_saver()
        store_iface = get_store()
        store = store_iface.get_store() if store_iface is not None else None

        db = get_database()
        async with db.session() as session:
            row = await session.get(AgentModel, agent_id)

        global _snapshot
        old = _snapshot
        new_graphs = dict(old.graphs)
        new_metadata = dict(old.metadata)

        if row is None or not row.is_active:
            # Agent deleted or deactivated — remove from snapshot
            new_graphs.pop(agent_id, None)
            new_metadata.pop(agent_id, None)
            _snapshot = RegistrySnapshot(graphs=new_graphs, metadata=new_metadata)
            if old.graphs.get(agent_id) is not None:
                logger.info(
                    "Agent %r removed from registry (inactive/deleted)", agent_id
                )
            return

        factory = _factories.get(agent_id)
        if factory is None:
            logger.warning(
                "Agent %r is active in DB but has no registered factory — "
                "cannot compile",
                agent_id,
            )
            new_graphs.pop(agent_id, None)
            new_metadata.pop(agent_id, None)
            _snapshot = RegistrySnapshot(graphs=new_graphs, metadata=new_metadata)
            return

        try:
            new_graphs[agent_id] = factory(checkpointer, store)
            new_metadata[agent_id] = row
            _snapshot = RegistrySnapshot(graphs=new_graphs, metadata=new_metadata)
            logger.info("Agent %r reloaded incrementally", agent_id)
        except Exception:
            logger.exception("Failed to compile agent %r", agent_id)
            # Keep old version if compile fails
            _snapshot = RegistrySnapshot(graphs=new_graphs, metadata=new_metadata)


# ── Runtime read API (plain dict on frozen dataclass, sub-microsecond) ─


class AgentNotFoundError(LookupError):
    """Raised when a required agent is not in the registry."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent {agent_id!r} not found in registry")
        self.agent_id = agent_id


def get_graph(agent_id: str) -> Any | None:
    """Return the compiled graph for *agent_id*, or None if not active."""
    return _snapshot.get(agent_id)


def require_graph(agent_id: str) -> Any:
    """Return the compiled graph for *agent_id*, or raise AgentNotFoundError.

    Prefer this over get_graph() when the agent MUST exist — it gives
    a clear error message and avoids None-check boilerplate in callers.
    """
    graph = _snapshot.get(agent_id)
    if graph is None:
        raise AgentNotFoundError(agent_id)
    return graph


def get_metadata(agent_id: str) -> AgentModel | None:
    return _snapshot.metadata.get(agent_id)


def list_metadata() -> list[AgentModel]:
    return _snapshot.list_metadata()


def get_ids() -> list[str]:
    return _snapshot.ids()


def get_snapshot_size() -> int:
    """Return number of active agents."""
    return len(_snapshot)


__all__ = [
    "AgentNotFoundError",
    "FactoryFn",
    "RegistrySnapshot",
    "register_factory",
    "reload_agents",
    "reload_agent",
    "get_graph",
    "require_graph",
    "get_metadata",
    "list_metadata",
    "get_ids",
    "get_snapshot_size",
]
