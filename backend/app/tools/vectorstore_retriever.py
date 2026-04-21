from typing import List
from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_qdrant import QdrantVectorStore
from langchain_litellm import LiteLLMEmbeddings

from app.database import qdrant_manager
from app.core.model_manager import ModelManager


async def _aget_vectorstore(collection_name: str) -> QdrantVectorStore:
    """Async get vectorstore with embedding model from database."""
    client = qdrant_manager.get_client()
    # Get embedding model configuration from ModelManager (database)
    model_name, api_key = await ModelManager.get_embedding_model_instance()
    embeddings = LiteLLMEmbeddings(model=model_name, api_key=api_key)
    return QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embeddings,
    )


def _get_vectorstore(collection_name: str) -> QdrantVectorStore:
    """Sync wrapper for _aget_vectorstore.

    Note: This function should be called from sync contexts only.
    In async contexts, use _aget_vectorstore directly.
    """
    import asyncio

    # Try to get the running loop
    try:
        _ = asyncio.get_running_loop()
        # We have a running loop but this is a sync function
        # This should not happen in normal operation since tools are run
        # in async contexts through LangGraph. If it does happen,
        # we raise an error to avoid blocking issues.
        raise RuntimeError(
            "_get_vectorstore() called from async context. "
            "Use _aget_vectorstore() instead in async code."
        )
    except RuntimeError as e:
        if "no running event loop" in str(e):
            # No running loop, safe to use asyncio.run
            return asyncio.run(_aget_vectorstore(collection_name))
        raise


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
