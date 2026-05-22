-- init_database.sql
-- Idempotent: safe to run multiple times, no DROP, no destructive changes

-- 1. agents table
CREATE TABLE IF NOT EXISTS public.agents (
    agent_id     VARCHAR(64) PRIMARY KEY,
    description  VARCHAR(1024) NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default agents (idempotent)
INSERT INTO public.agents (agent_id, description, is_active)
VALUES 
    ('chatbot',   'A Simple chatbot', true),
    ('navigator', 'A smart navigation assistant', true)
ON CONFLICT (agent_id) DO NOTHING;

-- 2. conversations table
CREATE TABLE IF NOT EXISTS public.conversations (
    thread_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          VARCHAR(128) NOT NULL,
    title            VARCHAR(64) NOT NULL,
    agent_id         VARCHAR(64) DEFAULT 'chatbot',
    is_deleted       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    
    -- Token usage fields (cumulative for the conversation)
    input_tokens     BIGINT NOT NULL DEFAULT 0,
    cache_read       BIGINT NOT NULL DEFAULT 0,
    output_tokens    BIGINT NOT NULL DEFAULT 0,
    reasoning        BIGINT NOT NULL DEFAULT 0,
    total_tokens     BIGINT NOT NULL DEFAULT 0
);

-- User-scoped index: list active conversations for a user, sorted by last update
CREATE INDEX IF NOT EXISTS idx_conv_user_active 
ON public.conversations (user_id, is_deleted, updated_at DESC);

-- Covering index for user-scoped conversation list (avoids table lookups)
CREATE INDEX IF NOT EXISTS idx_conv_user_list 
ON public.conversations (user_id, is_deleted, updated_at DESC) 
INCLUDE (thread_id, title, agent_id, created_at, input_tokens, cache_read, output_tokens, reasoning, total_tokens)
WHERE is_deleted = FALSE;

-- Index for agent_id lookups (used in conversation filtering)
CREATE INDEX IF NOT EXISTS idx_conversations_agent_id 
ON public.conversations (agent_id) 
WHERE is_deleted = FALSE;

-- Index for pagination and sorting by created_at
CREATE INDEX IF NOT EXISTS idx_conversations_created_at 
ON public.conversations (created_at DESC) 
WHERE is_deleted = FALSE;

-- 3. providers table (stores provider API keys and base URLs)
CREATE TABLE IF NOT EXISTS public.providers (
    provider               VARCHAR(64) PRIMARY KEY,   -- e.g. "dashscope", "zai", "openai-compatible"
    api_key                TEXT NOT NULL DEFAULT '',  -- encrypted API key
    base_url               VARCHAR(512),              -- base URL for OpenAI-Compatible providers
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

-- ZAI provider
-- Get your API key from: https://open.bigmodel.cn/apikey
INSERT INTO public.providers (provider, api_key, is_openai_compatible)
VALUES ('zai', '', false)
ON CONFLICT (provider) DO NOTHING;

-- 4. models table (user maintains all model configurations)
-- Note: api_key is now stored in providers table
CREATE TABLE IF NOT EXISTS public.models (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),  -- UUID primary key
    provider               VARCHAR(64) NOT NULL REFERENCES public.providers(provider),  -- FK to providers
    model_type             VARCHAR(16) NOT NULL DEFAULT 'llm',  -- llm, vlm, embedding
    model_id               VARCHAR(128) NOT NULL UNIQUE,  -- full model id with provider prefix, e.g. "dashscope/qwen3.5-27b"
    thinking               BOOLEAN NOT NULL DEFAULT FALSE,  -- whether supports thinking mode
    priority               INTEGER NOT NULL DEFAULT 0,  -- fallback priority (higher = preferred)
    is_default             BOOLEAN NOT NULL DEFAULT FALSE,
    is_active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for models
CREATE INDEX IF NOT EXISTS idx_models_provider ON public.models(provider);
CREATE INDEX IF NOT EXISTS idx_models_model_type ON public.models(model_type);
CREATE INDEX IF NOT EXISTS idx_models_thinking ON public.models(thinking);
CREATE INDEX IF NOT EXISTS idx_models_is_active ON public.models(is_active);
CREATE INDEX IF NOT EXISTS idx_models_is_default ON public.models(is_default);
CREATE UNIQUE INDEX IF NOT EXISTS idx_models_model_id ON public.models(model_id);

-- =============================================================================
-- Models should be configured via web UI after providers are set up
-- No default models are inserted - configure them in the application
-- =============================================================================

-- 5. trace_executions table (persisted DAG snapshots for offline trace viewing)
-- Each row = one agent invocation (user→agent turn), identified by request_id.
-- Contains per-request token usage, model used, and the full ExecutionDag.
CREATE TABLE IF NOT EXISTS public.trace_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id       UUID NOT NULL REFERENCES public.conversations(thread_id) ON DELETE CASCADE,
    agent_id        VARCHAR(64) NOT NULL,
    request_id      VARCHAR(128) NOT NULL,
    model_name      VARCHAR(128),              -- LLM model used for this turn
    dag_data        JSONB NOT NULL,             -- Complete ExecutionDag as JSONB
    total_steps     INTEGER NOT NULL DEFAULT 0,
    -- Per-request token usage
    input_tokens    BIGINT NOT NULL DEFAULT 0,
    cache_read      BIGINT NOT NULL DEFAULT 0,
    output_tokens   BIGINT NOT NULL DEFAULT 0,
    reasoning       BIGINT NOT NULL DEFAULT 0,
    total_tokens    BIGINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for trace_executions
CREATE INDEX IF NOT EXISTS idx_trace_exec_thread_id
ON public.trace_executions (thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trace_exec_agent_id
ON public.trace_executions (agent_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trace_exec_request_id
ON public.trace_executions (request_id);

-- Analyze tables after index creation for query planner
ANALYZE public.conversations;
ANALYZE public.models;
ANALYZE public.providers;
ANALYZE public.trace_executions;