from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.models import llm
from ..prompts import ANSWER_GRADER_PROMPT


class GradeAnswer(BaseModel):
    """Binary score indicating whether a generated answer adequately addresses the user's question."""

    binary_score: bool = Field(
        description="Answer addresses the question, 'yes' or 'no'"
    )


structured_llm_answer_grader = llm.with_structured_output(GradeAnswer)


answer_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", ANSWER_GRADER_PROMPT),
        ("human", "User question: \n\n {question} \n\n LLM generation: {generation}"),
    ]
)

answer_grader = answer_prompt | structured_llm_answer_grader
