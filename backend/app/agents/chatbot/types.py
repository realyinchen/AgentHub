"""Chatbot-specific runtime context types.

Architecture
------------
``AgentRuntimeContext`` is the shared base for all agents — defined in
``app.agents.types`` (framework layer).  ``ChatbotContext`` extends it
with chatbot-specific fields.

To create a context for another agent, follow the same pattern::

    from app.agents.types import AgentRuntimeContext

    @dataclass
    class RAGContext(AgentRuntimeContext):
        collection_id: str = ""
        top_k: int = 5

Then pass it via ``AgentSpec(context_schema=RAGContext)``.
"""

from dataclasses import dataclass

from app.agents.types import AgentRuntimeContext  # noqa: F401  — re-exported


@dataclass
class ChatbotContext(AgentRuntimeContext):
    """Chatbot Agent runtime context — inherits base + adds file-QA support.

    This subclass demonstrates the canonical extension pattern:
    define a dataclass that inherits from ``AgentRuntimeContext``, add
    only the agent-specific fields, and pass it via ``AgentSpec``.

    For other agents, follow the same pattern:

        @dataclass
        class RAGContext(AgentRuntimeContext):
            collection_id: str = ""
            top_k: int = 5

        @dataclass
        class ResearchContext(AgentRuntimeContext):
            depth: int = 3
            max_steps: int = 10

    Middleware accessing only base-class fields (dynamic_model,
    dynamic_prompt) remains compatible with all subclasses.
    """

    file: str = ""  # File path / URL for file-based Q&A scenarios
