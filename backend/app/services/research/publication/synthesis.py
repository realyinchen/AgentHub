from __future__ import annotations

import re
from typing import Any

from app.infra.llm.manager import get_model_manager
from app.services.research.publication.contracts import (
    ResearchBrief,
    ResearchFinding,
    ResearchSynthesisResult,
)
from app.services.research.publication.llm_provider import (
    LLMResearchSynthesisProvider,
)
from app.services.research.publication.provider import (
    ResearchSynthesisProvider,
    ResearchSynthesisRequest,
    SynthesisEvidence,
)
from app.services.research.report import ResearchReport


async def synthesize_research_report(
    report: ResearchReport | dict[str, Any],
    *,
    model_id: str = "",
    provider: ResearchSynthesisProvider | None = None,
    target_findings: int = 0,
) -> ResearchSynthesisResult:
    """Create a bounded brief; provider failure falls back to clean evidence."""

    validated = ResearchReport.model_validate(report)
    request = _request_from_report(validated)
    evidence_ids = [item.source_id for item in request.evidence]
    if not request.evidence:
        return ResearchSynthesisResult(
            run_id=validated.run_id,
            objective=validated.objective,
            status="empty",
            provider="deterministic",
            brief=_fallback_brief(
                request,
                limit=_finding_limit(target_findings),
            ),
            admitted_evidence_ids=[],
            metadata=_metadata(external_call=False),
        )

    selected_provider = provider
    selected_model_id = model_id
    error = ""
    if selected_provider is None:
        selected_model_id = await _resolve_model_id(model_id)
        if selected_model_id:
            try:
                selected_provider = LLMResearchSynthesisProvider(
                    selected_model_id
                )
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__

    if selected_provider is not None:
        try:
            brief = _restrict_brief(
                await selected_provider.synthesize(request),
                allowed_source_ids=set(evidence_ids),
                evidence_by_id={
                    item.source_id: (
                        f"{item.source_title} {item.claim}"
                    )
                    for item in request.evidence
                },
                language=request.language,
            )
            brief = _ensure_target_findings(
                brief,
                request=request,
                target_findings=target_findings,
            )
            if brief.findings:
                return ResearchSynthesisResult(
                    run_id=validated.run_id,
                    objective=validated.objective,
                    status="synthesized",
                    provider=str(
                        getattr(selected_provider, "name", "configured_provider")
                    ),
                    model_id=str(
                        getattr(selected_provider, "model_id", selected_model_id)
                    ),
                    brief=brief,
                    admitted_evidence_ids=evidence_ids,
                    metadata=_metadata(external_call=True),
                )
            error = "synthesis returned no source-backed findings"
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__

    return ResearchSynthesisResult(
        run_id=validated.run_id,
        objective=validated.objective,
        status="fallback",
        provider="deterministic",
        model_id=selected_model_id,
        brief=_fallback_brief(
            request,
            limit=_finding_limit(target_findings),
        ),
        admitted_evidence_ids=evidence_ids,
        error=error[:500],
        metadata=_metadata(external_call=selected_provider is not None),
    )


def synthesize_research_report_deterministic(
    report: ResearchReport | dict[str, Any],
    *,
    target_findings: int = 0,
) -> ResearchSynthesisResult:
    validated = ResearchReport.model_validate(report)
    request = _request_from_report(validated)
    evidence_ids = [item.source_id for item in request.evidence]
    return ResearchSynthesisResult(
        run_id=validated.run_id,
        objective=validated.objective,
        status="fallback" if evidence_ids else "empty",
        provider="deterministic",
        brief=_fallback_brief(
            request,
            limit=_finding_limit(target_findings),
        ),
        admitted_evidence_ids=evidence_ids,
        metadata=_metadata(external_call=False),
    )


def _request_from_report(report: ResearchReport) -> ResearchSynthesisRequest:
    sources = {str(item.evidence_id): item for item in report.sources}
    evidence: list[SynthesisEvidence] = []
    seen: set[str] = set()
    for decision in report.verified_claims:
        if not decision.publishable:
            continue
        for evidence_id in decision.evidence_ids:
            source_id = str(evidence_id)
            source = sources.get(source_id)
            if source is None or source_id in seen:
                continue
            seen.add(source_id)
            evidence.append(
                SynthesisEvidence(
                    source_id=source_id,
                    claim=decision.claim,
                    source_title=source.source_title,
                    source_url=source.source_url,
                    published_date=source.published_date,
                    quality=decision.quality,
                    relevance=source.relevance,
                    corroborated=decision.corroborated,
                )
            )
    return ResearchSynthesisRequest(
        objective=report.objective,
        language=_language(report.objective),
        evidence=evidence[:8],
        limitations=_limitations(report),
    )


def _fallback_brief(
    request: ResearchSynthesisRequest,
    *,
    limit: int = 5,
) -> ResearchBrief:
    findings = [
        ResearchFinding(
            title=_bounded(item.source_title or "来源结论", 100),
            summary=_bounded(item.claim, 240),
            why_it_matters="",
            caveat=_fallback_caveat(item, language=request.language),
            source_ids=[item.source_id],
        )
        for item in request.evidence[:limit]
    ]
    overview = (
        "以下内容仅整理自通过可读性、相关性和来源检查的证据。"
        if request.language == "zh-CN"
        else "The findings below use only evidence that passed publication checks."
    )
    if not findings:
        overview = (
            "现有检索结果没有形成可发布的证据结论。"
            if request.language == "zh-CN"
            else "The available search results produced no publishable evidence."
        )
    return ResearchBrief(
        language=request.language,
        overview=overview,
        findings=findings,
        limitations=request.limitations[:5],
    )


