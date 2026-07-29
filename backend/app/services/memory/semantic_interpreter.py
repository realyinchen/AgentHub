from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.memory.contracts import (
    USER_STATE_CATEGORIES,
    normalize_memory_value,
    validate_memory_token,
)


_INTERPRETER_TIMEOUT_SECONDS = 60


class UserStateOrganization(BaseModel):
    """Semantic proposal produced from one already-resolved user statement."""

    category: str
    state_key: str = ""
    summary: str
    state_value: dict[str, Any] = Field(default_factory=dict)
    relation: dict[str, Any] = Field(default_factory=dict)
    use_when: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    needs_confirmation: bool = False
    confirmation_question: str = ""
    ttl_hours: int | None = Field(default=None, ge=1, le=24 * 365)

    @field_validator("category", mode="before")
    @classmethod
    def validate_category(cls, value: Any) -> str:
        return validate_memory_token("category", value, USER_STATE_CATEGORIES)

    @field_validator("state_key", "summary", "confirmation_question", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return normalize_memory_value(value)

    @field_validator("use_when", mode="before")
    @classmethod
    def clean_use_when(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = normalize_memory_value(item)
            if text and text not in result:
                result.append(text[:120])
        return result[:12]

    @field_validator("state_value", "relation", mode="before")
    @classmethod
    def normalize_optional_object(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}


async def interpret_user_state(
    resolved_statement: str,
    *,
    requested_model_id: str = "",
) -> UserStateOrganization:
    """Turn a resolved statement into a typed proposal without persistence."""

    prompt = _build_interpreter_prompt(resolved_statement)
    model_errors: list[str] = []
    models: list[tuple[str, Any]] = []
    try:
        from app.infra.llm import get_llm
        from app.infra.llm.manager import get_model_manager

        if requested_model_id:
            models.append(("turn_model", get_llm(requested_model_id)))
        manager = get_model_manager()
        model_id = manager.default_llm_id or manager.get_first_active_llm_id()
        if not model_id and not getattr(manager, "_initialized", False):
            await manager.refresh()
            model_id = manager.default_llm_id or manager.get_first_active_llm_id()
        if model_id and model_id != requested_model_id:
            models.append(("runtime_default", get_llm(model_id)))
    except Exception as exc:
        model_errors.append(f"runtime_default: {exc}")
    try:
        from app.infra.llm import get_system_llm

        models.append(("system", get_system_llm()))
    except Exception as exc:
        model_errors.append(f"system: {exc}")

    for model_name, model in models:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(model.invoke, prompt),
                timeout=_INTERPRETER_TIMEOUT_SECONDS,
            )
            payload = _extract_json_object(_message_text(response))
            return UserStateOrganization.model_validate(payload)
        except Exception as exc:
            model_errors.append(f"{model_name}: {exc}")
    raise RuntimeError("; ".join(model_errors) or "no memory interpreter model available")


def _build_interpreter_prompt(resolved_statement: str) -> str:
    return f"""You organize user-authored state for a personal AI assistant.
Memory is user state, not general knowledge, a chat summary, or a knowledge graph.
Classify this exact, already-resolved user statement without inventing facts.

Categories:
- profile: identity, stable routine, role, personal background
- preference: likes, dislikes, habits with preference meaning, constraints
- relation: an open-vocabulary relation between the user and any person, pet, object, place, project, account, or other entity
- feedback: explicit outcome or interaction feedback, including read/bought/rejected/completed
- short_term: temporary mood, plan, deadline, location, or transient state

Return one JSON object only:
{{
  "category": "profile|preference|relation|feedback|short_term",
  "state_key": "stable.open.vocabulary.key",
  "summary": "concise statement in the user's language",
  "state_value": {{"open": "structured values"}},
  "relation": {{"subject": "user", "predicate": "open vocabulary", "object": "...", "object_type": "..."}},
  "use_when": ["queries or situations where this state helps"],
  "confidence": 0.0,
  "needs_confirmation": false,
  "confirmation_question": "question in the user's language when ambiguous",
  "ttl_hours": null
}}

Rules:
- The resolved statement is authoritative. Your structure is only an interpretation.
- Keep relation predicates and entity types open-vocabulary; do not limit them to pets or books.
- Set needs_confirmation=true for inferred details or remaining ambiguity.
- For short_term choose a practical ttl_hours. Other categories use null.
- use_when must include likely recall wording and task contexts.

Resolved user statement:
{resolved_statement}
"""


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text") or item.get("content") or "")
            if isinstance(item, dict)
            else str(item or "")
            for item in content
        )
    return str(content or "")


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("memory interpreter did not return JSON")
        payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("memory interpreter returned a non-object payload")
    return payload
