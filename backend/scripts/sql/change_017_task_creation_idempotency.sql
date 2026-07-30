-- change_017_task_creation_idempotency.sql
-- Bind one durable task to one originating conversation request.

ALTER TABLE public.task_states
    ADD COLUMN IF NOT EXISTS origin_request_id VARCHAR(128);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_task_state_origin_request'
          AND conrelid = 'public.task_states'::regclass
    ) THEN
        ALTER TABLE public.task_states
            ADD CONSTRAINT uq_task_state_origin_request
            UNIQUE (thread_id, origin_request_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_task_states_origin_request
ON public.task_states (thread_id, origin_request_id)
WHERE origin_request_id IS NOT NULL;
