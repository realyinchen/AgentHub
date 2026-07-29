from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    PlanReceipt,
    PlannedAction,
)
from app.services.agent_runtime.execution_graph import build_execution_graph
from app.services.agent_runtime.finalizer import finalize_runtime_receipt
from app.services.research.contracts import ResearchEvidence
from app.services.research.publication import (
    publish_research_answer,
    synthesize_research_report_deterministic,
)
from app.services.research.report import (
    ResearchReport,
    ResearchReportMemoryContext,
    ResearchReportSource,
)
from app.services.research.source_extraction import (
    extract_research_source_records,
)
from app.services.research.verifier import (
    ClaimAdmissionDecision,
    ClaimForVerification,
    EvidenceReference,
    ResearchVerifier,
    VerifierAdmissionInput,
    VerifierAdmissionResult,
)


def _assert_execution_graph() -> None:
    actions = [
        PlannedAction(
            action_id="start",
            capability="research",
            operation="start_research",
        ),
        PlannedAction(
            action_id="left",
            capability="web",
            operation="web_search",
            depends_on=["start"],
        ),
        PlannedAction(
            action_id="right",
            capability="book",
            operation="search_books",
            depends_on=["start"],
        ),
        PlannedAction(
            action_id="publish",
            capability="research",
            operation="publish_research_answer",
            depends_on=["left", "right"],
        ),
    ]
    plan = ActionPlan(
        plan_id="plan-test",
        source="routing_decision",
        route_type="slow_path",
        intent="deep_research",
        goal="test",
        response_mode="receipt",
        actions=actions,
    )
    receipt = PlanReceipt(
        plan_id=plan.plan_id,
        request_id="request-test",
        route_type=plan.route_type,
        intent=plan.intent,
        status="completed",
        actions=[
            ActionReceipt(
                action_id=action.action_id,
                capability=action.capability,
                operation=action.operation,
                status="completed",
                admitted=True,
            )
            for action in actions
        ],
    )
    graph = build_execution_graph(plan, receipt)
    edge_pairs = {(edge.source_id, edge.target_id) for edge in graph.edges}
    assert ("action:start", "action:left") in edge_pairs
    assert ("action:start", "action:right") in edge_pairs
    assert ("action:left", "action:publish") in edge_pairs
    assert ("action:right", "action:publish") in edge_pairs
    incoming = {node.node_id: 0 for node in graph.nodes}
    for edge in graph.edges:
        incoming[edge.target_id] += 1
    assert all(
        count > 0
        for node_id, count in incoming.items()
        if node_id != graph.entry_node_id
    )


def _assert_source_quality() -> None:
    noisy = (
        "回忆小学三四五六年级课外书必读 我的野生动物朋友 正版 带皮 "
        "德格雷二年级小学生必读课外书阅读 现货 包邮 旗舰店 优惠 "
    ) * 24
    rejected = extract_research_source_records(
        query="最新的好评动物图书",
        documents=[
            {
                "title": "淘宝商品",
                "url": "https://item.taobao.com/item.htm?id=1",
                "content": noisy,
                "quality": "medium",
            }
        ],
    )
    assert rejected.extracted_count == 0
    reason_codes = set(rejected.rejected_documents[0].reason_codes)
    assert "marketplace_source" in reason_codes
    assert reason_codes.intersection({"claim_too_long", "keyword_stuffing"})

    accepted = extract_research_source_records(
        query="最新的好评动物图书",
        documents=[
            {
                "title": "童书出版资讯",
                "url": "https://example.org/books/forest-friends",
                "content": (
                    "《森林里的朋友》于2026年出版，书评人称其图文结合方式"
                    "适合儿童理解野生动物。"
                ),
                "quality": "medium",
            }
        ],
    )
    assert accepted.extracted_count == 1
    assert len(accepted.source_records[0].claim) <= 320

    stale = extract_research_source_records(
        query="最新的好评科普图书",
        documents=[
            {
                "title": "中华优秀科普图书榜",
                "url": "https://example.org/old-list",
                "published_date": "2026-07-20",
                "content": (
                    "该活动共有200余家出版机构的3000多种图书参与评选，"
                    "最终推荐了近300种优秀科普读物。"
                ),
                "quality": "medium",
            }
        ],
    )
    assert stale.extracted_count == 0
    assert "missing_recency_evidence" in stale.rejected_documents[0].reason_codes

    evidence_id = uuid4()
    run_id = uuid4()
    verifier = ResearchVerifier()
    result = verifier.verify(
        VerifierAdmissionInput(
            run_id=run_id,
            objective="最新的好评动物图书",
            candidate_claims=[
                ClaimForVerification(
                    claim=noisy,
                    evidence_ids=[evidence_id],
                    quality="medium",
                )
            ],
            evidence=[
                ResearchEvidence(
                    id=evidence_id,
                    run_id=run_id,
                    source_type="web",
                    source_title="淘宝商品",
                    source_url="https://item.taobao.com/item.htm?id=1",
                    claim=noisy,
                    excerpt=noisy,
                    quality="medium",
                )
            ],
        )
    )
    assert not result.admitted_claims
    assert result.rejected_claims
    assert not result.rejected_claims[0].publishable


