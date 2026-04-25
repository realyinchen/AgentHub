-- init_database_sqlite.sql
-- SQLite version of init_database.sql
-- Idempotent: safe to run multiple times, no DROP, no destructive changes

-- 1. agents table
CREATE TABLE IF NOT EXISTS agents (
    agent_id     VARCHAR(64) PRIMARY KEY,
    description  VARCHAR(1024) NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

-- Insert default agents (idempotent)
INSERT OR IGNORE INTO agents (agent_id, description, is_active)
VALUES 
    ('chatbot',   'A Simple chatbot', 1),
    ('navigator', 'A smart navigation assistant', 1);

-- 2. conversations table
CREATE TABLE IF NOT EXISTS conversations (
    thread_id        TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    title            VARCHAR(64) NOT NULL,
    agent_id         VARCHAR(64) DEFAULT 'chatbot',
    is_deleted       BOOLEAN NOT NULL DEFAULT 0,
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now')),
    
    -- Token usage fields (cumulative for the conversation)
    input_tokens     BIGINT NOT NULL DEFAULT 0,
    cache_read       BIGINT NOT NULL DEFAULT 0,
    output_tokens    BIGINT NOT NULL DEFAULT 0,
    reasoning        BIGINT NOT NULL DEFAULT 0,
    total_tokens     BIGINT NOT NULL DEFAULT 0
);

-- Index for conversations
CREATE INDEX IF NOT EXISTS idx_conversations_deleted_updated 
ON conversations (is_deleted, updated_at DESC);

-- Index for agent_id lookups
CREATE INDEX IF NOT EXISTS idx_conversations_agent_id 
ON conversations (agent_id);

-- Index for pagination and sorting by created_at
CREATE INDEX IF NOT EXISTS idx_conversations_created_at 
ON conversations (created_at DESC);

-- 3. providers table (stores provider API keys and base URLs)
CREATE TABLE IF NOT EXISTS providers (
    provider               VARCHAR(64) PRIMARY KEY,   -- e.g. "dashscope", "zai", "openai-compatible"
    api_key                TEXT NOT NULL DEFAULT '',   -- encrypted API key
    base_url               VARCHAR(512),              -- base URL for OpenAI-Compatible providers
    is_openai_compatible   BOOLEAN NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for providers
CREATE INDEX IF NOT EXISTS idx_providers_is_openai_compatible ON providers(is_openai_compatible);

-- =============================================================================
-- Insert default providers (idempotent)
-- =============================================================================

-- DashScope provider (Alibaba Cloud)
INSERT OR IGNORE INTO providers (provider, api_key, is_openai_compatible)
VALUES ('dashscope', '', 0);

-- ZAI provider
INSERT OR IGNORE INTO providers (provider, api_key, is_openai_compatible)
VALUES ('zai', '', 0);

-- 4. models table (user maintains all model configurations)
CREATE TABLE IF NOT EXISTS models (
    id                     TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    provider               VARCHAR(64) NOT NULL REFERENCES providers(provider),
    model_type             VARCHAR(16) NOT NULL DEFAULT 'llm',
    model_id               VARCHAR(128) NOT NULL UNIQUE,
    thinking               BOOLEAN NOT NULL DEFAULT 0,
    is_default             BOOLEAN NOT NULL DEFAULT 0,
    is_active              BOOLEAN NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for models
CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider);
CREATE INDEX IF NOT EXISTS idx_models_model_type ON models(model_type);
CREATE INDEX IF NOT EXISTS idx_models_thinking ON models(thinking);
CREATE INDEX IF NOT EXISTS idx_models_is_active ON models(is_active);
CREATE INDEX IF NOT EXISTS idx_models_is_default ON models(is_default);
CREATE UNIQUE INDEX IF NOT EXISTS idx_models_model_id ON models(model_id);

-- 5. message_steps table (agent execution sequence for sidebar)
CREATE TABLE IF NOT EXISTS message_steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id       TEXT NOT NULL REFERENCES conversations(thread_id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL,
    step_number     INTEGER NOT NULL,
    message_type    VARCHAR(16) NOT NULL,
    
    -- Tool call/result fields
    tool_name       VARCHAR(128),
    tool_args       TEXT,           -- JSON stored as TEXT
    tool_output     TEXT,
    tool_call_id    VARCHAR(128),
    
    -- AI response fields
    content         TEXT,
    thinking        TEXT,
    tool_calls      TEXT,           -- JSON stored as TEXT
    
    created_at      TEXT DEFAULT (datetime('now')),
    
    CONSTRAINT unique_thread_session_step UNIQUE (thread_id, session_id, step_number)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_message_steps_session ON message_steps(session_id);
CREATE INDEX IF NOT EXISTS idx_message_steps_type ON message_steps(message_type);

-- Composite index for message steps lookup
CREATE INDEX IF NOT EXISTS idx_message_steps_thread_session_step 
ON message_steps (thread_id, session_id, step_number);

-- Index for message steps pagination
CREATE INDEX IF NOT EXISTS idx_message_steps_created_at 
ON message_steps (created_at DESC);

-- Index for tool_name lookups
CREATE INDEX IF NOT EXISTS idx_message_steps_tool_name 
ON message_steps (tool_name);