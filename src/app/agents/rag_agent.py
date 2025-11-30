from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.core.models import llm
from app.tools import retrieve_from_vectorstore


@tool(response_format="content_and_artifact")
def retrieve_context(query: str):
    """Retrieve relevant context from the knowledge base to answer the user's question."""
    return retrieve_from_vectorstore(collection_name="agentic_rag_survey", query=query)


tools = [retrieve_context]
prompt = (
    "You have access to a tool that retrieves context from a paper. "
    "Use the tool to help answer user queries."
)

rag_agent = create_agent(llm, tools, system_prompt=prompt, checkpointer=InMemorySaver())
