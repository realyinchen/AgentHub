from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.services.agent_runtime.contracts import ActionPlan, ActionReceipt, PlanReceipt


FailureStage = Literal[
    "planning",
    "source_search",
    "source_collection",
    "evidence_admission",
    "report_building",
    "answer_synthesis",
    "answer_publication",
    "execution",
]


class RuntimeFailureSummary(BaseModel):
    """Stable user-facing projection of a technical execution failure."""

    stage: FailureStage
    operation: str
    user_message: str
    technical_error: str = ""
    retryable: bool = False


_FAILURE_PROJECTIONS: dict[str, tuple[FailureStage, str, bool]] = {
    "start_research": (
        "planning",
        "研究任务未能初始化。",
        True,
    ),
    "web_search": (
        "source_search",
        "外部检索服务未能返回可用结果，本次研究没有获得可核验来源。",
        True,
    ),
    "plan_research_search": (
        "planning",
        "研究搜索任务未能生成。",
        True,
    ),
    "acquire_research_sources": (
        "source_search",
        "外部检索服务未能返回可用结果，本次研究没有获得可核验来源。",
        True,
    ),
    "collect_research_sources": (
        "source_collection",
        "检索结果未能转换为可追踪的来源记录。",
        True,
    ),
    "add_evidence": (
        "evidence_admission",
        "候选来源未能完成证据准入。",
        True,
    ),
    "evaluate_research_gaps": (
        "evidence_admission",
        "研究证据缺口未能完成评估。",
        True,
    ),
    "build_research_report": (
        "report_building",
        "已准入证据未能形成结构化研究报告。",
        True,
    ),
    "synthesize_research_answer": (
        "answer_synthesis",
        "结构化研究报告未能完成受约束综合。",
        True,
    ),
    "publish_research_answer": (
        "answer_publication",
        "结构化研究结果未能完成最终发布。",
        True,
    ),
    "finalize_research_answer": (
        "answer_publication",
        "结构化研究结果未能完成最终发布。",
        True,
    ),
}


def project_runtime_failure(
    plan: ActionPlan,
    receipt: PlanReceipt,
) -> RuntimeFailureSummary | None:
    """Return the first actionable failure without exposing graph identifiers."""

    failed = _root_failure(receipt.actions)
    if failed is None:
        return None

    stage, message, retryable = _FAILURE_PROJECTIONS.get(
        failed.operation,
        ("execution", "研究执行未能完成。", True),
    )
    if failed.status == "blocked":
        message = _blocked_message(stage)
        retryable = False

    return RuntimeFailureSummary(
        stage=stage,
        operation=failed.operation,
        user_message=message,
        technical_error=failed.error,
        retryable=retryable,
    )


def render_research_failure(summary: RuntimeFailureSummary | None) -> str:
    """Render bounded Markdown while technical detail remains in the trace."""

    reason = (
        summary.user_message
        if summary is not None
        else "研究执行没有生成最终发布结果。"
    )
    return (
        "## 研究状态\n"
        "本次研究未能完成。\n\n"
        "## 原因\n"
        f"{reason}\n\n"
        "## 处理原则\n"
        "由于证据链未闭合，我没有生成未经验证的结论。"
    )


def _root_failure(actions: list[ActionReceipt]) -> ActionReceipt | None:
    for status in ("failed", "blocked"):
        match = next((item for item in actions if item.status == status), None)
        if match is not None:
            return match
    return next((item for item in actions if item.status == "skipped"), None)


def _blocked_message(stage: FailureStage) -> str:
    if stage == "source_search":
        return "当前策略未允许执行外部检索，因此没有获得可核验来源。"
    return "当前执行策略未允许研究链继续运行。"
