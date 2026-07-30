-- change_018_task_waiting_and_projection.sql
-- Exact-once TaskState receipt projection and explicit waiting receipts.

ALTER TABLE public.task_states
    ADD COLUMN IF NOT EXISTS projected_receipt_refs JSONB
    NOT NULL DEFAULT '[]'::jsonb;

UPDATE public.task_states
SET projected_receipt_refs = completed_receipt_refs
WHERE projected_receipt_refs = '[]'::jsonb
  AND completed_receipt_refs <> '[]'::jsonb;

UPDATE public.task_states
SET recovery_cursor = jsonb_array_length(projected_receipt_refs)
WHERE recovery_cursor <> jsonb_array_length(projected_receipt_refs);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_task_projected_receipt_refs_array'
          AND conrelid = 'public.task_states'::regclass
    ) THEN
        ALTER TABLE public.task_states
            ADD CONSTRAINT ck_task_projected_receipt_refs_array
            CHECK (jsonb_typeof(projected_receipt_refs) = 'array');
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_task_cursor_matches_projection'
          AND conrelid = 'public.task_states'::regclass
    ) THEN
        ALTER TABLE public.task_states
            ADD CONSTRAINT ck_task_cursor_matches_projection
            CHECK (
                recovery_cursor =
                jsonb_array_length(projected_receipt_refs)
            );
    END IF;
END $$;

ALTER TABLE public.action_execution_receipts
    DROP CONSTRAINT IF EXISTS ck_action_receipt_status;

ALTER TABLE public.action_execution_receipts
    ADD CONSTRAINT ck_action_receipt_status
    CHECK (
        status IN (
            'completed', 'failed', 'blocked', 'skipped', 'waiting'
        )
    );
