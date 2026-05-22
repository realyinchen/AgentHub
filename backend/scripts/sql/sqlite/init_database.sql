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
    user_id          VARCHAR(128) NOT NULL,
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

-- User-scoped index: list active conversations for a user, sorted by last update
CREATE INDEX IF NOT EXISTS idx_conv_user_active 
ON conversations (user_id, is_deleted, updated_at DESC);

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
    priority               INTEGER NOT NULL DEFAULT 0,
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

-- 5. trace_executions table (persisted DAG snapshots for offline trace viewing)
-- Each row = one agent invocation (user→agent turn), identified by request_id.
-- Contains per-request token usage, model used, and the full ExecutionDag.
CREATE TABLE IF NOT EXISTS trace_executions (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    thread_id       TEXT NOT NULL REFERENCES conversations(thread_id) ON DELETE CASCADE,
    agent_id        VARCHAR(64) NOT NULL,
    request_id      VARCHAR(128) NOT NULL,
    model_name      VARCHAR(128),              -- LLM model used for this turn
    dag_data        TEXT NOT NULL,              -- JSON stored as TEXT (complete ExecutionDag)
    total_steps     INTEGER NOT NULL DEFAULT 0,
    -- Per-request token usage
    input_tokens    BIGINT NOT NULL DEFAULT 0,
    cache_read      BIGINT NOT NULL DEFAULT 0,
    output_tokens   BIGINT NOT NULL DEFAULT 0,
    reasoning       BIGINT NOT NULL DEFAULT 0,
    total_tokens    BIGINT NOT NULL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Indexes for trace_executions
CREATE INDEX IF NOT EXISTS idx_trace_exec_thread_id 
ON trace_executions (thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_trace_exec_agent_id 
ON trace_executions (agent_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trace_exec_request_id 
ON trace_executions (request_id);