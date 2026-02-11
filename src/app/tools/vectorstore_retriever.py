from typing import List
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore

from app.core.models import embedding_model
from app.database import qdrant_manager


def _get_vectorstore(collection_name: str) -> QdrantVectorStore:
    client = qdrant_manager.get_client()
    return QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=embedding_model,
    )


def retrieve_from_vectorstore(
    collection_name: str, query: str
) -> tuple[str, List[Document]]:
    """Retrieve information to help answer a query.

    Args:
        collection_name (str): Collection name of a vector store.
        query (str): User query.

    Returns:
        (serialized_content: str, documents: List[Document])
    """
    vectorstore = _get_vectorstore(collection_name)
    retrieved_docs = vectorstore.similarity_search(query, k=2)
    serialized = "\n\n".join(
        (f"Source: {doc.metadata}\nContent: {doc.page_content}")
        for doc in retrieved_docs
    )
    return serialized, retrieved_docs
