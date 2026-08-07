from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.agent_runtime.trace_redaction import redact_tool_args


EXECUTION_GRAPH_CONTRACT_VERSION = "execution-graph-v2"

ExecutionNodeKind = Literal["user", "action", "response"]
ExecutionNodeStatus = Literal[
    "input",
    "completed",
    "failed",
    "blocked",
    "skipped",
    "waiting",
    "response",
    "missing",
]
ExecutionEdgeRelation = Literal["dependency", "entry", "response"]


class ExecutionGraphNode(BaseModel):
    """One semantic node in a runtime execution graph.

    The graph deliberately contains observability metadata only. Action
    outputs remain in PlanReceipt and trace steps so graph topology never
    becomes another execution or persistence channel.
    """

    node_id: str
    kind: ExecutionNodeKind
    label: str
    status: ExecutionNodeStatus
    order: int = Field(ge=0)
    step_number: int = Field(ge=1)
    action_id: str | None = None
    capability: str | None = None
    operation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionGraphEdge(BaseModel):
    edge_id: str
    source_id: str
    target_id: str
    relation: ExecutionEdgeRelation


class ExecutionGraph(BaseModel):
    """Versioned topology projected from ActionPlan plus PlanReceipt."""

    contract_version: str = EXECUTION_GRAPH_CONTRACT_VERSION
    plan_id: str
    request_id: str
    entry_node_id: str
    exit_node_id: str
    nodes: list[ExecutionGraphNode] = Field(default_factory=list)
    edges: list[ExecutionGraphEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_topology(self) -> "ExecutionGraph":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("execution graph node ids must be unique")
        known = set(node_ids)
        if self.entry_node_id not in known or self.exit_node_id not in known:
            raise ValueError("execution graph entry and exit nodes must exist")
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("execution graph edge ids must be unique")
        dangling = [
            edge.edge_id
            for edge in self.edges
            if edge.source_id not in known or edge.target_id not in known
        ]
        if dangling:
            raise ValueError(f"execution graph contains dangling edges: {dangling}")
        return self


def build_execution_graph(
    plan: ActionPlan,
    receipt: PlanReceipt,
) -> ExecutionGraph:
    """Project authoritative dependencies without inferring message order."""

    if receipt.plan_id != plan.plan_id:
        raise ValueError("receipt does not belong to the supplied action plan")

    user_node_id = f"user:{receipt.request_id}"
    response_node_id = f"response:{receipt.request_id}"
    receipts_by_id = {item.action_id: item for item in receipt.actions}
    action_node_ids = {
        action.action_id: f"action:{action.action_id}"
        for action in plan.actions
    }
    nodes: list[ExecutionGraphNode] = [
        ExecutionGraphNode(
            node_id=user_node_id,
            kind="user",
            label="用户",
            status="input",
            order=0,
            step_number=1,
        )
    ]
    for index, action in enumerate(plan.actions, start=1):
        action_receipt = receipts_by_id.get(action.action_id)
        nodes.append(
            ExecutionGraphNode(
                node_id=action_node_ids[action.action_id],
                kind="action",
                label=action.operation,
                status=(
                    action_receipt.status
                    if action_receipt is not None
                    else "missing"
                ),
                order=index,
                step_number=index + 1,
                action_id=action.action_id,
                capability=action.capability,
                operation=action.operation,
                metadata={
                    "required": action.required,
                    "system_executed": bool(
                        action_receipt and action_receipt.system_executed
                    ),
                    "tool_args": redact_tool_args(action.arguments),
                },
            )
        )
    nodes.append(
        ExecutionGraphNode(
            node_id=response_node_id,
            kind="response",
            label="AI",
            status="response",
            order=len(plan.actions) + 1,
            step_number=len(plan.actions) + 2,
        )
    )

    edges: list[ExecutionGraphEdge] = []
    depended_on = {
        dependency
        for action in plan.actions
        for dependency in action.depends_on
    }
    for action in plan.actions:
        target_id = action_node_ids[action.action_id]
        if action.depends_on:
            for dependency in action.depends_on:
                source_id = action_node_ids[dependency]
                edges.append(
                    _edge(source_id, target_id, relation="dependency")
                )
        else:
            edges.append(_edge(user_node_id, target_id, relation="entry"))

    terminal_actions = [
        action
        for action in plan.actions
        if action.action_id not in depended_on
    ]
    if terminal_actions:
        for action in terminal_actions:
            edges.append(
                _edge(
                    action_node_ids[action.action_id],
                    response_node_id,
                    relation="response",
                )
            )
    else:
        edges.append(_edge(user_node_id, response_node_id, relation="response"))

    return ExecutionGraph(
        plan_id=plan.plan_id,
        request_id=receipt.request_id,
        entry_node_id=user_node_id,
        exit_node_id=response_node_id,
        nodes=nodes,
        edges=edges,
    )


def _edge(
    source_id: str,
    target_id: str,
    *,
    relation: ExecutionEdgeRelation,
) -> ExecutionGraphEdge:
    return ExecutionGraphEdge(
        edge_id=f"{relation}:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        relation=relation,
    )
