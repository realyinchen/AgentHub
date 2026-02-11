# type: ignore
from langgraph.graph import END, StateGraph

from .chains import answer_grader, hallucination_grader, question_router
from .consts import (
    COORDINATOR,
    REPORTER,
    RETRIEVE,
    GRADE_DOCUMENTS,
    WEBSEARCH,
    RAG_ANSWER,
    DIRECT_ANSWER,
)
from .nodes import (
    rag_answer,
    direct_answer,
    coordinator,
    grade_documents,
    reporter,
    retrieve,
    web_search,
)
from .state import GraphState


def decide_to_generate(state: GraphState):
    """Determine whether to proceed with generation or search the web based on document relevance scores."""

    return WEBSEARCH if state["web_search"] else RAG_ANSWER


def grade_generation_grounded_in_documents_and_question(state):
    """Grade answer quality and groundedness."""

    question = state["question"]
    documents = "\n\n".join([document.page_content for document in state["documents"]])
    generation = state["generation"]

    # Check if grounded
    hallucination_grader_score = hallucination_grader.invoke(
        {"documents": documents, "generation": generation}
    )

    if hallucination_grader_score.binary_score:
        # Check if useful
        answer_grader_score = answer_grader.invoke(
            {"question": question, "generation": generation}
        )
        if answer_grader_score.binary_score:
            return "useful"
        else:
            return "not useful"
    else:
        return "not supported"


def route_question(state: GraphState) -> str:
    """Route question to vectorstore or web search or direct answer."""

    source = question_router.invoke({"question": state["question"]})

    if source.datasource == "vector_store":
        return RETRIEVE
    if source.datasource == "web_search":
        return WEBSEARCH
    if source.datasource == "direct_answer":
        return DIRECT_ANSWER


# Build workflow
workflow = StateGraph(GraphState)
workflow.add_node(COORDINATOR, coordinator)
workflow.add_node(RETRIEVE, retrieve)
workflow.add_node(GRADE_DOCUMENTS, grade_documents)
workflow.add_node(WEBSEARCH, web_search)
workflow.add_node(RAG_ANSWER, rag_answer)
workflow.add_node(DIRECT_ANSWER, direct_answer)
workflow.add_node(REPORTER, reporter)

workflow.set_entry_point(COORDINATOR)
workflow.add_conditional_edges(
    COORDINATOR,
    route_question,
    {WEBSEARCH: WEBSEARCH, RETRIEVE: RETRIEVE, DIRECT_ANSWER: DIRECT_ANSWER},
)
workflow.add_edge(RETRIEVE, GRADE_DOCUMENTS)
workflow.add_conditional_edges(
    GRADE_DOCUMENTS,
    decide_to_generate,
    {WEBSEARCH: WEBSEARCH, RAG_ANSWER: RAG_ANSWER},
)
workflow.add_conditional_edges(
    RAG_ANSWER,
    grade_generation_grounded_in_documents_and_question,
    {"not supported": RAG_ANSWER, "useful": REPORTER, "not useful": WEBSEARCH},
)
workflow.add_edge(WEBSEARCH, RAG_ANSWER)
workflow.add_edge(DIRECT_ANSWER, END)
workflow.add_edge(REPORTER, END)

app = workflow.compile()
