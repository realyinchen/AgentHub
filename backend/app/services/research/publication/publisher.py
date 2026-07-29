from __future__ import annotations

from typing import Any

from app.services.research.evidence_quality import classify_source
from app.services.research.publication.contracts import (
    PublishedResearchAnswer,
    PublishedResearchSource,
    ResearchSynthesisResult,
)
from app.services.research.report import ResearchReport


def publish_research_answer(
    report: ResearchReport | dict[str, Any],
    synthesis: ResearchSynthesisResult | dict[str, Any],
) -> PublishedResearchAnswer:
    """Render localized Markdown from a validated ResearchBrief."""

    validated_report = ResearchReport.model_validate(report)
    validated_synthesis = ResearchSynthesisResult.model_validate(synthesis)
    if validated_synthesis.run_id != validated_report.run_id:
        raise ValueError("research synthesis does not belong to the report")

    sources_by_id = {
        str(source.evidence_id): source
        for source in validated_report.sources
    }
    cited_ids = list(
        dict.fromkeys(
            source_id
            for finding in validated_synthesis.brief.findings
            for source_id in finding.source_ids
            if source_id in sources_by_id
        )
    )
    citation_number = {
        source_id: index
        for index, source_id in enumerate(cited_ids, start=1)
    }
    published_sources = [
        PublishedResearchSource(
            source_id=source_id,
            title=sources_by_id[source_id].source_title,
            url=sources_by_id[source_id].source_url,
            published_date=sources_by_id[source_id].published_date,
            source_class=classify_source(sources_by_id[source_id].source_url),
        )
        for source_id in cited_ids
    ]
    language = validated_synthesis.brief.language
    answer = _markdown(
        validated_synthesis,
        citation_number=citation_number,
        sources=published_sources,
    )
    if validated_synthesis.brief.findings and validated_report.verification.ready_for_final_answer:
        status = "verified"
    elif validated_synthesis.brief.findings:
        status = "partial_with_limitations"
    else:
        status = "blocked_no_publishable_evidence"
    return PublishedResearchAnswer(
        run_id=validated_report.run_id,
        objective=validated_report.objective,
        answer_status=status,
        language=language,
        answer=answer,
        brief=validated_synthesis.brief,
        sources=published_sources,
        limitations=validated_synthesis.brief.limitations,
        metadata={
            "synthesis_contract_version": validated_synthesis.contract_version,
            "synthesis_status": validated_synthesis.status,
            "synthesis_provider": validated_synthesis.provider,
            "source_count": len(published_sources),
            "finding_count": len(validated_synthesis.brief.findings),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
        },
    )


def _markdown(
    synthesis: ResearchSynthesisResult,
    *,
    citation_number: dict[str, int],
    sources: list[PublishedResearchSource],
) -> str:
    brief = synthesis.brief
    zh = brief.language == "zh-CN"
    lines = [f"## {'研究结论' if zh else 'Research conclusion'}"]
    lines.append(
        brief.overview
        or (
            "现有证据不足以形成可发布结论。"
            if zh
            else "The current evidence is insufficient for a publishable conclusion."
        )
    )
    if brief.findings:
        lines.extend(["", f"## {'主要发现' if zh else 'Key findings'}"])
        for index, finding in enumerate(brief.findings, start=1):
            citations = "".join(
                f" [{citation_number[source_id]}]"
                for source_id in finding.source_ids
                if source_id in citation_number
            )
            lines.extend(
                [
                    "",
                    f"{index}. **{_escape(finding.title)}**",
                    f"   - {finding.summary}{citations}",
                ]
            )
            if finding.why_it_matters:
                label = "价值" if zh else "Why it matters"
                lines.append(f"   - {label}：{finding.why_it_matters}")
            if finding.caveat:
                label = "注意" if zh else "Caveat"
                lines.append(f"   - {label}：{finding.caveat}")
    if sources:
        lines.extend(["", f"## {'来源' if zh else 'Sources'}"])
        for index, source in enumerate(sources, start=1):
            title = _escape(source.title or source.url or f"Source {index}")
            if source.url:
                line = f"{index}. [{title}]({source.url})"
            else:
                line = f"{index}. {title}"
            if source.published_date:
                label = "来源日期" if zh else "Source date"
                line += f"（{label}：{source.published_date}）"
            lines.append(line)
    if brief.limitations:
        lines.extend(["", f"## {'证据限制' if zh else 'Evidence limitations'}"])
        lines.extend(f"- {item}" for item in brief.limitations)
    return "\n".join(lines).strip()


def _escape(text: str) -> str:
    return str(text or "").replace("[", "［").replace("]", "］").strip()
