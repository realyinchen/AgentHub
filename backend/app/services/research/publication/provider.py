from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from app.services.research.publication.contracts import ResearchBrief


class SynthesisEvidence(BaseModel):
    source_id: str
    claim: str
    source_title: str
    source_url: str
    published_date: str = ""
    quality: str
    relevance: int
    corroborated: bool = False


class ResearchSynthesisRequest(BaseModel):
    objective: str
    language: str
    evidence: list[SynthesisEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ResearchSynthesisProvider(Protocol):
    name: str
    model_id: str

    async def synthesize(
        self,
        request: ResearchSynthesisRequest,
    ) -> ResearchBrief: ...
