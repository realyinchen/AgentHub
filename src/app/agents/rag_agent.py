from langchain.agents import create_agent
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from app.core.models import llm, embedding_model


client = QdrantClient(host="localhost", port=6333)

vectorstore = QdrantVectorStore(
    client=client,
    collection_name="agentic_rag_survey",
    embedding=embedding_model,
)


@tool(response_format="content_and_artifact")
def retrieve_context(query: str):
    """Retrieve information to help answer a query."""
    retrieved_docs = vectorstore.similarity_search(query, k=2)
    serialized = "\n\n".join(
        (f"Source: {doc.metadata}\nContent: {doc.page_content}")
        for doc in retrieved_docs
    )
    return serialized, retrieved_docs


tools = [retrieve_context]
prompt = (
    "You have access to a tool that retrieves context from a paper. "
    "Use the tool to help answer user queries."
)

rag_agent = create_agent(llm, tools, system_prompt=prompt, checkpointer=InMemorySaver())
