from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.infra.llm import get_llm
from app.services.research.publication.contracts import ResearchBrief
from app.services.research.publication.provider import ResearchSynthesisRequest


SYNTHESIS_TIMEOUT_SECONDS = 45


class LLMResearchSynthesisProvider:
    """Schema-validated prose synthesis over admitted evidence only."""

    name = "runtime_llm"

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    async def synthesize(
        self,
        request: ResearchSynthesisRequest,
    ) -> ResearchBrief:
        model = get_llm(self.model_id)
        prompt = _prompt(request)
        async with asyncio.timeout(SYNTHESIS_TIMEOUT_SECONDS):
            response = await model.ainvoke(prompt)
        return ResearchBrief.model_validate(_json_payload(_message_text(response)))


def _prompt(request: ResearchSynthesisRequest) -> str:
    schema = ResearchBrief.model_json_schema()
    evidence = [item.model_dump(mode="json") for item in request.evidence]
    language_rule = (
        "Write every user-facing field in Simplified Chinese."
        if request.language == "zh-CN"
        else "Write every user-facing field in English."
    )
    return (
        "You synthesize a concise research brief. You cannot call tools and "
        "must use only the admitted evidence supplied below. "
        f"{language_rule}\n"
        "Return one JSON object only, with no Markdown fences or explanation. "
        "It must validate against the supplied JSON Schema. Use at most five "
        "findings. Every finding must cite one or more exact source_id values "
        "from the evidence. Do not invent titles, ratings, publication dates, "
        "consensus, or facts. Do not copy long source passages. If one source "
        "only mentions an item, describe it as that source's statement rather "
        "than independent consensus. Preserve uncertainty in caveat.\n\n"
        f"Objective: {request.objective}\n"
        f"Known limitations: {json.dumps(request.limitations, ensure_ascii=False)}\n"
        f"Admitted evidence: {json.dumps(evidence, ensure_ascii=False)}\n"
        f"JSON Schema: {json.dumps(schema, ensure_ascii=False)}"
    )


def _message_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()
    return str(content or "").strip()


def _json_payload(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("research synthesis must return a JSON object")
    return payload
