-- change_008_recommendation_events.sql
-- Durable recommendation behavior signals. These are recommendation state,
-- not long-term memory and not research state.

CREATE TABLE IF NOT EXISTS public.recommendation_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    thread_id         UUID REFERENCES public.conversations(thread_id) ON DELETE SET NULL,
    request_id        VARCHAR(128),
    message_id        VARCHAR(128),
    book_id           UUID REFERENCES public.books(id) ON DELETE SET NULL,
    book_title        VARCHAR(256),
    event_type        VARCHAR(32) NOT NULL,
    signal_polarity   VARCHAR(16) NOT NULL DEFAULT 'neutral',
    signal_strength   NUMERIC(4,3) NOT NULL DEFAULT 0.000,
    source            VARCHAR(32) NOT NULL DEFAULT 'agent_tool',
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_recommendation_events_type CHECK (
        event_type IN (
            'candidate_retrieved',
            'recommended',
            'followup_suggested',
            'followup_clicked',
            'followup_matched',
            'detail_requested',
            'want_to_read',
            'read',
            'liked',
            'disliked',
            'not_interested',
            'suppressed'
        )
    ),
    CONSTRAINT chk_recommendation_signal_polarity CHECK (
        signal_polarity IN ('positive', 'negative', 'neutral')
    ),
    CONSTRAINT chk_recommendation_signal_source CHECK (
        source IN ('agent_tool', 'book_feedback', 'followup_question', 'api', 'system')
    ),
    CONSTRAINT chk_recommendation_signal_strength CHECK (
        signal_strength >= 0.000 AND signal_strength <= 1.000
    )
);

CREATE INDEX IF NOT EXISTS idx_recommendation_events_user_created
ON public.recommendation_events(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_recommendation_events_book_created
ON public.recommendation_events(book_id, created_at DESC)
WHERE book_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recommendation_events_title
ON public.recommendation_events(user_id, lower(book_title), created_at DESC)
WHERE book_title IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recommendation_events_type
ON public.recommendation_events(event_type);

CREATE INDEX IF NOT EXISTS idx_recommendation_events_metadata_gin
ON public.recommendation_events USING gin (metadata jsonb_path_ops);

ANALYZE public.recommendation_events;
