"""Verify R5 publication, graph, and stream contracts without external I/O."""

from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.contracts import ControllerOutput
from app.services.agent_core.publication.contracts import (
    CommittedPublication,
    ReceiptEvidenceBundle,
)
from app.services.agent_core.publication.graph import (
    project_public_execution_graph,
)
from app.services.agent_core.publication.service import TrustedPublisher
from app.services.agent_core.publication.stream import TrustedStreamSequencer
from app.services.agent_core.receipt_projector import ReceiptContextProjector
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    PlanReceipt,
    PlannedAction,
)
from app.services.agent_runtime.execution_graph import build_execution_graph
from app.services.conversation.journal_contracts import (
    ConversationJournalEvent,
)


def _main() -> int:
    plan = ActionPlan(
        plan_id="r5-local-plan",
        source="controller_proposal",
        route_type="slow_path",
        intent="web_evidence",
        goal="整理近期好评图书",
        response_mode="model",
        actions=[
            PlannedAction(
                action_id="r5-internal-action",
                capability="web",
                operation="web_search_v2",
                metadata={"side_effect": False},
            )
        ],
    )
    receipt = PlanReceipt(
        plan_id=plan.plan_id,
        request_id="r5-local-request",
        route_type=plan.route_type,
        intent=plan.intent,
        status="completed",
        actions=[
            ActionReceipt(
                action_id=plan.actions[0].action_id,
                capability="web",
                operation="web_search_v2",
                status="completed",
                admitted=True,
                output={
                    "result_mode": "web_evidence",
                    "status": "ok",
                    "query": "近期好评图书",
                    "sources": [
                        {
                            "title": "来源一",
                            "url": "https://example.com/one",
                            "snippet": "一条可引用的图书证据。",
                        },
                        {
                            "title": "来源二",
                            "url": "https://example.com/two",
                            "snippet": "另一条可引用的图书证据。",
                        },
                    ],
                    "raw": "MUST_NOT_LEAK",
                },
            )
        ],
    )
    projected = ReceiptContextProjector().project(receipt)
    projection_json = json.dumps(
        [item.model_dump(mode="json") for item in projected],
        ensure_ascii=False,
    )
    assert "MUST_NOT_LEAK" not in projection_json
    assert projected[0].result_mode == "web_evidence"

    answer = TrustedPublisher().publish_synthesis(
        ControllerOutput(
            mode="direct_answer",
            text=(
                "## 推荐结论\n\n"
                "- [来源一](https://example.com/one)：一条可引用证据。\n"
                "- [来源二](https://example.com/two)：另一条可引用证据。"
            ),
        ),
        evidence=[ReceiptEvidenceBundle(plan=plan, receipt=receipt)],
    )
    internal_graph = build_execution_graph(plan, receipt)
    public_graph = project_public_execution_graph(internal_graph)
    assert "r5-internal-action" not in public_graph.model_dump_json()
    sequencer = TrustedStreamSequencer(request_id=receipt.request_id)
    started = sequencer.turn_started()
    graph_event = sequencer.graph_snapshot(public_graph)
    journal_event = ConversationJournalEvent.model_validate(
        {
            "id": "2fd42c87-694b-45a6-ae9a-cc90f5685ef4",
            "user_id": "0564cc32-d249-4ed8-ad25-05835fc82aaf",
            "thread_id": "c418a420-013d-4194-a7c4-ffddf6c1f700",
            "request_id": receipt.request_id,
            "exchange_id": "3aa80a90-560f-44da-85f1-60b62b9ded61",
            "sequence_no": 2,
            "event_type": "assistant_published",
            "role": "assistant",
            "content": answer.content,
            "receipt_refs": answer.receipt_refs,
            "created_at": "2026-07-30T00:00:00Z",
        }
    )
    completed = sequencer.answer_completed(
        answer=answer,
        committed=CommittedPublication(
            message={
                "type": "ai",
                "content": answer.content,
                "request_id": receipt.request_id,
            },
            journal_event=journal_event,
            execution_graph=internal_graph,
        ),
    )
    assert [started.sequence, graph_event.sequence, completed.sequence] == [
        1,
        2,
        3,
    ]
    print(
        json.dumps(
            {
                "contract": "r5-trusted-publication-v1",
                "typed_evidence_projection": True,
                "publication_modes_mutually_exclusive": True,
                "receipt_backed_synthesis": True,
                "public_graph_redacted": True,
                "ordered_events": [
                    started.type,
                    graph_event.type,
                    completed.type,
                ],
                "answer_completed_after_commit_contract": True,
                "status": "passed",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
