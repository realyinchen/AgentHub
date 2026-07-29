-- init_database.sql
-- Idempotent: safe to run multiple times, no DROP, no destructive changes

-- 1. users table (main user table for authentication)
CREATE TABLE IF NOT EXISTS public.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    VARCHAR(64) NOT NULL,
    is_mock_user    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for looking up mock users
CREATE INDEX IF NOT EXISTS idx_users_is_mock_user ON public.users(is_mock_user);

-- Mock users for development/demo (idempotent)
INSERT INTO public.users (id, display_name, is_mock_user)
VALUES 
    ('00000000-0000-0000-0000-000000000001', 'Jack', true),
    ('00000000-0000-0000-0000-000000000002', 'Rose', true)
ON CONFLICT (id) DO NOTHING;

-- 2. user_channels table (channel bindings for users)
CREATE TABLE IF NOT EXISTS public.user_channels (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                  UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    channel                  VARCHAR(32) NOT NULL,  -- 'weixin', 'telegram', etc.
    channel_user_id          VARCHAR(128) NOT NULL,  -- e.g., 'xxx@im.wechat'
    channel_token            TEXT,  -- Bot token (encrypted)
    channel_base_url         VARCHAR(512),  -- API base URL
    channel_token_expires_at TIMESTAMPTZ,
    channel_extra_data       JSONB,
    last_contact_id          VARCHAR(128),  -- Last contact for reconnection
    last_context_token       TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(channel, channel_user_id)
);

-- Indexes for user_channels
CREATE INDEX IF NOT EXISTS idx_user_channels_user_id ON public.user_channels(user_id);
CREATE INDEX IF NOT EXISTS idx_user_channels_channel ON public.user_channels(channel);

-- 3. conversations table
CREATE TABLE IF NOT EXISTS public.conversations (
    thread_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title            VARCHAR(64) NOT NULL,
    is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Token usage fields (cumulative for the conversation)
    input_tokens     BIGINT NOT NULL DEFAULT 0,
    output_tokens    BIGINT NOT NULL DEFAULT 0,
    total_tokens     BIGINT NOT NULL DEFAULT 0
);

-- User-scoped index: list active conversations for a user, sorted by last update
CREATE INDEX IF NOT EXISTS idx_conv_user_active 
ON public.conversations (user_id, is_deleted, updated_at DESC);

-- Covering index for user-scoped conversation list (avoids table lookups)
CREATE INDEX IF NOT EXISTS idx_conv_user_list 
ON public.conversations (user_id, is_deleted, updated_at DESC) 
INCLUDE (thread_id, title, created_at, input_tokens, output_tokens, total_tokens)
WHERE is_deleted = FALSE;

-- Index for pagination and sorting by created_at
CREATE INDEX IF NOT EXISTS idx_conversations_created_at 
ON public.conversations (created_at DESC) 
WHERE is_deleted = FALSE;

