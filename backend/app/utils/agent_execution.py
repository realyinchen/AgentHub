"""Agent execution persistence service.

Provides unified persistence for token usage and execution DAG after
an agent completes its response. Used by both invoke and stream paths.

Usage (invoke path)::

    from app.utils.agent_execution import AgentExecutionService

    service = AgentExecutionService(supervisor)
    await service.persist(
        db=db,
        thread_id=thread_id,
        request_id=request_id,
        model_name=model_name,
        tokens=totals,
    )

Usage (stream path — inside AsyncWriteQueue callback)::

    async def _persist():
        db = get_database()
        async with db.session() as session:
            await service.persist(
                db=session,
                thread_id=thread_id,
                request_id=request_id,
                model_name=model_name,
                tokens=tokens,
            )
    write_queue.add("persist", _persist())
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from langgraph.graph.state import CompiledStateGraph

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AgentExecutionService:
    """Unified agent execution persistence service.

    Responsibilities:
        1. Persist token usage to the conversation table
        2. Persist execution DAG snapshot to trace_executions table

    Both operations are wrapped in independent try/except blocks so that
    a failure in one (e.g. DAG construction) never prevents the other
    from completing.
    """

    def __init__(self, agent: CompiledStateGraph) -> None:
        """Initialize the service with a compiled agent graph.

        Args:
            agent: A compiled LangGraph agent used for DAG reconstruction.
        """
        self._agent = agent

    async def persist(
        self,
        db: AsyncSession,
        *,
        thread_id: UUID,
        request_id: str,
        model_name: str | None,
        tokens: dict[str, int],
    ) -> None:
        """Persist token usage and execution DAG after an agent response.

        Both operations are wrapped in try/except so that a failure in one
        (e.g. DAG construction) never prevents the other from completing.

        Args:
            db: An active async database session (not auto-committed inside
                this function — the caller owns transaction boundaries).
            thread_id: Conversation thread identifier.
            request_id: Unique request identifier for this invocation.
            model_name: Resolved model name (or None).
            tokens: A dict with keys: input_tokens, cache_read, output_tokens,
                reasoning, total_tokens.
        """
        from app.crud import chat as chat_crud
        from app.crud import trace as trace_crud
        from app.utils.dag import DagBuilder

        thread_id_str = str(thread_id)

        # Token persistence
        if tokens["total_tokens"] > 0:
            try:
                await chat_crud.update_conversation_tokens(
                    db=db,
                    thread_id=thread_id,
                    input_tokens=tokens["input_tokens"],
                    cache_read=tokens["cache_read"],
                    output_tokens=tokens["output_tokens"],
                    reasoning=tokens["reasoning"],
                    total_tokens=tokens["total_tokens"],
                )
            except Exception:
                logger.exception("Failed to persist token usage for %s", request_id)

        # DAG persistence
        try:
            dag_builder = DagBuilder(self._agent)
            dag = await dag_builder.get_execution_dag(thread_id_str)
            await trace_crud.upsert_trace(
                db=db,
                thread_id=thread_id,
                request_id=str(request_id),
                dag_data=dag.model_dump(),
                total_steps=len(dag.steps),
                model_name=model_name,
                input_tokens=tokens.get("input_tokens", 0),
                cache_read=tokens.get("cache_read", 0),
                output_tokens=tokens.get("output_tokens", 0),
                reasoning=tokens.get("reasoning", 0),
                total_tokens=tokens.get("total_tokens", 0),
            )
        except Exception:
            logger.exception("Failed to persist DAG for %s", request_id)