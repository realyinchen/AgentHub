import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, model_validator, field_validator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional


logger = logging.getLogger(__name__)


# .env is always located in the backend/ directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # Changed: empty strings in .env become None instead of ""
        extra="ignore",
        validate_default=True,
    )

    # =========================================================================
    # Application Mode & Metadata
    # =========================================================================
    MODE: Literal["dev", "prod"] = "dev"

    PROJECT_NAME: str = "AgentHub"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "Multi-agent orchestration platform with LangGraph"

    SECRET_KEY: Optional[SecretStr] = None

    API_V1_STR: str = "/api/v1"

    HOST: str = "0.0.0.0"
    PORT: int = 8080
    GRACEFUL_SHUTDOWN_TIMEOUT: int = Field(default=30, ge=1, le=300)

    # =========================================================================
    # Timezone
    # =========================================================================
    # Default IANA timezone used for time-context injection in dynamic prompts.
    DEFAULT_TIMEZONE: str = "Asia/Shanghai"

    # =========================================================================
    # LangSmith Tracing Configuration
    # =========================================================================
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_PROJECT: str = "default"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: Optional[SecretStr] = None

    # =========================================================================
    # Database Configuration (PostgreSQL only)
    # =========================================================================
    # AgentHub uses PostgreSQL exclusively for all environments.
    # Database type and vector store type are always "postgres" / "pgvector".

    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[SecretStr] = None
    POSTGRES_HOST: Optional[str] = None
    POSTGRES_PORT: Optional[int] = Field(default=None, ge=1, le=65535)
    POSTGRES_DB: Optional[str] = None
    POSTGRES_APPLICATION_NAME: str = "agent-hub"
    POSTGRES_SSL_MODE: Literal[
        "disable", "prefer", "require", "verify-ca", "verify-full"
    ] = "prefer"
    POSTGRES_MIN_CONNECTIONS_PER_POOL: int = Field(default=2, ge=1)
    POSTGRES_MAX_CONNECTIONS_PER_POOL: int = Field(default=10, ge=1)

    # =========================================================================
    # Vector Store Configuration (pgvector only)
    # =========================================================================
    # PGVector uses the same PostgreSQL connection as the main database
    # (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB).
    # No additional configuration required.

    # Default embedding dimension for vector databases
    EMBEDDING_DIMENSION: int = Field(default=1024, ge=1)

    # =========================================================================
    # CORS Configuration
    # =========================================================================
    # Comma-separated string, e.g.: "http://localhost:5173,https://app.example.com"
    CORS_ORIGINS: str = "http://localhost:5173"

    # =========================================================================
    # Logging Configuration
    # =========================================================================
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_FORMAT: Literal["console", "json"] = "console"

    # =========================================================================
    # Agent Execution Timeouts
    # =========================================================================
    # Per-request timeout for agent.ainvoke (synchronous invocation).
    # Set to 0 to disable.  Recommended: 120 (2 minutes) for production.
    AGENT_INVOKE_TIMEOUT: float = Field(default=120.0, ge=0)

    # Per-request timeout for agent.astream_events (SSE streaming).
    # Must be longer than invoke because streaming can involve many
    # sequential tool calls.  Set to 0 to disable.
    # Recommended: 300 (5 minutes) for production.
    AGENT_STREAM_TIMEOUT: float = Field(default=300.0, ge=0)

    # =========================================================================
    # LiteLLM Router — Per-Call Timeout
    # =========================================================================
    # Maximum seconds for a single LLM API call through the LiteLLM Router.
    # This applies at the Router level and is separate from the per-request
    # timeouts (AGENT_INVOKE_TIMEOUT / AGENT_STREAM_TIMEOUT).  Set to 0 to
    # disable.  Recommended: 60 seconds for production.
    LLM_REQUEST_TIMEOUT: float = Field(default=60.0, ge=0)

    # =========================================================================
    # JWT Authentication Configuration
    # =========================================================================
    # JWT Token for user authentication (HTTP-only Cookie)
    JWT_SECRET_KEY: Optional[SecretStr] = None
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60 * 24 * 7, ge=1
    )  # 7 days default
    JWT_COOKIE_NAME: str = "agenthub_token"
    JWT_COOKIE_SECURE: bool = True  # HTTPS only (set False for dev without HTTPS)
    JWT_COOKIE_SAMESITE: Literal["strict", "lax", "none"] = "lax"

    # =========================================================================
    # WeChat iLink Bot API Configuration
    # =========================================================================
    # Base URL for WeChat iLink Bot API (Tencent's official server)
    # Can be overridden for custom deployments
    WEIXIN_ILINK_BASE_URL: str = "https://ilinkai.weixin.qq.com"

    # =========================================================================
    # API Keys & Secrets
    # =========================================================================
    # Amap (Gaode Maps) Configuration
    AMAP_KEY: Optional[SecretStr] = None

    # Tavily Search API
    TAVILY_API_KEY: Optional[SecretStr] = None

    # API Key Encryption Configuration
    # This is the AES-256 key used to encrypt API keys stored in the database
    # MUST be set in .env for ALL environments!
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(24)[:32])"
    API_KEY_ENCRYPTION_KEY: Optional[SecretStr] = None

    # =========================================================================
    # System-level Default LLM (Required)
    # =========================================================================
    # Used by agents at compile time, and by all internal/implicit LLM calls
    # (long-term memory extraction, conversation summarization, title generation,
    # etc.). Users can dynamically switch models at runtime per-request, but
    # this is the always-available system fallback.
    #
    # SYSTEM_DEFAULT_LLM_MODEL format: "provider/model-id" (e.g. "zai/glm-5.1")
    SYSTEM_DEFAULT_LLM_MODEL: Optional[str] = None
    SYSTEM_DEFAULT_LLM_API_KEY: Optional[SecretStr] = None
    SYSTEM_DEFAULT_LLM_BASE_URL: Optional[str] = None

    # Optional OpenRouter attribution headers. OpenRouter accepts OpenAI-
    # compatible requests without these, but they help identify the app.
    OPENROUTER_HTTP_REFERER: Optional[str] = None
    OPENROUTER_X_TITLE: str = "AgentHub"

    # =========================================================================
    # System-level Default Embedding (Optional — falls back to LLM API key)
    # =========================================================================
    # When the database has no embedding model configured, the system uses
    # this model as the fallback.  The API key is shared with the system
    # default LLM (SYSTEM_DEFAULT_LLM_API_KEY).
    #
    # SYSTEM_DEFAULT_EMBEDDING_MODEL format: "provider/model-id"
    #   (e.g. "openai/text-embedding-3-small")
    SYSTEM_DEFAULT_EMBEDDING_MODEL: Optional[str] = None

    # =========================================================================
    # Computed Fields
    # =========================================================================

    @computed_field
    @property
    def is_dev(self) -> bool:
        """Whether running in dev (development/test) mode."""
        return self.MODE == "dev"

    @computed_field
    @property
    def system_default_embedding_api_key(self) -> Optional[str]:
        """Fallback embedding API key — shared with SYSTEM_DEFAULT_LLM_API_KEY."""
        if self.SYSTEM_DEFAULT_LLM_API_KEY is None:
            return None
        return self.SYSTEM_DEFAULT_LLM_API_KEY.get_secret_value()

    @computed_field
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS comma-separated string into a list."""
        if not self.CORS_ORIGINS.strip():
            return []
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]

    # =========================================================================
    # Field Validators
    # =========================================================================

    @field_validator(
        "LANGCHAIN_API_KEY",
        "AMAP_KEY",
        "TAVILY_API_KEY",
        "API_KEY_ENCRYPTION_KEY",
        "SYSTEM_DEFAULT_LLM_API_KEY",
        "JWT_SECRET_KEY",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings from .env to None for Optional SecretStr fields."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator(
        "POSTGRES_USER",
        "POSTGRES_HOST",
        "POSTGRES_DB",
        "SYSTEM_DEFAULT_LLM_MODEL",
        "SYSTEM_DEFAULT_LLM_BASE_URL",
        "SYSTEM_DEFAULT_EMBEDDING_MODEL",
        mode="before",
    )
    @classmethod
    def empty_str_to_none_str(cls, v):
        """Convert empty strings from .env to None for Optional str fields."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # =========================================================================
    # Model Validators (mode="after" - run after field parsing)
    # =========================================================================

    @model_validator(mode="after")
    def validate_pool_sizes(self) -> "Settings":
        """Validate PostgreSQL connection pool size configuration."""
        if (
            self.POSTGRES_MIN_CONNECTIONS_PER_POOL is not None
            and self.POSTGRES_MAX_CONNECTIONS_PER_POOL is not None
            and self.POSTGRES_MIN_CONNECTIONS_PER_POOL
            > self.POSTGRES_MAX_CONNECTIONS_PER_POOL
        ):
            raise ValueError(
                "POSTGRES_MIN_CONNECTIONS_PER_POOL must be <= POSTGRES_MAX_CONNECTIONS_PER_POOL"
            )
        return self

    @model_validator(mode="after")
    def validate_postgres_config(self) -> "Settings":
        """Validate required PostgreSQL fields."""
        required_fields = [
            ("POSTGRES_USER", self.POSTGRES_USER),
            ("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD),
            ("POSTGRES_HOST", self.POSTGRES_HOST),
            ("POSTGRES_PORT", self.POSTGRES_PORT),
            ("POSTGRES_DB", self.POSTGRES_DB),
        ]
        missing = [name for name, value in required_fields if value is None]
        if missing:
            raise ValueError(
                f"PostgreSQL is required. The following fields must be set in .env: "
                f"{', '.join(missing)}."
            )
        return self

    @model_validator(mode="after")
    def validate_api_key_encryption_key(self) -> "Settings":
        """Validate API_KEY_ENCRYPTION_KEY is set (required for ALL environments)."""
        if self.API_KEY_ENCRYPTION_KEY is None:
            raise ValueError(
                "API_KEY_ENCRYPTION_KEY must be set in .env for ALL environments. "
                'Generate a secure key with: python -c "import secrets; print(secrets.token_urlsafe(24)[:32])"'
            )
        return self

    @model_validator(mode="after")
    def validate_system_default_llm(self) -> "Settings":
        """Validate the system-level default LLM is fully configured.

        SYSTEM_DEFAULT_LLM_MODEL + SYSTEM_DEFAULT_LLM_API_KEY are REQUIRED —
        they back the agent's compile-time default model and every internal/
        implicit LLM call (summarization, long-term memory, title generation,
        etc.).

        SYSTEM_DEFAULT_LLM_MODEL must be in "provider/model-id" form so the
        provider can be parsed for provider-specific extra_body handling.
        """
        if (
            self.SYSTEM_DEFAULT_LLM_MODEL is None
            or self.SYSTEM_DEFAULT_LLM_API_KEY is None
        ):
            raise ValueError(
                "SYSTEM_DEFAULT_LLM_MODEL and SYSTEM_DEFAULT_LLM_API_KEY must both be set in .env. "
                "These provide the system-level fallback LLM used by all agents "
                "and internal LLM calls."
            )
        if "/" not in self.SYSTEM_DEFAULT_LLM_MODEL:
            raise ValueError(
                f"SYSTEM_DEFAULT_LLM_MODEL must be in 'provider/model-id' format, "
                f"got '{self.SYSTEM_DEFAULT_LLM_MODEL}'. Example: 'zai/glm-5.1'."
            )
        return self

    @model_validator(mode="after")
    def validate_langsmith_config(self) -> "Settings":
        """Validate and enforce LangSmith restrictions.

        Rules:
        1. Only dev MODE can use LangSmith tracing. Prod mode is always disabled.
        2. If LANGCHAIN_TRACING_V2=True, LANGCHAIN_API_KEY must be provided.
           If not provided, tracing is force-disabled and a warning is logged.
        """
        # Rule 1: Only dev mode can use LangSmith
        if not self.is_dev and self.LANGCHAIN_TRACING_V2:
            logger.warning(
                "LangSmith tracing is only allowed in dev mode. "
                f"MODE='{self.MODE}' detected. Forcing LANGCHAIN_TRACING_V2=False."
            )
            self.LANGCHAIN_TRACING_V2 = False
            return self

        # Rule 2: If tracing is enabled in dev mode, API key must be set
        if self.is_dev and self.LANGCHAIN_TRACING_V2 and self.LANGCHAIN_API_KEY is None:
            logger.warning(
                "LANGCHAIN_TRACING_V2=True but LANGCHAIN_API_KEY is not set. "
                "Forcing LANGCHAIN_TRACING_V2=False. "
                "Get a key from: https://smith.langchain.com/"
            )
            self.LANGCHAIN_TRACING_V2 = False

        return self

    @model_validator(mode="after")
    def validate_jwt_config(self) -> "Settings":
        """Validate JWT_SECRET_KEY is set (required for user authentication)."""
        if self.JWT_SECRET_KEY is None:
            raise ValueError(
                "JWT_SECRET_KEY must be set in .env for user authentication. "
                'Generate a secure key with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return self

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_encoded_credentials(self) -> tuple[str, str]:
        """Return URL-encoded (user, password) tuple for PostgreSQL connection strings."""
        # These are guaranteed to be set by validate_postgres_config
        assert self.POSTGRES_USER is not None
        assert self.POSTGRES_PASSWORD is not None
        return (
            quote_plus(self.POSTGRES_USER),
            quote_plus(self.POSTGRES_PASSWORD.get_secret_value()),
        )

    def get_async_postgres_url(self) -> str:
        """Build and return the asynchronous PostgreSQL connection string."""
        user, password = self._get_encoded_credentials()
        return (
            f"postgresql+asyncpg://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def get_postgres_url(self) -> str:
        """Build and return the synchronous PostgreSQL connection string."""
        user, password = self._get_encoded_credentials()
        return (
            f"postgresql+psycopg://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?application_name={self.POSTGRES_APPLICATION_NAME}"
            f"&sslmode={self.POSTGRES_SSL_MODE}"
            f"&connect_timeout=5"
        )

    def get_postgres_libpq_url(self) -> str:
        """Build and return the PostgreSQL connection string for psycopg 3.

        Returns a postgresql+psycopg:// URL suitable for SQLAlchemy
        connections via the psycopg 3 driver (psycopg-binary).
        """
        user, password = self._get_encoded_credentials()
        return (
            f"postgresql+psycopg://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?sslmode={self.POSTGRES_SSL_MODE}"
            f"&connect_timeout=5"
        )

    def get_postgres_conn_string(self) -> str:
        """Build and return a plain libpq connection string for psycopg 3.

        Returns a postgresql:// URL (no SQLAlchemy driver prefix) suitable
        for psycopg's native AsyncConnection.connect() and LangGraph's
        AsyncPostgresSaver / AsyncPostgresStore.
        """
        user, password = self._get_encoded_credentials()
        return (
            f"postgresql://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?sslmode={self.POSTGRES_SSL_MODE}"
            f"&connect_timeout=5"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get settings instance (cached, FastAPI recommended pattern)."""
    return Settings()


def reset_settings() -> None:
    """Clear cached settings (for testing).

    Usage:
        from app.infra.config import reset_settings
        reset_settings()
        # Now new settings will be loaded from environment
    """
    get_settings.cache_clear()
