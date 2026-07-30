from __future__ import annotations

from collections import defaultdict

from app.services.agent_runtime.contracts import ActionPlan, PlannedAction


class PlanGraphNormalizer:
    """Validate and stably topologically order one ActionPlan."""

    def normalize(self, plan: ActionPlan) -> ActionPlan:
        by_id = {action.action_id: action for action in plan.actions}
        indegree = {action.action_id: 0 for action in plan.actions}
        outgoing: dict[str, list[str]] = defaultdict(list)
        order_index = {
            action.action_id: index for index, action in enumerate(plan.actions)
        }

        for action in plan.actions:
            if action.action_id in action.depends_on:
                raise ValueError(
                    f"action {action.action_id} cannot depend on itself"
                )
            for dependency in action.depends_on:
                if dependency not in by_id:
                    raise ValueError(
                        f"action {action.action_id} has unknown dependency "
                        f"{dependency}"
                    )
                indegree[action.action_id] += 1
                outgoing[dependency].append(action.action_id)

        ready = sorted(
            [item for item, degree in indegree.items() if degree == 0],
            key=order_index.__getitem__,
        )
        normalized: list[PlannedAction] = []
        while ready:
            action_id = ready.pop(0)
            normalized.append(by_id[action_id])
            for child in sorted(
                outgoing[action_id],
                key=order_index.__getitem__,
            ):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort(key=order_index.__getitem__)

        if len(normalized) != len(plan.actions):
            cycle_nodes = sorted(
                item for item, degree in indegree.items() if degree > 0
            )
            raise ValueError(
                "action plan contains a dependency cycle: "
                + ", ".join(cycle_nodes)
            )

        metadata = dict(plan.metadata)
        metadata.update(
            {
                "graph_normalized": True,
                "execution_order": [
                    action.action_id for action in normalized
                ],
                "parallel_execution": False,
            }
        )
        return plan.model_copy(
            update={"actions": normalized, "metadata": metadata}
        )
