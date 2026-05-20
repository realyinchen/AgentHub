"""Model middleware for AgentHub.

Provides dynamic model selection using LangChain v1's @wrap_model_call.

This enables:
- Per-request model switching (e.g., based on user preferences)
- Thinking mode toggle
- Fallback model configuration
"""

from app.agents.middleware.model.dynamic import dynamic_model

__all__ = [
    "dynamic_model",
]
