from typing import List
from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_qdrant import QdrantVectorStore
from langchain_litellm import LiteLLMEmbeddings

from app.core.config import settings
from app.database import qdrant_manager


def _get_vectorstore(collection_name: str) -> QdrantVectorStore:
    client = qdrant_manager.get_client()
    # Get embedding model configuration from environment variables
    model_name = settings.EMBEDDING_MODEL_NAME
    if not model_name:
        raise ValueError("EMBEDDING_MODEL_NAME is not configured in .env")
    api_key = (
        settings.EMBEDDING_API_KEY.get_secret_value()
        if settings.EMBEDDING_API_KEY
        else None
    )
    embeddings = LiteLLMEmbeddings(model=model_name, api_key=api_key)
    return QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )


@tool
def retrieve_from_vectorstore(
    collection_name: str, query: str
) -> tuple[str, List[Document]]:
    """Retrieve information to help answer a query.

    This tool searches a vector store collection for documents similar to the query.
    Use this when you need to retrieve relevant information from a knowledge base.

    Args:
        collection_name: Name of the vector store collection to search.
        query: The search query to find relevant documents.

    Returns:
        A tuple containing:
        - serialized_content: Formatted string with retrieved documents
        - documents: List of retrieved Document objects

    Examples:
        >>> retrieve_from_vectorstore.invoke({"collection_name": "docs", "query": "What is AI?"})
    """
    vectorstore = _get_vectorstore(collection_name)
    retrieved_docs = vectorstore.similarity_search(query, k=2)
    serialized = "\n\n".join(
        (f"Source: {doc.metadata}\nContent: {doc.page_content}")
        for doc in retrieved_docs
    )
    return serialized, retrieved_docs
