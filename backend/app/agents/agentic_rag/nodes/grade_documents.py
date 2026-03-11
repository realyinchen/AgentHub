from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from typing import Any, Dict

from app.core.models import llm
from ..prompts import RETRIEVAL_GRADER_PROMPT
from ..state import GraphState


class GradeDocuments(BaseModel):
    """Binary score for relevance check on retrieved documents."""

    binary_score: str = Field(
        description="Documents are relevant to the question, 'yes' or 'no'"
    )


structured_llm_document_grader = llm.with_structured_output(GradeDocuments)

grade_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", RETRIEVAL_GRADER_PROMPT),
        ("human", "Retrieved document: \n\n {document} \n\n User question: {question}"),
    ]
)

retrieval_grader = grade_prompt | structured_llm_document_grader


def grade_documents(state: GraphState) -> Dict[str, Any]:
    """
    Determines whether the retrieved documents are relevant to the question
    If any document is not relevant, we will set a flag to run web search

    Args:
        state (dict): The current graph state

    Returns:
        state (dict): Filtered out irrelevant documents and updated web_search state
    """

    question = state["question"]
    documents = state["documents"]

    filtered_docs = []
    web_search = False
    for document in documents:
        score = retrieval_grader.invoke(
            {"question": question, "document": document.page_content}
        )
        grade = score.binary_score  # type: ignore
        if grade.lower() == "yes":
            filtered_docs.append(document)
        else:
            web_search = True
            continue
    return {"documents": filtered_docs, "question": question, "web_search": web_search}
