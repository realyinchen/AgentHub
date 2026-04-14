import logging
import asyncio
from typing import Optional
from litellm.router import Router
from langchain_litellm import ChatLiteLLMRouter
from langchain_core.runnables import Runnable
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
import litellm

from app.database import adb_manager
from app.crud import model as crud
from app.utils.crypto import decrypt_api_key

logger = logging.getLogger(__name__)

# Enable streaming usage globally for litellm
# This ensures token usage is included in streaming responses
litellm.enable_json_schema_validation = True


def build_extra_body(provider: str, thinking_enabled: bool) -> dict:
    """
    Build extra_body parameters based on provider and thinking mode flag.

    DashScope (Alibaba Cloud):
      - enabled: {"enable_thinking": true}
      - disabled: {"enable_thinking": false}

    ZhipuAI (zai):
      - enabled: {"thinking": {"type": "enabled"}}
      - disabled: {"thinking": {"type": "disabled"}}
    """
    provider_lower = provider.lower()
    if provider_lower == "dashscope" or "dashscope" in provider_lower:
        return {"enable_thinking": thinking_enabled}
    elif provider_lower == "zai" or "zhipu" in provider_lower:
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
    else:
        # Other providers return empty by default, can be extended later
        return {}


def bind_tools_with_usage_tracking(llm, tools, extra_body=None):
    """
    Bind tools to LLM with proper stream_options for token usage tracking.

    This ensures that streaming responses include usage_metadata which is
    required for token counting in the conversation.

    IMPORTANT: When using bind_tools(), the stream_options must be passed
    directly to bind_tools() because it creates a new Runnable that doesn't
    inherit from previous bind() calls.

    Args:
        llm: The LLM instance (ChatLiteLLMRouter)
        tools: List of tools to bind
        extra_body: Optional extra_body parameters (e.g., for thinking mode)

    Returns:
        LLM with tools bound and stream_options configured
    """
    kwargs = {"stream_options": {"include_usage": True}}
    if extra_body:
        kwargs["extra_body"] = extra_body
    return llm.bind_tools(tools, **kwargs)  # type: ignore


