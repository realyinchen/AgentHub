-- init_database.sql
-- Idempotent: safe to run multiple times, no DROP, no destructive changes

-- =============================================================================
-- IMPORTANT: Configure your LLM and VLM models before initialization!
-- 
-- 1. First, configure your models in this file:
--    - Set the API keys for your providers (dashscope, zai, etc.)
--    - Adjust model_id, model_name as needed
--    - Set is_default=true for your preferred default LLM and VLM
--
-- 2. Then, configure other parameters in backend/.env:
--    - EMBEDDING_MODEL_NAME: Embedding model for vector store
--    - EMBEDDING_API_KEY: API key for embedding model
--    - Other API keys (Tavily, Amap, etc.)
--
-- Note: Embedding models are configured in backend/.env, not in this file.
-- =============================================================================

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

-- 3. models table (user maintains all model configurations)
-- Note: Embedding models are configured via .env file, not here
CREATE TABLE IF NOT EXISTS public.models (
    provider               VARCHAR(64) NOT NULL,      -- e.g. "dashscope", "zai"
    api_key                TEXT NOT NULL DEFAULT '',  -- encrypted by frontend
    model_type             VARCHAR(16) NOT NULL DEFAULT 'llm',  -- llm, vlm, embedding
    model_id               VARCHAR(128) PRIMARY KEY,  -- litellm model, e.g. "qwen3.5-27b"
    model_name             VARCHAR(64) NOT NULL,      -- display name, e.g. "qwen3.5-27b"
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

-- =============================================================================
-- Insert default models (idempotent)
-- IMPORTANT: Replace the empty api_key values with your actual API keys!
-- 
-- Provider order (alphabetically): dashscope, zai
-- If no default model is set, the first provider's model will be used as default.
-- =============================================================================

-- DashScope models (Alibaba Cloud)
-- Get your API key from: https://dashscope.console.aliyun.com/apiKey
INSERT INTO public.models (provider, api_key, model_type, model_id, model_name, thinking, is_default, is_active)
VALUES 
    ('dashscope', '', 'llm', 'dashscope/qwen3.5-27b', 'qwen3.5-27b', true, true, true),
    ('dashscope', '', 'vlm', 'dashscope/qwen-vl-max', 'qwen-vl-max', false, true, true)
ON CONFLICT (model_id) DO NOTHING;

-- ZhipuAI models (prefix: zai)
-- Get your API key from: https://open.bigmodel.cn/apikey
INSERT INTO public.models (provider, api_key, model_type, model_id, model_name, thinking, is_default, is_active)
VALUES 
    ('zai', '', 'llm', 'zai/glm-5', 'glm-5', true, false, true)
ON CONFLICT (model_id) DO NOTHING;

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