def _ensure_target_findings(
    brief: ResearchBrief,
    *,
    request: ResearchSynthesisRequest,
    target_findings: int,
) -> ResearchBrief:
    target = _finding_limit(target_findings)
    if target_findings <= 0 or len(brief.findings) >= target:
        return brief
    findings = list(brief.findings)
    used_source_ids = {
        source_id
        for finding in findings
        for source_id in finding.source_ids
    }
    fallback = _fallback_brief(request, limit=5)
    for finding in fallback.findings:
        if any(source_id in used_source_ids for source_id in finding.source_ids):
            continue
        findings.append(finding)
        used_source_ids.update(finding.source_ids)
        if len(findings) >= target:
            break
    return brief.model_copy(update={"findings": findings[:target]})


def _finding_limit(value: int) -> int:
    return max(1, min(int(value or 5), 5))


def _fallback_caveat(item: SynthesisEvidence, *, language: str) -> str:
    values: list[str] = []
    if item.published_date:
        values.append(
            f"来源标注日期：{item.published_date}。"
            if language == "zh-CN"
            else f"Source date: {item.published_date}."
        )
    if not item.corroborated:
        values.append(
            "该结论目前仅由单一来源支持。"
            if language == "zh-CN"
            else "This finding currently has one supporting source."
        )
    return _bounded(" ".join(values), 180)


def _restrict_brief(
    brief: ResearchBrief,
    *,
    allowed_source_ids: set[str],
    evidence_by_id: dict[str, str],
    language: str,
) -> ResearchBrief:
    findings: list[ResearchFinding] = []
    for item in brief.findings[:5]:
        source_ids = [
            source_id
            for source_id in item.source_ids
            if source_id in allowed_source_ids
        ][:4]
        if not source_ids:
            continue
        if not _supported_by_source_text(
            item.title,
            item.summary,
            source_ids=source_ids,
            evidence_by_id=evidence_by_id,
        ):
            continue
        findings.append(item.model_copy(update={"source_ids": source_ids}))
    return brief.model_copy(
        update={
            "language": language,
            "findings": findings,
            "limitations": brief.limitations[:5],
        }
    )


def _limitations(report: ResearchReport) -> list[str]:
    zh = _language(report.objective) == "zh-CN"
    values: list[str] = []
    if report.uncertain_claims:
        values.append(
            f"{len(report.uncertain_claims)} 条证据因强度不足未作为结论。"
            if zh
            else (
                f"{len(report.uncertain_claims)} uncertain claim(s) lacked "
                "enough evidence strength."
            )
        )
    if report.rejected_claims:
        values.append(
            f"{len(report.rejected_claims)} 条候选证据未通过发布质量检查。"
            if zh
            else f"{len(report.rejected_claims)} candidates failed publication checks."
        )
    values.extend(
        (f"待补证据：{gap}" if zh else f"Open gap: {gap}")
        for gap in report.gaps[:3]
    )
    if report.memory_context.constraints:
        values.append(
            "个人记忆只用于偏好背景，不作为事实证据。"
            if zh
            else "Personal memory was used only as context, not evidence."
        )
    if not report.verified_claims:
        objective = report.objective.lower()
        if re.search(r"最新|近期|最近|新书|\blatest\b|\brecent\b", objective):
            values.append(
                "现有来源缺少可核验的出版或发布时间。"
                if zh
                else "The current sources lack verifiable publication dates."
            )
        if re.search(
            r"好评|高分|口碑|评分|评价|\breview|\brating|\bbest\b",
            objective,
        ):
            values.append(
                "现有来源缺少可核验的评分、评论或榜单依据。"
                if zh
                else "The current sources lack verifiable rating or review evidence."
            )
        if not values:
            values.append(
                "现有来源未通过相关性和可发布性检查。"
                if zh
                else "The available sources did not pass relevance and publication checks."
            )
    return values[:5]


async def _resolve_model_id(requested: str) -> str:
    if requested:
        return requested
    manager = get_model_manager()
    model_id = manager.default_llm_id or manager.get_first_active_llm_id()
    if model_id:
        return model_id
    if not getattr(manager, "_initialized", False):
        try:
            await manager.refresh()
        except Exception:
            return ""
    return manager.default_llm_id or manager.get_first_active_llm_id() or ""


def _metadata(*, external_call: bool) -> dict[str, Any]:
    return {
        "writes_research_state": False,
        "writes_evidence": False,
        "writes_long_term_memory": False,
        "writes_recommendation_events": False,
        "external_call": external_call,
        "input_scope": "admitted_evidence_only",
    }


def _language(text: str) -> str:
    return "zh-CN" if re.search(r"[\u4e00-\u9fff]", text) else "en"


def _bounded(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _supported_by_source_text(
    title: str,
    summary: str,
    *,
    source_ids: list[str],
    evidence_by_id: dict[str, str],
) -> bool:
    source_text = " ".join(
        evidence_by_id.get(source_id, "")
        for source_id in source_ids
    ).lower()
    output_text = f"{title} {summary}".lower()
    output_terms = _content_terms(output_text)
    source_terms = _content_terms(source_text)
    return bool(output_terms.intersection(source_terms))


def _content_terms(text: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9]{4,}", text))
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        terms.update(
            segment[index : index + 2]
            for index in range(max(0, len(segment) - 1))
        )
    return terms
