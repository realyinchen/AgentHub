-- Linear, app-owned version chains for canonical long-term memory.
-- Columns remain nullable so legacy memory_events can be audited and backfilled.

ALTER TABLE public.memory_events
    ADD COLUMN IF NOT EXISTS chain_id UUID,
    ADD COLUMN IF NOT EXISTS schema_key VARCHAR(128),
    ADD COLUMN IF NOT EXISTS memory_key VARCHAR(256),
    ADD COLUMN IF NOT EXISTS version_no INTEGER,
    ADD COLUMN IF NOT EXISTS operation VARCHAR(16),
    ADD COLUMN IF NOT EXISTS previous_version_id UUID,
    ADD COLUMN IF NOT EXISTS source_event_id UUID,
    ADD COLUMN IF NOT EXISTS receipt_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS canonical_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS schema_version INTEGER,
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_memory_events_previous_version'
    ) THEN
        ALTER TABLE public.memory_events
            ADD CONSTRAINT fk_memory_events_previous_version
            FOREIGN KEY (previous_version_id)
            REFERENCES public.memory_events(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_memory_events_source_event'
    ) THEN
        ALTER TABLE public.memory_events
            ADD CONSTRAINT fk_memory_events_source_event
            FOREIGN KEY (source_event_id)
            REFERENCES public.conversation_events(id)
            ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_memory_events_v2_operation'
    ) THEN
        ALTER TABLE public.memory_events
            ADD CONSTRAINT ck_memory_events_v2_operation
            CHECK (
                operation IS NULL
                OR operation IN ('create', 'correct', 'supersede', 'forget')
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_memory_events_v2_version_positive'
    ) THEN
        ALTER TABLE public.memory_events
            ADD CONSTRAINT ck_memory_events_v2_version_positive
            CHECK (version_no IS NULL OR version_no > 0);
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_events_v2_chain_version
    ON public.memory_events(chain_id, version_no)
    WHERE chain_id IS NOT NULL AND version_no IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_events_v2_active_head
    ON public.memory_events(user_id, memory_key)
    WHERE memory_key IS NOT NULL AND superseded_by IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_events_v2_receipt_key
    ON public.memory_events(user_id, receipt_id, memory_key)
    WHERE receipt_id IS NOT NULL AND memory_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_events_v2_current
    ON public.memory_events(user_id, schema_key, memory_key)
    WHERE (
        memory_key IS NOT NULL
        AND superseded_by IS NULL
        AND is_deleted = FALSE
        AND operation != 'forget'
    );

CREATE INDEX IF NOT EXISTS idx_memory_events_v2_source_event
    ON public.memory_events(source_event_id)
    WHERE source_event_id IS NOT NULL;

COMMENT ON COLUMN public.memory_events.memory_key IS
    'System-canonicalized fact identity; never supplied by the model';

COMMENT ON COLUMN public.memory_events.canonical_hash IS
    'Hash of canonical schema, subject, value, and qualifiers';