def _assert_publication() -> None:
    run_id = uuid4()
    user_id = uuid4()
    evidence_id = uuid4()
    claim = (
        "《森林里的朋友》于2026年出版，书评人称其图文结合方式"
        "适合儿童理解野生动物。"
    )
    reference = EvidenceReference(
        id=evidence_id,
        source_type="web",
        source_title="童书出版资讯",
        source_url="https://example.org/books/forest-friends",
        quality="medium",
        relevance=5,
        source_class="editorial",
        provenance_valid=True,
        content_quality=1,
        query_relevance=1,
        publishable=True,
    )
    decision = ClaimAdmissionDecision(
        claim=claim,
        status="admitted",
        evidence_ids=[evidence_id],
        evidence=[reference],
        quality="medium",
        reason_codes=["supported_by_evidence"],
        provenance_valid=True,
        content_quality=1,
        query_relevance=1,
        corroborated=True,
        publishable=True,
    )
    verification = VerifierAdmissionResult(
        run_id=run_id,
        decisions=[decision],
        admitted_claims=[decision],
        ready_for_final_answer=True,
    )
    report = ResearchReport(
        run_id=run_id,
        user_id=user_id,
        objective="深度搜索最新的好评动物图书",
        run_status="completed",
        report_status="verified",
        verified_claims=[decision],
        sources=[
            ResearchReportSource(
                evidence_id=evidence_id,
                source_title="童书出版资讯",
                source_url="https://example.org/books/forest-friends",
                quality="medium",
                relevance=5,
                claim=claim,
            )
        ],
        memory_context=ResearchReportMemoryContext(
            constraints=["preference:user:positive:animal books"]
        ),
        verification=verification,
    )
    synthesis = synthesize_research_report_deterministic(report)
    published = publish_research_answer(report, synthesis)
    assert published.answer_status == "verified"
    assert "## 研究结论" in published.answer
    assert "## 主要发现" in published.answer
    assert "## 来源" in published.answer
    assert "Limitations:" not in published.answer
    assert all(
        len(finding.summary) <= 280
        for finding in published.brief.findings
    )
    assert published.sources[0].source_id == str(evidence_id)

    empty_verification = VerifierAdmissionResult(run_id=run_id)
    empty_report = ResearchReport(
        run_id=run_id,
        user_id=user_id,
        objective="最新的好评动物图书",
        run_status="completed",
        report_status="no_verified_claims",
        verification=empty_verification,
    )
    empty_synthesis = synthesize_research_report_deterministic(empty_report)
    empty_answer = publish_research_answer(empty_report, empty_synthesis)
    assert empty_answer.answer_status == "blocked_no_publishable_evidence"
    assert "## 证据限制" in empty_answer.answer
    assert "出版或发布时间" in empty_answer.answer
    assert "评分、评论或榜单" in empty_answer.answer


def _assert_failure_projection() -> None:
    operations = [
        "start_research",
        "web_search",
        "collect_research_sources",
        "add_evidence",
        "build_research_report",
        "synthesize_research_answer",
        "publish_research_answer",
    ]
    actions: list[PlannedAction] = []
    previous_action_id = ""
    for index, operation in enumerate(operations):
        action_id = f"action-{index}"
        actions.append(
            PlannedAction(
                action_id=action_id,
                capability="web" if operation == "web_search" else "research",
                operation=operation,
                depends_on=[previous_action_id] if previous_action_id else [],
            )
        )
        previous_action_id = action_id
    plan = ActionPlan(
        plan_id="plan-failure",
        source="routing_decision",
        route_type="slow_path",
        intent="deep_research",
        goal="最新的好评图书",
        response_mode="receipt",
        actions=actions,
    )
    receipts = [
        ActionReceipt(
            action_id=actions[0].action_id,
            capability=actions[0].capability,
            operation=actions[0].operation,
            status="completed",
            admitted=True,
        ),
        ActionReceipt(
            action_id=actions[1].action_id,
            capability=actions[1].capability,
            operation=actions[1].operation,
            status="failed",
            error="provider timeout",
            admitted=True,
        ),
    ]
    receipts.extend(
        ActionReceipt(
            action_id=action.action_id,
            capability=action.capability,
            operation=action.operation,
            status="skipped",
            error=f"dependency did not complete: {actions[1].action_id}",
        )
        for action in actions[2:]
    )
    receipt = PlanReceipt(
        plan_id=plan.plan_id,
        request_id="request-failure",
        route_type=plan.route_type,
        intent=plan.intent,
        status="failed",
        actions=receipts,
    )
    message = finalize_runtime_receipt(plan, receipt)
    assert "外部检索服务" in message.content
    assert "dependency did not complete" not in message.content
    assert "action-" not in message.content
    assert message.custom_data["failure_summary"]["stage"] == "source_search"
    assert (
        message.custom_data["failure_summary"]["technical_error"]
        == "provider timeout"
    )


def main() -> None:
    _assert_execution_graph()
    _assert_source_quality()
    _assert_publication()
    _assert_failure_projection()
    print("verify_research_publication_architecture: ok")


if __name__ == "__main__":
    main()
