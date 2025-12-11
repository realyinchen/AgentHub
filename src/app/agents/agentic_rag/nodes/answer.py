from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from typing import Any, Dict

from app.core.models import llm
from ..prompts import RAG_PROMPT, DIRECT_ANSWER_PROMPT
from ..state import GraphState


rag_prompt = ChatPromptTemplate.from_messages(
    [("system", RAG_PROMPT), MessagesPlaceholder(variable_name="messages")]
)
rag_answer_chain = rag_prompt | llm

direct_answer_prompt = ChatPromptTemplate.from_messages(
    [("system", DIRECT_ANSWER_PROMPT), MessagesPlaceholder(variable_name="messages")]
)
direct_answer_chain = direct_answer_prompt | llm


def rag_answer(state: GraphState) -> Dict[str, Any]:
    """Generate answer using documents and question."""

    question = state["question"]
    documents = state["documents"]
    generation = rag_answer_chain.invoke(
        {"context": documents, "question": question, "messages": state["messages"]}
    )
    return {"documents": documents, "question": question, "generation": generation}


def direct_answer(state: GraphState) -> Dict[str, Any]:
    """Generate answer using LLM own knowledge."""

    question = state["question"]
    generation = direct_answer_chain.invoke(
        {"question": question, "messages": state["messages"]}
    )
    return {"messages": [generation]}
