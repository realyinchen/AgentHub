from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.chat import ChatMessage
from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.agent_runtime.execution_graph import ExecutionGraph
from app.services.conversation.journal_contracts import (
    ConversationJournalEvent,
)


class ReceiptEvidenceBundle(AgentCoreModel):
    """One normalized plan and its matching immutable runtime receipt."""

    plan: ActionPlan
    receipt: PlanReceipt

    @model_validator(mode="after")
    def validate_ownership(self) -> "ReceiptEvidenceBundle":
        if self.plan.plan_id != self.receipt.plan_id:
            raise ValueError("receipt does not belong to the supplied plan")
        planned = {action.action_id for action in self.plan.actions}
        foreign = [
            action.action_id
            for action in self.receipt.actions
            if action.action_id not in planned
        ]
        if foreign:
            raise ValueError("receipt contains actions outside its plan")
        return self


class PublicExecutionGraphNode(AgentCoreModel):
    node_id: str = Field(min_length=1, max_length=128)
    kind: Literal["user", "action", "response"]
    label: str = Field(min_length=1, max_length=256)
    status: Literal[
        "input",
        "completed",
        "failed",
        "blocked",
        "skipped",
        "waiting",
        "response",
        "missing",
    ]
    order: int = Field(ge=0)


class PublicExecutionGraphEdge(AgentCoreModel):
    source_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=128)
    relation: Literal["dependency", "entry", "response"]


class PublicExecutionGraph(AgentCoreModel):
    contract_version: Literal[
        "public-execution-graph-v1"
    ] = "public-execution-graph-v1"
    nodes: list[PublicExecutionGraphNode] = Field(default_factory=list)
    edges: list[PublicExecutionGraphEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_topology(self) -> "PublicExecutionGraph":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("public graph node ids must be unique")
        known = set(node_ids)
        if any(
            edge.source_id not in known or edge.target_id not in known
            for edge in self.edges
        ):
            raise ValueError("public graph contains a dangling edge")
        return self


class TrustedStreamEvent(AgentCoreModel):
    protocol_version: Literal["agent-stream-v1"] = "agent-stream-v1"
    sequence: int = Field(ge=1)
    type: Literal[
        "turn.started",
        "graph.snapshot",
        "answer.completed",
        "clarification.required",
        "turn.failed",
    ]
    request_id: str = Field(min_length=1, max_length=128)
    content: dict[str, Any] = Field(default_factory=dict)


class CommittedPublication(AgentCoreModel):
    """A final projection whose Journal transaction has already committed."""

    message: ChatMessage
    journal_event: ConversationJournalEvent
    execution_graph: ExecutionGraph

    @model_validator(mode="after")
    def validate_publication(self) -> "CommittedPublication":
        if self.message.request_id != self.journal_event.request_id:
            raise ValueError("committed publication request mismatch")
        if (
            self.journal_event.event_type
            in {"assistant_published", "clarification_requested"}
            and self.message.content != self.journal_event.content
        ):
            raise ValueError("committed publication content mismatch")
        return self


__all__ = [
    "CommittedPublication",
    "PublicExecutionGraph",
    "PublicExecutionGraphEdge",
    "PublicExecutionGraphNode",
    "ReceiptEvidenceBundle",
    "TrustedStreamEvent",
]
