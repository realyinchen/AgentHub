# pyright: reportArgumentType=false

import logging
from langchain_litellm import ChatLiteLLMRouter
from langchain_community.embeddings import DashScopeEmbeddings
from litellm.router import Router
from langchain_core.messages import AIMessage

from app.core.config import settings


logger = logging.getLogger(__name__)


def _get_api_key_from_model_list(model_list: list[dict]) -> str | None:
    """Extract API key from model list configuration."""
    for model_config in model_list:
        litellm_params = model_config.get("litellm_params", {})
        api_key = litellm_params.get("api_key")
        if api_key:
            return api_key
    return None


def _build_model_list_for_router(model_list: list[dict]) -> list[dict]:
    """
    Build model list for litellm Router.
    Ensures each model has the required fields.
    """
    result = []
    for model_config in model_list:
        model_name = model_config.get("model_name")
        litellm_params = model_config.get("litellm_params", {})
        
        if not model_name or not litellm_params:
            continue
            
        result.append({
            "model_name": model_name,
            "litellm_params": litellm_params,
        })
    return result


# Initialize LLM instances
llm = None
thinking_llm = None
embedding_model = None

# Get model list from configuration
model_list = settings.get_model_list()

if model_list:
    # Router mode: use ChatLiteLLMRouter for multi-model management
    logger.info("Initializing LLMs in Router mode with %d models", len(model_list))
    
    # Build model list for router
    router_model_list = _build_model_list_for_router(model_list)
    
    # Create litellm Router
    litellm_router = Router(model_list=router_model_list)
    
    # Get default and thinking model names
    default_model_name = settings.LLM_DEFAULT_MODEL
    thinking_model_name = settings.LLM_THINKING_MODEL
    
    # Create LLM instances
    if default_model_name:
        llm = ChatLiteLLMRouter(
            router=litellm_router,
            model_name=default_model_name,
            temperature=0,
        )
        logger.info("Created default LLM with model_name=%s", default_model_name)
    
    if thinking_model_name:
        thinking_llm = ChatLiteLLMRouter(
            router=litellm_router,
            model_name=thinking_model_name,
            temperature=0,
        )
        logger.info("Created thinking LLM with model_name=%s", thinking_model_name)
    
    # Initialize embedding model
    api_key = _get_api_key_from_model_list(model_list)
    if api_key and settings.EMBEDDING_MODEL_NAME:
        embedding_model = DashScopeEmbeddings(
            model=settings.EMBEDDING_MODEL_NAME,
            dashscope_api_key=api_key,
        )
        logger.info("Created embedding model: %s", settings.EMBEDDING_MODEL_NAME)

elif settings.LLM_API_KEY and settings.LLM_NAME:
    # Legacy single model mode
    logger.info("Initializing LLMs in single model mode")
    
    api_key = settings.LLM_API_KEY.get_secret_value()
    
    llm = ChatLiteLLMRouter(
        router=Router(model_list=[{
            "model_name": "default",
            "litellm_params": {
                "model": settings.LLM_NAME,
                "api_key": api_key,
                "api_base": settings.LLM_BASE_URL,
                "extra_body": {"enable_thinking": False},
            },
        }]),
        model_name="default",
        temperature=0,
    )
    
    # In single model mode, thinking mode uses the same model with enable_thinking
    if settings.LLM_BASE_URL:
        thinking_llm = ChatLiteLLMRouter(
            router=Router(model_list=[{
                "model_name": "thinking",
                "litellm_params": {
                    "model": settings.LLM_NAME,
                    "api_key": api_key,
                    "api_base": settings.LLM_BASE_URL,
                    "extra_body": {"enable_thinking": True},
                },
            }]),
            model_name="thinking",
            temperature=0,
        )
    
    if settings.EMBEDDING_MODEL_NAME:
        embedding_model = DashScopeEmbeddings(
            model=settings.EMBEDDING_MODEL_NAME,
            dashscope_api_key=api_key,
        )
else:
    logger.warning("No LLM configuration found. Please set LLM_MODELS or LLM_API_KEY/LLM_NAME.")


def get_llm(thinking_mode: bool = False) -> ChatLiteLLMRouter | None:
    """
    Get the appropriate LLM based on thinking_mode.

    Args:
        thinking_mode: If True, return the thinking model; otherwise return the normal model.

    Returns:
        ChatLiteLLMRouter instance or None if not configured
    """
    if thinking_mode:
        if thinking_llm:
            logger.debug("get_llm: returning thinking_llm")
            return thinking_llm
        logger.warning("Thinking mode requested but thinking_llm not configured")
    if llm:
        logger.debug("get_llm: returning default llm")
        return llm
    raise ValueError("No LLM configured. Please set LLM_MODELS or LLM_API_KEY/LLM_NAME.")


def is_thinking_mode_available() -> bool:
    """Check if thinking mode is available."""
    return thinking_llm is not None


def extract_thinking_and_answer(msg: AIMessage) -> dict:
    """
    Extract thinking content and final answer from AIMessage.
    
    Handles both structured content (list of blocks) and string content.
    
    Args:
        msg: AIMessage from LLM response
        
    Returns:
        dict with 'thinking' and 'final_answer' keys
    """
    thinking = ""
    final_answer = ""

    if isinstance(msg.content, list):
        # Structured content: [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "..."}]
        for block in msg.content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "thinking":
                    thinking += block.get("thinking", "") + "\n"
                elif block_type == "text":
                    final_answer += block.get("text", "") + "\n"
    elif isinstance(msg.content, str):
        # Fallback to string content
        final_answer = msg.content

    # Alternative: get reasoning from additional_kwargs
    reasoning_from_kwargs = msg.additional_kwargs.get("reasoning_content", "")
    if not thinking.strip() and reasoning_from_kwargs:
        thinking = reasoning_from_kwargs.strip()

    return {
        "thinking": thinking.strip(),
        "final_answer": final_answer.strip(),
    }