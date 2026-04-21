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
    ('navigator', 'A smart navigation assistant based on AMap(高德地图)', true)
ON CONFLICT (agent_id) DO NOTHING;

-- 2. conversations table
CREATE TABLE IF NOT EXISTS public.conversations (
    thread_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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

-- Index for conversations
CREATE INDEX IF NOT EXISTS idx_conversations_deleted_updated 
ON public.conversations (is_deleted, updated_at DESC);

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

-- ZhipuAI provider
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

-- 4. message_steps table (agent execution sequence for sidebar)
-- Stores each step of agent execution: human messages, tool calls, tool results, and AI responses
-- Each session (conversation turn) has a unique session_id to group steps together
CREATE TABLE IF NOT EXISTS public.message_steps (
    id              BIGSERIAL PRIMARY KEY,
    thread_id       UUID NOT NULL REFERENCES public.conversations(thread_id) ON DELETE CASCADE,
    session_id      UUID NOT NULL,         -- Groups steps by conversation turn
    step_number     INTEGER NOT NULL,
    message_type    VARCHAR(16) NOT NULL,  -- 'human', 'ai', 'tool'
    
    -- Tool call/result fields
    tool_name       VARCHAR(128),          -- Tool name (e.g., "get_weather")
    tool_args       JSONB,                 -- Tool call arguments
    tool_output     TEXT,                  -- Tool execution result
    tool_call_id    VARCHAR(128),          -- Tool call ID for matching call with result
    
    -- AI response fields
    content         TEXT,                  -- Message content (human or AI)
    thinking        TEXT,                  -- Thinking/reasoning content (for AI messages)
    tool_calls      JSONB,                 -- Tool calls from AI (for AI messages with tool calls)
    
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT unique_thread_session_step UNIQUE (thread_id, session_id, step_number)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_message_steps_thread ON public.message_steps(thread_id);
CREATE INDEX IF NOT EXISTS idx_message_steps_session ON public.message_steps(session_id);
CREATE INDEX IF NOT EXISTS idx_message_steps_type ON public.message_steps(message_type);

