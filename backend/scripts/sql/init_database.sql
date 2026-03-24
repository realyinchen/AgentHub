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
    ('navigator', 'A smart navigation assistant based on AMap(高德地图)', true),
    ('rag-agent', 'A RAG Agent that can search local knowledge bases and online information.', true)
ON CONFLICT (agent_id) DO NOTHING;

-- 2. conversations table
CREATE TABLE IF NOT EXISTS public.conversations (
    thread_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        VARCHAR(64) NOT NULL,
    agent_id     VARCHAR(64) DEFAULT 'chatbot',
    is_deleted   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_conversations_deleted_updated 
ON public.conversations (is_deleted, updated_at DESC);