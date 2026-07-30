-- Pin asynchronous Shadow context to the originating user Journal event.
-- change_020 is already append-only history and is intentionally unchanged.

ALTER TABLE public.agent_shadow_observations
    ADD COLUMN IF NOT EXISTS journal_sequence_watermark BIGINT;

UPDATE public.agent_shadow_observations o
SET journal_sequence_watermark = e.sequence_no
FROM public.conversation_events e
WHERE o.journal_sequence_watermark IS NULL
  AND e.thread_id = o.thread_id
  AND e.request_id = o.request_id
  AND e.event_type = 'user_message';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.agent_shadow_observations
        WHERE journal_sequence_watermark IS NULL
           OR journal_sequence_watermark <= 0
    ) THEN
        RAISE EXCEPTION
            'agent_shadow_observations contain unresolved Journal watermarks';
    END IF;
END
$$;

ALTER TABLE public.agent_shadow_observations
    ALTER COLUMN journal_sequence_watermark SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_shadow_observation_watermark'
    ) THEN
        ALTER TABLE public.agent_shadow_observations
            ADD CONSTRAINT ck_agent_shadow_observation_watermark
            CHECK (journal_sequence_watermark > 0);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_shadow_observation_watermark
ON public.agent_shadow_observations (
    thread_id,
    journal_sequence_watermark
);
