-- change_016_task_state_and_receipts.sql
-- Versioned cross-turn plans, leased task projection, immutable action receipts.

CREATE TABLE IF NOT EXISTS public.task_states (
    task_id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    thread_id                   UUID NOT NULL REFERENCES public.conversations(thread_id) ON DELETE CASCADE,
    status                      VARCHAR(32) NOT NULL DEFAULT 'pending',
    current_plan_version_id     UUID,
    current_action_id           VARCHAR(128),
    completed_receipt_refs      JSONB NOT NULL DEFAULT '[]'::jsonb,
    waiting_reason              TEXT,
    pending_clarification       JSONB,
    recovery_cursor             BIGINT NOT NULL DEFAULT 0,
    lease_owner                 VARCHAR(128),
    lease_expires_at            TIMESTAMPTZ,
    terminal_error              JSONB,
    state_version               BIGINT NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_task_state_status
        CHECK (
            status IN (
                'pending', 'running', 'waiting',
                'completed', 'failed', 'cancelled'
            )
        ),
    CONSTRAINT ck_task_state_cursor CHECK (recovery_cursor >= 0),
    CONSTRAINT ck_task_state_version CHECK (state_version >= 0),
    CONSTRAINT ck_task_receipt_refs_array
        CHECK (jsonb_typeof(completed_receipt_refs) = 'array')
);

CREATE TABLE IF NOT EXISTS public.task_plan_versions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id               UUID NOT NULL REFERENCES public.task_states(task_id) ON DELETE CASCADE,
    version_no            INTEGER NOT NULL CHECK (version_no > 0),
    previous_version_id   UUID REFERENCES public.task_plan_versions(id) ON DELETE RESTRICT,
    plan_json             JSONB NOT NULL,
    source                VARCHAR(32) NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_task_plan_version_number UNIQUE (task_id, version_no),
    CONSTRAINT ck_task_plan_source
        CHECK (source IN ('controller', 'recovery', 'operator')),
    CONSTRAINT ck_task_plan_json_object
        CHECK (jsonb_typeof(plan_json) = 'object')
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_task_state_current_plan_version'
    ) THEN
        ALTER TABLE public.task_states
            ADD CONSTRAINT fk_task_state_current_plan_version
            FOREIGN KEY (current_plan_version_id)
            REFERENCES public.task_plan_versions(id)
            ON DELETE RESTRICT;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.action_execution_receipts (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key       VARCHAR(64) NOT NULL UNIQUE,
    task_id               UUID REFERENCES public.task_states(task_id) ON DELETE CASCADE,
    plan_version_id       UUID REFERENCES public.task_plan_versions(id) ON DELETE SET NULL,
    plan_id               VARCHAR(128) NOT NULL,
    action_id             VARCHAR(128) NOT NULL,
    request_id            VARCHAR(128) NOT NULL,
    capability            VARCHAR(128) NOT NULL,
    operation             VARCHAR(128) NOT NULL,
    status                VARCHAR(32) NOT NULL,
    receipt_json          JSONB NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_action_receipt_key
        CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_action_receipt_status
        CHECK (status IN ('completed', 'failed', 'blocked', 'skipped')),
    CONSTRAINT ck_action_receipt_json_object
        CHECK (jsonb_typeof(receipt_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_task_states_owner_status
ON public.task_states (user_id, thread_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_states_lease
ON public.task_states (status, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_task_plan_versions_current
ON public.task_plan_versions (task_id, version_no DESC);

CREATE INDEX IF NOT EXISTS idx_action_receipts_task
ON public.action_execution_receipts (task_id, created_at, action_id);

CREATE INDEX IF NOT EXISTS idx_action_receipts_plan
ON public.action_execution_receipts (plan_id, action_id);
