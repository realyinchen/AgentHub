"""
Vectorstore Retriever Tool

Provides a LangGraph tool for searching the vector store.
Uses the abstract VectorstoreInterface so the tool is backend-agnostic.
"""

import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.database.factory import get_vectorstore

logger = logging.getLogger(__name__)


class VectorStoreSearchInput(BaseModel):
    """Input schema for vector store search tool."""

    query: str = Field(description="The search query text")
    collection_name: str = Field(
        default="documents",
        description="The name of the collection to search in",
    )
    limit: int = Field(
        default=5,
        description="Maximum number of results to return",
    )


@tool(args_schema=VectorStoreSearchInput)
async def vectorstore_search(
    query: str,
    collection_name: str = "documents",
    limit: int = 5,
) -> str:
    """
    Search the vector store for relevant documents.

    This tool searches the configured vector store backend (Qdrant/sqlite-vec)
    for documents similar to the query text.
    """
    try:
        vectorstore = get_vectorstore()

        # Use the vectorstore's text search which handles embedding internally
        results = await vectorstore.search(
            collection_name=collection_name,
            query_text=query,
            limit=limit,
        )

        if not results:
            return "No relevant documents found."

        # Format results
        formatted = []
        for i, result in enumerate(results, 1):
            score = result.get("score", 0)
            payload = result.get("payload", {})
            content = payload.get("content", payload.get("text", str(payload)))
            source = payload.get(
                "source", payload.get("metadata", {}).get("source", "unknown")
            )
            formatted.append(f"[{i}] (Score: {score:.4f}, Source: {source})\n{content}")

        return "\n\n---\n\n".join(formatted)

    except Exception as e:
        logger.error(f"Vectorstore search error: {e}")
        return f"Error searching vector store: {str(e)}"
