from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.services.research.loop.contracts import (
    ResearchRoundSources,
    ResearchSearchTask,
)
from app.services.research.loop.source_projection import (
    project_research_search_output,
)


ResearchSearchExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def acquire_research_round(
    *,
    task: ResearchSearchTask | dict[str, Any],
    executor: ResearchSearchExecutor,
) -> ResearchRoundSources:
    """Execute one explicit search task and project its provider response."""

    search_task = ResearchSearchTask.model_validate(task)
    if not search_task.should_search:
        return project_research_search_output(
            task=search_task,
            provider_output={"status": "completed"},
        )
    provider_output = await executor(search_task.tool_arguments())
    return project_research_search_output(
        task=search_task,
        provider_output=provider_output,
    )
