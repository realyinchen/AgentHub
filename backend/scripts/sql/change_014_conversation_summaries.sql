-- change_014_conversation_summaries.sql
-- Immutable cumulative summaries derived only from ConversationJournal.

CREATE TABLE IF NOT EXISTS public.conversation_summaries (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    thread_id             UUID NOT NULL REFERENCES public.conversations(thread_id) ON DELETE CASCADE,
    from_sequence         BIGINT NOT NULL,
    to_sequence           BIGINT NOT NULL,
    previous_summary_id   UUID REFERENCES public.conversation_summaries(id) ON DELETE RESTRICT,
    structured_content    JSONB NOT NULL,
    source_hash           VARCHAR(64) NOT NULL,
    model_id              VARCHAR(256) NOT NULL,
    prompt_version        VARCHAR(64) NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_conversation_summary_range
        CHECK (from_sequence > 0 AND to_sequence >= from_sequence),
    CONSTRAINT ck_conversation_summary_source_hash
        CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_conversation_summary_content_object
        CHECK (jsonb_typeof(structured_content) = 'object'),
    CONSTRAINT uq_conversation_summary_derivation
        UNIQUE (thread_id, to_sequence, source_hash, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_conversation_summary_latest
ON public.conversation_summaries (thread_id, to_sequence DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_summary_previous
ON public.conversation_summaries (previous_summary_id);
