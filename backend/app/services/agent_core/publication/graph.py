from __future__ import annotations

from app.services.agent_core.publication.contracts import (
    PublicExecutionGraph,
    PublicExecutionGraphEdge,
    PublicExecutionGraphNode,
)
from app.services.agent_core.turn_contracts import TurnReceipt
from app.services.agent_runtime.execution_graph import (
    ExecutionGraph,
    ExecutionGraphEdge,
    ExecutionGraphNode,
)


def project_public_execution_graph(
    graph: ExecutionGraph,
) -> PublicExecutionGraph:
    """Redact one authoritative graph without recomputing its topology."""

    ordered = sorted(graph.nodes, key=lambda item: item.order)
    public_id_by_internal: dict[str, str] = {}
    action_index = 0
    public_nodes: list[PublicExecutionGraphNode] = []
    for node in ordered:
        if node.kind == "user":
            public_id = "turn"
        elif node.kind == "response":
            public_id = "answer"
        else:
            action_index += 1
            public_id = f"step-{action_index}"
        public_id_by_internal[node.node_id] = public_id
        public_nodes.append(
            PublicExecutionGraphNode(
                node_id=public_id,
                kind=node.kind,
                label=node.label,
                status=node.status,
                order=node.order,
            )
        )
    return PublicExecutionGraph(
        nodes=public_nodes,
        edges=[
            PublicExecutionGraphEdge(
                source_id=public_id_by_internal[edge.source_id],
                target_id=public_id_by_internal[edge.target_id],
                relation=edge.relation,
            )
            for edge in graph.edges
        ],
    )


def build_turn_execution_graph(
    turn: TurnReceipt | None,
    *,
    request_id: str,
) -> ExecutionGraph:
    """Build one continuous graph from ordered normalized round plans."""

    user_node_id = f"user:{request_id}"
    response_node_id = f"response:{request_id}"
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
    edges: list[ExecutionGraphEdge] = []
    order = 0
    previous_terminals = [user_node_id]

    rounds = turn.rounds if turn is not None else []
    for round_receipt in rounds:
        plan = round_receipt.plan
        receipt = round_receipt.receipt
        if plan is None or receipt is None:
            continue
        if plan.plan_id != receipt.plan_id:
            raise ValueError("turn contains a mismatched plan receipt")
        receipt_by_id = {
            item.action_id: item for item in receipt.actions
        }
        node_by_action = {
            action.action_id: (
                f"action:r{round_receipt.round_no}:{action.action_id}"
            )
            for action in plan.actions
        }
        depended_on = {
            dependency
            for action in plan.actions
            for dependency in action.depends_on
        }
        roots = [
            action for action in plan.actions if not action.depends_on
        ]
        for action in plan.actions:
            order += 1
            action_receipt = receipt_by_id.get(action.action_id)
            nodes.append(
                ExecutionGraphNode(
                    node_id=node_by_action[action.action_id],
                    kind="action",
                    label=action.operation,
                    status=(
                        action_receipt.status
                        if action_receipt is not None
                        else "missing"
                    ),
                    order=order,
                    step_number=order + 1,
                    action_id=(
                        f"r{round_receipt.round_no}:"
                        f"{action.action_id}"
                    ),
                    capability=action.capability,
                    operation=action.operation,
                    metadata={
                        "required": action.required,
                        "system_executed": bool(
                            action_receipt
                            and action_receipt.system_executed
                        ),
                        "round_no": round_receipt.round_no,
                    },
                )
            )
            for dependency in action.depends_on:
                edges.append(
                    _turn_edge(
                        node_by_action[dependency],
                        node_by_action[action.action_id],
                        relation="dependency",
                    )
                )
        for root in roots:
            for previous in previous_terminals:
                edges.append(
                    _turn_edge(
                        previous,
                        node_by_action[root.action_id],
                        relation=(
                            "entry"
                            if previous == user_node_id
                            else "dependency"
                        ),
                    )
                )
        terminals = [
            node_by_action[action.action_id]
            for action in plan.actions
            if action.action_id not in depended_on
        ]
        if terminals:
            previous_terminals = terminals

    order += 1
    nodes.append(
        ExecutionGraphNode(
            node_id=response_node_id,
            kind="response",
            label="AI",
            status="response",
            order=order,
            step_number=order + 1,
        )
    )
    for previous in previous_terminals:
        edges.append(
            _turn_edge(
                previous,
                response_node_id,
                relation="response",
            )
        )
    return ExecutionGraph(
        plan_id=f"turn:{request_id}",
        request_id=request_id,
        entry_node_id=user_node_id,
        exit_node_id=response_node_id,
        nodes=nodes,
        edges=edges,
    )


def _turn_edge(
    source_id: str,
    target_id: str,
    *,
    relation: str,
) -> ExecutionGraphEdge:
    return ExecutionGraphEdge(
        edge_id=f"{relation}:{source_id}->{target_id}",
        source_id=source_id,
        target_id=target_id,
        relation=relation,
    )


__all__ = [
    "build_turn_execution_graph",
    "project_public_execution_graph",
]
