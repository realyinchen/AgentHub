-- database_change_001.sql
-- Add branching support for Grok-like chat (message_nodes + current_leaf_id)
-- Idempotent: safe to run multiple times

-- 1. Create message_nodes table FIRST (before referencing it)
CREATE TABLE IF NOT EXISTS public.message_nodes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id        UUID NOT NULL 
                     REFERENCES public.conversations(thread_id) ON DELETE CASCADE,
    role             VARCHAR(16) NOT NULL 
                     CHECK (role IN ('user', 'assistant')),
    content          TEXT NOT NULL,
    parent_id        UUID 
                     REFERENCES public.message_nodes(id) ON DELETE SET NULL,
    branch_index     INTEGER DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    tool_calls       JSONB,
    tool_call_status VARCHAR(16) 
                     CHECK (tool_call_status IN ('pending', 'completed', 'failed', NULL)),
    custom_data      JSONB
);

-- 2. Add current_leaf_id to conversations (AFTER message_nodes exists)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public'
          AND table_name = 'conversations'
          AND column_name = 'current_leaf_id'
    ) THEN
        ALTER TABLE public.conversations
        ADD COLUMN current_leaf_id UUID 
        REFERENCES public.message_nodes(id) ON DELETE SET NULL;
        
        RAISE NOTICE 'Added current_leaf_id to conversations';
    ELSE
        RAISE NOTICE 'current_leaf_id already exists → skipped';
    END IF;
END $$;

-- 3. Indexes (all idempotent)
CREATE INDEX IF NOT EXISTS idx_message_nodes_thread_id    
ON public.message_nodes (thread_id);

CREATE INDEX IF NOT EXISTS idx_message_nodes_parent_id    
ON public.message_nodes (parent_id);

CREATE INDEX IF NOT EXISTS idx_message_nodes_created_at   
ON public.message_nodes (created_at);

CREATE INDEX IF NOT EXISTS idx_message_nodes_branch_index 
ON public.message_nodes (branch_index);