class ModelManager:
    """
    Dynamic model manager - loads model configuration from database, no service restart needed.

    Features:
    - Caches model configurations and LLM instances for zero-latency access
    - Supports hot-reload: refresh cache without service restart
    - Thread-safe singleton pattern with async lock
    - Dynamically builds extra_body based on provider and thinking mode
    """

    _router: Optional[Router] = None
    _models_cache: dict = {}
    _llm_cache: dict[str, Runnable[LanguageModelInput, AIMessage]] = {}
    _default_llm_id: Optional[str] = None
    _default_vlm_id: Optional[str] = None
    _default_embedding_id: Optional[str] = None
    _lock: asyncio.Lock = asyncio.Lock()
    _initialized: bool = False

    @classmethod
    async def get_router(cls) -> Optional[Router]:
        """Get Router, load from database if not initialized (thread-safe)"""
        if cls._initialized and cls._router is not None:
            return cls._router

        async with cls._lock:
            # Double-check after acquiring lock
            if cls._initialized and cls._router is not None:
                return cls._router
            await cls._refresh_unlocked()
        return cls._router

    @classmethod
    async def refresh(cls):
        """
        Reload model configuration from database.
        Call this method after any model configuration changes.
        Thread-safe with lock protection.
        """
        async with cls._lock:
            await cls._refresh_unlocked()

    @classmethod
    async def _refresh_unlocked(cls):
        """Internal refresh method (must be called with lock held)"""
        logger.info("Refreshing model configuration from database...")

        async with adb_manager.session() as db:
            # Load all active models with API key configured
            models = await crud.get_models_with_api_key(db)
            cls._models_cache = {m.model_id: m for m in models}

            # Cache default model IDs by type
            cls._default_llm_id = None
            cls._default_vlm_id = None
            cls._default_embedding_id = None

            for m in models:
                if getattr(m, "is_default", False):
                    model_type = getattr(m, "model_type", "llm")
                    if model_type == "llm":
                        cls._default_llm_id = str(m.model_id)
                    elif model_type == "vlm":
                        cls._default_vlm_id = str(m.model_id)
                    elif model_type == "embedding":
                        cls._default_embedding_id = str(m.model_id)

            # Build LiteLLM Router model_list
            # Note: extra_body is built dynamically when getting LLM, not here
            model_list = cls._build_litellm_model_list(models)

            if model_list:
                cls._router = Router(model_list=model_list)
                logger.info(f"ModelManager initialized with {len(model_list)} models")
            else:
                cls._router = None
                logger.warning(
                    "No models configured. Please configure models in database."
                )

            # Clear LLM cache, recreate on next fetch
            cls._llm_cache.clear()
            cls._initialized = True

    @classmethod
    def _build_litellm_model_list(cls, models: list) -> list[dict]:
        """
        Build LiteLLM Router model_list.
        Note: extra_body is set to default (thinking disabled) here.
        It will be overridden dynamically when calling the model.
        API keys are decrypted before being passed to litellm.
        """
        result = []
        for m in models:
            # Build default extra_body (thinking disabled)
            extra_body = build_extra_body(m.provider, False)

            # Build litellm model name for Router
            # LiteLLM expects format: provider/model_name (e.g., "dashscope/qwen3.5-flash")
            # If model_id doesn't have provider prefix, add it
            if "/" in m.model_id:
                litellm_model = m.model_id
            else:
                # Add provider prefix based on provider field
                provider_prefix = m.provider.lower()
                # Map common provider names to litellm provider prefixes
                provider_mapping = {
                    "dashscope": "dashscope",
                    "alibaba": "dashscope",
                    "zhipu": "zhipu",
                    "zai": "zhipu",
                    "openai": "openai",
                    "deepseek": "deepseek",
                    "anthropic": "anthropic",
                    "google": "gemini",
                    "gemini": "gemini",
                }
                litellm_provider = provider_mapping.get(provider_prefix, provider_prefix)
                litellm_model = f"{litellm_provider}/{m.model_id}"

            # Decrypt API key before passing to litellm
            decrypted_api_key = decrypt_api_key(m.api_key) if m.api_key else ""

            # Use litellm_model as model_name for Router
            # model_name is the internal identifier, model is the litellm format
            model_config = {
                "model_name": m.model_id,  # Keep original model_id as identifier
                "litellm_params": {
                    "model": litellm_model,  # Use provider-prefixed format for litellm
                    "api_key": decrypted_api_key,
                    "extra_body": extra_body,
                    "stream_options": {
                        "include_usage": True
                    },  # Enable token usage in streaming
                },
            }

            result.append(model_config)
        return result

    @classmethod
    async def get_llm(
        cls,
        model_id: Optional[str] = None,
        thinking_mode: bool = False,
        model_type: str = "llm",
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """
        Get LLM instance

        Args:
            model_id: Specify model ID, use this model if provided
            thinking_mode: Whether to enable thinking mode (only works if model supports it)
            model_type: Model type (llm, vlm), used when model_id not specified

        Returns:
            Runnable LLM instance (ChatLiteLLMRouter with bound extra_body)
        """
        router = await cls.get_router()

        if router is None:
            raise ValueError(
                "No models configured. Please configure models in database."
            )

        # If model_id specified, use directly
        if model_id:
            # Check if model exists
            if model_id not in cls._models_cache:
                raise ValueError(f"Model '{model_id}' not found in database.")

            model = cls._models_cache[model_id]

            # Build cache key with thinking mode
            cache_key = f"{model_id}:{thinking_mode}"
            if cache_key in cls._llm_cache:
                return cls._llm_cache[cache_key]

            # Build extra_body based on provider and thinking_mode
            extra_body = build_extra_body(model.provider, thinking_mode)

            # Build litellm model name for Router
            # The model_name in Router is the original model_id (without provider prefix)
            # But we need to use the provider-prefixed format for litellm
            if "/" in model_id:
                litellm_model = model_id
            else:
                # Add provider prefix based on provider field
                provider_prefix = model.provider.lower()
                provider_mapping = {
                    "dashscope": "dashscope",
                    "alibaba": "dashscope",
                    "zhipu": "zhipu",
                    "zai": "zhipu",
                    "openai": "openai",
                    "deepseek": "deepseek",
                    "anthropic": "anthropic",
                    "google": "gemini",
                    "gemini": "gemini",
                }
                litellm_provider = provider_mapping.get(provider_prefix, provider_prefix)
                litellm_model = f"{litellm_provider}/{model_id}"

            llm = ChatLiteLLMRouter(
                router=router,
                model_name=model_id,  # Use original model_id as model_name (Router identifier)
                temperature=0,
            )

            # Use bind() to attach extra_body, ensuring it's passed during API calls
            # This is necessary because Router ignores extra_body from constructor
            # Also enable stream_options to include token usage in streaming responses
            llm_with_extra_body = llm.bind(
                extra_body=extra_body,
                stream_options={
                    "include_usage": True
                },  # Request token usage in streaming
            )

            cls._llm_cache[cache_key] = llm_with_extra_body
            return llm_with_extra_body

        # Select default model based on model_type
        default_id = None
        if model_type == "llm":
            default_id = cls._default_llm_id
        elif model_type == "vlm":
            default_id = cls._default_vlm_id

        if default_id:
            return await cls.get_llm(model_id=default_id, thinking_mode=thinking_mode)

        # If no default model, use first available of the type
        for m in cls._models_cache.values():
            if m.model_type == model_type:
                return await cls.get_llm(
                    model_id=m.model_id, thinking_mode=thinking_mode
                )

        raise ValueError(f"No {model_type} models available.")

    @classmethod
    async def get_embedding_model(cls, model_id: Optional[str] = None) -> str:
        """
        Get embedding model ID

        Args:
            model_id: Specify model ID, use this model if provided

        Returns:
            Model ID string for embedding
        """
        if model_id:
            if model_id not in cls._models_cache:
                raise ValueError(f"Model '{model_id}' not found in database.")
            return model_id

        # Use default embedding model
        if cls._default_embedding_id:
            return cls._default_embedding_id

        # If no default, use first available embedding model
        for m in cls._models_cache.values():
            if m.model_type == "embedding":
                return m.model_id

        raise ValueError("No embedding models available.")

    @classmethod
    def get_model(cls, model_id: str):
        """Get model from cache"""
        return cls._models_cache.get(model_id)

    @classmethod
    def is_thinking_mode_available(cls, model_id: str) -> bool:
        """Check if a specific model supports thinking mode"""
        model = cls._models_cache.get(model_id)
        if model:
            return model.thinking
        return False

    @classmethod
    def get_model_info_list(cls) -> list[dict]:
        """Get model info list"""
        return [
            {
                "model_id": m.model_id,
                "model_name": m.model_name,
                "model_type": m.model_type,
                "provider": m.provider,
                "thinking": m.thinking,
                "is_default": m.is_default,
                "is_active": m.is_active,
            }
            for m in cls._models_cache.values()
        ]

    @classmethod
    def get_default_llm_id(cls) -> Optional[str]:
        """Get default LLM model ID (from cache, no DB query)"""
        return cls._default_llm_id

    @classmethod
    def get_default_vlm_id(cls) -> Optional[str]:
        """Get default VLM model ID (from cache, no DB query)"""
        return cls._default_vlm_id

    @classmethod
    def get_default_embedding_id(cls) -> Optional[str]:
        """Get default embedding model ID (from cache, no DB query)"""
        return cls._default_embedding_id
