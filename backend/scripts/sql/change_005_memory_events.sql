-- change_005_memory_events.sql
-- Idempotent upgrade for app-owned, agent-managed memory.

CREATE TABLE IF NOT EXISTS public.memory_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    thread_id       UUID REFERENCES public.conversations(thread_id) ON DELETE SET NULL,
    type            VARCHAR(32) NOT NULL,
    subject         VARCHAR(64) NOT NULL,
    value           TEXT NOT NULL,
    polarity        VARCHAR(32) NOT NULL DEFAULT 'neutral',
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    source          VARCHAR(32) NOT NULL DEFAULT 'chat_turn',
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    revision_of     UUID REFERENCES public.memory_events(id) ON DELETE SET NULL,
    superseded_by   UUID REFERENCES public.memory_events(id) ON DELETE SET NULL,
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_events_user_active
ON public.memory_events(user_id, type, subject, created_at DESC)
WHERE is_deleted = FALSE AND superseded_by IS NULL;

CREATE INDEX IF NOT EXISTS idx_memory_events_thread
ON public.memory_events(thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_events_revision
ON public.memory_events(revision_of);

CREATE INDEX IF NOT EXISTS idx_memory_events_superseded
ON public.memory_events(superseded_by);

CREATE INDEX IF NOT EXISTS idx_memory_events_metadata_gin
ON public.memory_events USING gin (metadata jsonb_path_ops);

ANALYZE public.memory_events;
