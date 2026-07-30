-- Authoritative conversation event journal.
-- LangGraph checkpoints remain recoverable runtime state, not chat history truth.

ALTER TABLE public.conversations
    ADD COLUMN IF NOT EXISTS journal_sequence BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS public.conversation_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL
                    REFERENCES public.users(id) ON DELETE CASCADE,
    thread_id       UUID NOT NULL
                    REFERENCES public.conversations(thread_id) ON DELETE CASCADE,
    request_id      VARCHAR(128) NOT NULL,
    exchange_id     UUID NOT NULL,
    sequence_no     BIGINT NOT NULL CHECK (sequence_no > 0),
    event_type      VARCHAR(32) NOT NULL
                    CHECK (
                        event_type IN (
                            'user_message',
                            'assistant_published',
                            'clarification_requested',
                            'turn_failed'
                        )
                    ),
    role            VARCHAR(16) NOT NULL
                    CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL CHECK (length(content) > 0),
    receipt_refs    JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_conversation_events_type_role
        CHECK (
            (event_type = 'user_message' AND role = 'user')
            OR
            (event_type IN ('assistant_published', 'clarification_requested')
                AND role = 'assistant')
            OR
            (event_type = 'turn_failed' AND role = 'system')
        ),
    CONSTRAINT uq_conversation_events_thread_sequence
        UNIQUE (thread_id, sequence_no),
    CONSTRAINT uq_conversation_events_request_type
        UNIQUE (thread_id, request_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_conversation_events_owner_sequence
    ON public.conversation_events(user_id, thread_id, sequence_no);

CREATE INDEX IF NOT EXISTS idx_conversation_events_exchange
    ON public.conversation_events(thread_id, exchange_id, sequence_no);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_events_request_terminal
    ON public.conversation_events(thread_id, request_id)
    WHERE event_type IN (
        'assistant_published',
        'clarification_requested',
        'turn_failed'
    );

COMMENT ON TABLE public.conversation_events IS
    'Immutable canonical conversation and turn lifecycle events';

COMMENT ON COLUMN public.conversations.journal_sequence IS
    'Per-thread sequence allocated under a conversation row lock';
