from langchain_tavily import TavilySearch
from langchain_core.tools import BaseTool


def create_web_search(
    max_results: int = 3,
    include_answer: bool = True,
    include_raw_content: bool = False,
    search_depth: str = "basic",
    **kwargs,
) -> BaseTool:
    """Create a web search tool instance with customizable configuration.

    This factory function creates a TavilySearch tool for performing web searches.
    Use this when you need different search configurations for different use cases.

    Args:
        max_results: Maximum number of search results to return. Defaults to 3.
        include_answer: Whether to include a direct summary answer. Defaults to True.
        include_raw_content: Whether to include raw HTML content. Defaults to False.
        search_depth: Search depth, either "basic" or "advanced". Defaults to "basic".
        **kwargs: Additional arguments passed to TavilySearch.

    Returns:
        A configured TavilySearch tool instance.

    Examples:
        >>> search = create_web_search(max_results=5)
        >>> search = create_web_search(search_depth="advanced")
    """
    return TavilySearch(
        max_results=max_results,
        include_answer=include_answer,
        include_raw_content=include_raw_content,
        search_depth=search_depth,
        **kwargs,
    )
