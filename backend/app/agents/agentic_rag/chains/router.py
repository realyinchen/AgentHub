from typing import Literal
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.models import llm
from ..prompts import ROUTER_PROMPT


class RouteQuery(BaseModel):
    """Route a user query to the most relevant destination."""

    datasource: Literal["vector_store", "web_search", "direct_answer"] = Field(
        ...,
        description=(
            "Choose 'vector_store' for questions about Agentic RAG or RAG architectures; "
            "'web_search' for questions requiring up-to-date or external information; "
            "'direct_answer' for greetings, simple factual questions (e.g., capital of China), "
            "or anything the LLM can confidently answer without retrieval."
        ),
    )


structured_llm_router = llm.with_structured_output(RouteQuery)


route_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", ROUTER_PROMPT),
        ("human", "{question}"),
    ]
)

question_router = route_prompt | structured_llm_router
