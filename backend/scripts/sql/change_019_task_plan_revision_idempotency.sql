-- change_019_task_plan_revision_idempotency.sql
-- Bind one immutable task plan revision to one originating request.

ALTER TABLE public.task_plan_versions
    ADD COLUMN IF NOT EXISTS origin_request_id VARCHAR(128);

CREATE UNIQUE INDEX IF NOT EXISTS uq_task_plan_revision_origin_request
ON public.task_plan_versions (task_id, origin_request_id)
WHERE origin_request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_task_plan_revision_origin_request
ON public.task_plan_versions (origin_request_id, task_id)
WHERE origin_request_id IS NOT NULL;