-- 4. providers table (protocol/adapter registry)
CREATE TABLE IF NOT EXISTS public.providers (
    provider               VARCHAR(64) PRIMARY KEY,   -- e.g. "dashscope", "zai", "openai-compatible"
    api_key                TEXT NOT NULL DEFAULT '',  -- legacy encrypted API key; new code uses provider_connections
    base_url               VARCHAR(512),              -- legacy base URL; new code uses provider_connections
    is_openai_compatible   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for providers
CREATE INDEX IF NOT EXISTS idx_providers_is_openai_compatible ON public.providers(is_openai_compatible);

-- =============================================================================
-- Insert default providers (idempotent)
-- IMPORTANT: Configure providers first, then add models via web UI!
-- =============================================================================

-- DashScope provider (Alibaba Cloud)
-- Get your API key from: https://dashscope.console.aliyun.com/apiKey
INSERT INTO public.providers (provider, api_key, is_openai_compatible)
VALUES ('dashscope', '', false)
ON CONFLICT (provider) DO NOTHING;

-- Generic OpenAI-compatible provider for custom gateways.
INSERT INTO public.providers (provider, api_key, base_url, is_openai_compatible)
VALUES ('openai-compatible', 'local', 'http://127.0.0.1:1234/v1', true)
ON CONFLICT (provider) DO NOTHING;

-- OpenRouter OpenAI-compatible gateway.
-- Configure api_key before using. Free model IDs usually use the free suffix.
INSERT INTO public.providers (provider, api_key, base_url, is_openai_compatible)
VALUES ('openrouter', '', 'https://openrouter.ai/api/v1', true)
ON CONFLICT (provider) DO NOTHING;

-- 4.1 provider_connections table (concrete endpoint/account config)
CREATE TABLE IF NOT EXISTS public.provider_connections (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider             VARCHAR(64) NOT NULL REFERENCES public.providers(provider),
    name                 VARCHAR(128) NOT NULL,
    preset_type          VARCHAR(32) NOT NULL DEFAULT 'default',
    api_key              TEXT NOT NULL DEFAULT '',
    base_url             VARCHAR(512),
    extra_headers_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_connections_provider_name
ON public.provider_connections(provider, name);
CREATE INDEX IF NOT EXISTS idx_provider_connections_provider
ON public.provider_connections(provider);
CREATE INDEX IF NOT EXISTS idx_provider_connections_active
ON public.provider_connections(is_active);

INSERT INTO public.provider_connections (provider, name, preset_type, api_key, base_url, is_active)
VALUES
    ('dashscope', 'DashScope 默认', 'default', '', NULL, true),
    ('openrouter', 'OpenRouter 默认', 'default', '', 'https://openrouter.ai/api/v1', true),
    ('openai-compatible', 'LM Studio 本地', 'lmstudio', 'local', 'http://127.0.0.1:1234/v1', true),
    ('openai-compatible', 'Ollama 本地', 'ollama', 'local', 'http://127.0.0.1:11434/v1', false),
    ('openai-compatible', 'vLLM', 'vllm', 'local', 'http://127.0.0.1:8000/v1', false),
    ('openai-compatible', '自定义 API', 'custom', '', NULL, false)
ON CONFLICT (provider, name) DO NOTHING;

-- 5. models table (user maintains all model configurations)
-- Note: api_key is now stored in providers table
-- Note: model_id is the plain model name (e.g. "qwen3.5-32b").
--       The full litellm model name "provider/model_id" is assembled at runtime.
CREATE TABLE IF NOT EXISTS public.models (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- UUID primary key
    provider               VARCHAR(64) NOT NULL REFERENCES public.providers(provider),  -- FK to providers
    connection_id          UUID REFERENCES public.provider_connections(id),
    model_type             VARCHAR(16) NOT NULL DEFAULT 'llm',  -- llm, vlm, embedding
    model_id               VARCHAR(128) NOT NULL,  -- provider model name, e.g. "qwen3.5-32b"
    thinking               BOOLEAN NOT NULL DEFAULT FALSE,  -- whether supports thinking mode
    is_default             BOOLEAN NOT NULL DEFAULT FALSE,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for models
CREATE INDEX IF NOT EXISTS idx_models_provider ON public.models(provider);
CREATE INDEX IF NOT EXISTS idx_models_connection_id ON public.models(connection_id);
CREATE INDEX IF NOT EXISTS idx_models_model_type ON public.models(model_type);
CREATE INDEX IF NOT EXISTS idx_models_thinking ON public.models(thinking);
CREATE INDEX IF NOT EXISTS idx_models_is_active ON public.models(is_active);
CREATE INDEX IF NOT EXISTS idx_models_is_default ON public.models(is_default);
CREATE INDEX IF NOT EXISTS idx_models_model_id ON public.models(model_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_models_connection_model_id
ON public.models(connection_id, model_id)
WHERE connection_id IS NOT NULL;

-- =============================================================================
-- Models should be configured via web UI after providers are set up
-- No default models are inserted - configure them in the application
-- =============================================================================

INSERT INTO public.models (provider, connection_id, model_type, model_id, thinking, is_default, is_active)
SELECT 'openrouter', pc.id, 'llm', 'nex-agi/nex-n2-pro:free', true, false, true
FROM public.provider_connections pc
WHERE pc.provider = 'openrouter' AND pc.name = 'OpenRouter 默认'
ON CONFLICT DO NOTHING;

-- 6. model_capability_checks table (observed runtime model capability)
CREATE TABLE IF NOT EXISTS public.model_capability_checks (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id                 UUID NOT NULL REFERENCES public.models(id) ON DELETE CASCADE,
    provider                 VARCHAR(64) NOT NULL,
    provider_model_id        VARCHAR(256) NOT NULL,
    checked_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chat_ok                  BOOLEAN NOT NULL DEFAULT FALSE,
    thinking_request_ok      BOOLEAN,
    reasoning_text_ok        BOOLEAN,
    streaming_reasoning_ok   BOOLEAN,
    reasoning_field_path     VARCHAR(128),
    latency_ms               INTEGER,
    error_type               VARCHAR(64),
    last_error               TEXT,
    raw_summary              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_model_capability_model_checked
ON public.model_capability_checks(model_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_capability_provider_model
ON public.model_capability_checks(provider, provider_model_id);
CREATE INDEX IF NOT EXISTS idx_model_capability_reasoning
ON public.model_capability_checks(reasoning_text_ok);

-- 7. trace_executions table (persisted DAG snapshots for offline trace viewing)
-- Each row = one agent invocation (user→agent turn), identified by request_id.
-- Contains model used and the full ExecutionDag.
CREATE TABLE IF NOT EXISTS public.trace_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id       UUID NOT NULL REFERENCES public.conversations(thread_id) ON DELETE CASCADE,
    request_id      VARCHAR(128) NOT NULL,
    model_name      VARCHAR(128),              -- LLM model used for this turn
    dag_data        JSONB NOT NULL,             -- Complete ExecutionDag as JSONB
    total_steps     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for trace_executions
CREATE INDEX IF NOT EXISTS idx_trace_exec_thread_id
ON public.trace_executions (thread_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trace_exec_request_id
ON public.trace_executions (request_id);

-- 8. langchain_pg_collection table (PGVector — collection registry)
CREATE TABLE IF NOT EXISTS public.langchain_pg_collection (
    uuid       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name       VARCHAR NOT NULL UNIQUE,
    cmetadata  JSON
);

-- 9. langchain_pg_embedding table (PGVector — vector embeddings)
-- Legacy import surface only. Active semantic data lives in versioned
-- embedding-space tables created from observed model dimensions.
CREATE TABLE IF NOT EXISTS public.langchain_pg_embedding (
    langchain_id      VARCHAR PRIMARY KEY,
    collection_id     UUID REFERENCES public.langchain_pg_collection(uuid) ON DELETE CASCADE,
    embedding         vector,
    content           VARCHAR,
    langchain_metadata  JSONB
);

-- GIN index for JSONB metadata queries on embeddings
CREATE INDEX IF NOT EXISTS ix_langchain_metadata_gin
    ON public.langchain_pg_embedding USING gin (langchain_metadata jsonb_path_ops);

-- 10. books table (cached public book metadata)
CREATE TABLE IF NOT EXISTS public.books (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(256) NOT NULL,
    subtitle        VARCHAR(256),
    authors         JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary         TEXT,
    rating          NUMERIC(3,1),
    rating_count    INTEGER,
    cover_url       VARCHAR(1024),
    source_name     VARCHAR(64) NOT NULL DEFAULT 'web',
    source_url      VARCHAR(1024) UNIQUE,
    external_id     VARCHAR(128),
    raw_data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_books_title ON public.books(title);
CREATE INDEX IF NOT EXISTS idx_books_source_name ON public.books(source_name);
CREATE INDEX IF NOT EXISTS idx_books_external_id ON public.books(external_id);
CREATE INDEX IF NOT EXISTS idx_books_last_seen_at ON public.books(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_books_raw_data_gin
    ON public.books USING gin (raw_data jsonb_path_ops);

-- 11. book_interactions table (user feedback and reading state)
CREATE TABLE IF NOT EXISTS public.book_interactions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    book_id           UUID REFERENCES public.books(id) ON DELETE SET NULL,
    book_title        VARCHAR(256),
    interaction_type  VARCHAR(32) NOT NULL,
    note              TEXT,
    rating            INTEGER,
    raw_data          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_book_interactions_user
ON public.book_interactions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_book_interactions_book
ON public.book_interactions(book_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_book_interactions_type
ON public.book_interactions(interaction_type);

-- 12. user_preference_profiles table (structured long-term reading memory)
CREATE TABLE IF NOT EXISTS public.user_preference_profiles (
    user_id           UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    preferred_tags    JSONB NOT NULL DEFAULT '[]'::jsonb,
    disliked_tags     JSONB NOT NULL DEFAULT '[]'::jsonb,
    favorite_authors  JSONB NOT NULL DEFAULT '[]'::jsonb,
    disliked_authors  JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes             TEXT NOT NULL DEFAULT '',
    profile_summary   TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_preference_profiles_preferred_tags_gin
    ON public.user_preference_profiles USING gin (preferred_tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_user_preference_profiles_favorite_authors_gin
    ON public.user_preference_profiles USING gin (favorite_authors jsonb_path_ops);

-- Analyze tables after index creation for query planner
ANALYZE public.users;
ANALYZE public.user_channels;
ANALYZE public.conversations;
ANALYZE public.models;
ANALYZE public.model_capability_checks;
ANALYZE public.providers;
ANALYZE public.trace_executions;
ANALYZE public.langchain_pg_collection;
ANALYZE public.langchain_pg_embedding;
ANALYZE public.books;
ANALYZE public.book_interactions;
ANALYZE public.user_preference_profiles;
