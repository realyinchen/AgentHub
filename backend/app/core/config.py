import json
import os
from dotenv import find_dotenv
from pydantic import (
    BeforeValidator,
    HttpUrl,
    SecretStr,
    TypeAdapter,
    computed_field,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Annotated, Any


def is_running_in_docker() -> bool:
    """
    Detect if the application is running inside a Docker container.

    Returns:
        True if running in Docker, False otherwise.
    """
    # Check for /.dockerenv file (Docker creates this file in containers)
    if os.path.exists("/.dockerenv"):
        return True

    # Check /proc/1/cgroup for Docker indicators
    try:
        with open("/proc/1/cgroup", "r") as f:
            content = f.read()
            # Docker containers typically have "docker" or "containerd" in cgroup
            if "docker" in content or "containerd" in content:
                return True
    except (FileNotFoundError, PermissionError):
        pass

    return False


def get_default_host() -> str:
    """
    Get the default host based on the runtime environment.

    Returns:
        'host.docker.internal' if running in Docker, 'localhost' otherwise.
    """
    return "host.docker.internal" if is_running_in_docker() else "localhost"


def check_str_is_http(x: str) -> str:
    http_url_adapter = TypeAdapter(HttpUrl)
    return str(http_url_adapter.validate_python(x))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_dotenv(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=False,
    )
    MODE: str | None = None

    API_V1_STR: str = "/api/v1"

    HOST: str = "0.0.0.0"
    PORT: int = 8080
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 30

    # Default LLM configuration (fallback if LLM_MODELS is not set)
    LLM_API_KEY: SecretStr | None = None
    LLM_BASE_URL: str | None = None
    LLM_NAME: str | None = None
    EMBEDDING_MODEL_NAME: str | None = None

    # Multi-model configuration in JSON format
    # Example:
    # LLM_MODELS='[
    #   {
    #     "model_name": "default",
    #     "litellm_params": {
    #       "model": "dashscope/qwen3-max",
    #       "api_key": "sk-xxx",
    #       "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    #     }
    #   },
    #   {
    #     "model_name": "thinking",
    #     "litellm_params": {
    #       "model": "dashscope/qwen3.5-27b",
    #       "api_key": "sk-xxx",
    #       "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    #       "extra_body": {"enable_thinking": true}
    #     }
    #   }
    # ]'
    LLM_MODELS: str | None = None

    # Default model name to use (must match a model_name in LLM_MODELS)
    LLM_DEFAULT_MODEL: str = "default"

    # Thinking model name (must match a model_name in LLM_MODELS)
    # If not set, thinking mode feature is disabled
    LLM_THINKING_MODEL: str | None = None

    # Legacy thinking model configuration (for backward compatibility)
    THINKING_LLM_NAME: str | None = None
    THINKING_ENABLE_PARAM: str | None = None

    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_PROJECT: str = "default"
    LANGCHAIN_ENDPOINT: Annotated[str, BeforeValidator(check_str_is_http)] = (
        "https://api.smith.langchain.com"
    )
    LANGCHAIN_API_KEY: SecretStr | None = None

    # PostgreSQL Configuration
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_HOST: str | None = None
    POSTGRES_PORT: int | None = None
    POSTGRES_DB: str | None = None
    POSTGRES_APPLICATION_NAME: str = "agent-hub"
    POSTGRES_MIN_CONNECTIONS_PER_POOL: int = 1
    POSTGRES_MAX_CONNECTIONS_PER_POOL: int = 1

    # Qdrant Configuration
    QDRANT_HOST: str | None = None
    QDRANT_PORT: int | None = None
    QDRANT_COLLECTION: str = ""

    def model_post_init(self, __context: Any) -> None:
        """
        Set intelligent defaults for host configurations after model initialization.

        If POSTGRES_HOST or QDRANT_HOST are not explicitly set in environment,
        automatically detect the runtime environment and set appropriate values:
        - Docker container: use 'host.docker.internal' to access host services
        - Local development: use 'localhost'
        """
        # Set intelligent default for POSTGRES_HOST if not explicitly configured
        if self.POSTGRES_HOST is None:
            object.__setattr__(self, "POSTGRES_HOST", get_default_host())

        # Set intelligent default for QDRANT_HOST if not explicitly configured
        if self.QDRANT_HOST is None:
            object.__setattr__(self, "QDRANT_HOST", get_default_host())

    # Amap (高德地图) Configuration
    AMAP_KEY: SecretStr | None = None

    @computed_field
    @property
    def ASYNC_POSTGRE_URL(self) -> str:
        """Build and return the asynchronous PostgreSQL connection string."""
        if settings.POSTGRES_PASSWORD is None:
            raise ValueError("POSTGRES_PASSWORD is not set")
        return (
            f"postgresql+asyncpg://{settings.POSTGRES_USER}:"
            f"{settings.POSTGRES_PASSWORD.get_secret_value()}@"
            f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/"
            f"{settings.POSTGRES_DB}"
        )

    @computed_field
    @property
    def POSTGRE_URL(self) -> str:
        if settings.POSTGRES_PASSWORD is None:
            raise ValueError("POSTGRES_PASSWORD is not set")
        return (
            f"postgresql+psycopg://{settings.POSTGRES_USER}:"
            f"{settings.POSTGRES_PASSWORD.get_secret_value()}@"
            f"{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/"
            f"{settings.POSTGRES_DB}"
        )

    @computed_field
    @property
    def BASE_URL(self) -> str:
        return f"http://{self.HOST}:{self.PORT}"

    def is_dev(self) -> bool:
        return self.MODE == "dev"

    def get_model_list(self) -> list[dict[str, Any]] | None:
        """
        Parse LLM_MODELS JSON string into a list of model configurations.

        Returns:
            List of model configurations, or None if LLM_MODELS is not set
        """
        if not self.LLM_MODELS:
            return None

        try:
            models = json.loads(self.LLM_MODELS)
            if isinstance(models, list):
                return models
        except json.JSONDecodeError:
            pass

        return None

    def is_router_mode(self) -> bool:
        """Check if the app is configured to use ChatLiteLLMRouter mode."""
        return self.get_model_list() is not None

    def get_model_info_list(self) -> list[dict[str, Any]]:
        """
        Get list of model info with name and is_thinking flag.

        A model is considered a "thinking" model if its model_name ends with "thinking".

        Returns:
            List of dicts with 'name' and 'is_thinking' keys
        """
        model_list = self.get_model_list()
        if not model_list:
            return []

        result = []
        for model_config in model_list:
            model_name = model_config.get("model_name")
            if model_name:
                # Check if model_name ends with "thinking" (case-insensitive)
                is_thinking = model_name.lower().endswith("thinking")
                result.append(
                    {
                        "name": model_name,
                        "is_thinking": is_thinking,
                    }
                )
        return result


settings = Settings()
