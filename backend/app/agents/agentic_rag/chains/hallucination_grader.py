from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field


from app.core.models import llm
from ..prompts import HALLUCINATION_GRADER_PROMPT


class GradeHallucinations(BaseModel):
    """Binary score for hallucination present in generation answer."""

    binary_score: bool = Field(
        description="Answer is grounded in the facts, 'yes' or 'no'"
    )


structured_llm_hallucinations_grader = llm.with_structured_output(GradeHallucinations)


hallucination_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", HALLUCINATION_GRADER_PROMPT),
        ("human", "Set of facts: \n\n {documents} \n\n LLM generation: {generation}"),
    ]
)

hallucination_grader = hallucination_prompt | structured_llm_hallucinations_grader
