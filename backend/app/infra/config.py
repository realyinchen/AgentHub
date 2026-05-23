import os

# Disable LiteLLM remote model cost map fetch to avoid SSL timeout errors
# This must be set BEFORE importing litellm anywhere in the codebase
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

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
    # LangSmith Tracing Configuration
    # =========================================================================
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_PROJECT: str = "default"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: Optional[SecretStr] = None

    # =========================================================================
    # Database Configuration
    # =========================================================================
    # DATABASE_TYPE is a computed_field, determined by MODE:
    # - dev -> sqlite
    # - prod -> postgres

    # PostgreSQL Configuration (required for DATABASE_TYPE == "postgres")
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

    # SQLite configuration (used when DATABASE_TYPE == "sqlite")
    SQLITE_DATABASE_PATH: str = "./data/agenthub.db"

    # =========================================================================
    # Vector Store Configuration
    # =========================================================================
    # VECTORSTORE_TYPE is a computed_field, determined by MODE:
    # - dev -> sqlite_vec
    # - prod -> pgvector (PostgreSQL pgvector extension, no external service)

    # PGVector uses the same PostgreSQL connection as the main database
    # (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB)
    # No additional configuration required.

    # Default embedding dimension for vector databases
    EMBEDDING_DIMENSION: int = Field(default=1024, ge=1)

    # =========================================================================
    # WebSocket Configuration
    # =========================================================================
    WS_ENABLED: bool = False
    WS_HEARTBEAT_INTERVAL: int = Field(default=30, ge=1)

    # =========================================================================
    # CORS Configuration
    # =========================================================================
    # Comma-separated string, e.g.: "http://localhost:5173,https://app.example.com"
    CORS_ORIGINS: str = "http://localhost:5173"

    # =========================================================================
    # Logging Configuration
    # =========================================================================
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

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
    # Prompts Configuration
    # =========================================================================
    # Absolute path to the prompts directory.
    # None = auto-resolve to app/prompts/ relative to the backend package.
    PROMPTS_DIR: Optional[str] = Field(
        default=None,
        description="Absolute path to prompts directory. None = use app/prompts/.",
    )

    # =========================================================================
    # System-level Default LLM (Required)
    # =========================================================================
    # Used by agents at compile time, and by all internal/implicit LLM calls
    # (long-term memory extraction, conversation summarization, title generation,
    # etc.). Users can dynamically switch models at runtime per-request, but
    # this is the always-available system fallback.
    #
    # DEFAULT_LLM_MODEL format: "provider/model-id" (e.g. "zai/glm-5.1")
    DEFAULT_LLM_MODEL: Optional[str] = None
    DEFAULT_LLM_API_KEY: Optional[SecretStr] = None

    # =========================================================================
    # Computed Fields
    # =========================================================================

    @computed_field
    @property
    def DATABASE_TYPE(self) -> Literal["sqlite", "postgres"]:
        """Database type, automatically determined by MODE.

        - dev -> sqlite
        - prod -> postgres
        """
        if self.MODE == "prod":
            return "postgres"
        return "sqlite"

    @computed_field
    @property
    def VECTORSTORE_TYPE(self) -> Literal["sqlite_vec", "pgvector"]:
        """Vector store type, automatically determined by MODE.

        - dev -> sqlite_vec
        - prod -> pgvector (PostgreSQL pgvector extension)
        """
        if self.MODE == "prod":
            return "pgvector"
        return "sqlite_vec"

    @computed_field
    @property
    def is_dev(self) -> bool:
        """Whether running in dev (development/test) mode."""
        return self.MODE == "dev"

    @computed_field
    @property
    def prompts_dir(self) -> Path:
        """Resolved prompts directory path."""
        if self.PROMPTS_DIR:
            return Path(self.PROMPTS_DIR)
        return Path(__file__).resolve().parent.parent / "prompts"

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
        "DEFAULT_LLM_API_KEY",
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
        "DEFAULT_LLM_MODEL",
        "PROMPTS_DIR",
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
        # Only validate if using PostgreSQL
        if self.DATABASE_TYPE == "postgres":
            if (
                self.POSTGRES_MIN_CONNECTIONS_PER_POOL
                > self.POSTGRES_MAX_CONNECTIONS_PER_POOL
            ):
                raise ValueError(
                    "POSTGRES_MIN_CONNECTIONS_PER_POOL must be <= POSTGRES_MAX_CONNECTIONS_PER_POOL"
                )
        return self

    @model_validator(mode="after")
    def validate_postgres_config(self) -> "Settings":
        """Validate required PostgreSQL fields when DATABASE_TYPE is postgres."""
        if self.DATABASE_TYPE == "postgres":
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
                    f"DATABASE_TYPE='postgres' requires the following fields to be set: "
                    f"{', '.join(missing)}. Please set these in .env."
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

        DEFAULT_LLM_MODEL + DEFAULT_LLM_API_KEY are REQUIRED — they back the
        agent's compile-time default model and every internal/implicit LLM
        call (summarization, long-term memory, title generation, etc.).
        DEFAULT_LLM_MODEL must be in "provider/model-id" form so the provider
        can be parsed for provider-specific extra_body handling.
        """
        if self.DEFAULT_LLM_MODEL is None or self.DEFAULT_LLM_API_KEY is None:
            raise ValueError(
                "DEFAULT_LLM_MODEL and DEFAULT_LLM_API_KEY must both be set in .env. "
                "These provide the system-level fallback LLM used by all agents "
                "and internal LLM calls."
            )
        if "/" not in self.DEFAULT_LLM_MODEL:
            raise ValueError(
                f"DEFAULT_LLM_MODEL must be in 'provider/model-id' format, "
                f"got '{self.DEFAULT_LLM_MODEL}'. Example: 'zai/glm-5.1'."
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

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _require_postgres(self) -> None:
        """Raise RuntimeError if not using PostgreSQL."""
        if self.DATABASE_TYPE != "postgres":
            raise RuntimeError(
                f"PostgreSQL URLs are not available when DATABASE_TYPE='{self.DATABASE_TYPE}'. "
                "Check settings.DATABASE_TYPE before calling this method."
            )

    def _get_encoded_credentials(self) -> tuple[str, str]:
        """Return URL-encoded (user, password) tuple for PostgreSQL connection strings."""
        self._require_postgres()
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
            f"?application_name={self.POSTGRES_APPLICATION_NAME}"
            f"&sslmode={self.POSTGRES_SSL_MODE}"
        )

    def get_postgres_url(self) -> str:
        """Build and return the synchronous PostgreSQL connection string."""
        user, password = self._get_encoded_credentials()
        return (
            f"postgresql+psycopg://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?application_name={self.POSTGRES_APPLICATION_NAME}"
            f"&sslmode={self.POSTGRES_SSL_MODE}"
        )

    def get_postgres_libpq_url(self) -> str:
        """Build and return the raw PostgreSQL libpq connection string.

        Returns the postgresql:// URL without driver prefix, suitable for
        direct psycopg/postgres (libpq) connections.
        """
        user, password = self._get_encoded_credentials()
        return (
            f"postgresql://{user}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            f"?sslmode={self.POSTGRES_SSL_MODE}"
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
