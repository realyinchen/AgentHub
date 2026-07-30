-- Durable Shadow eligibility is attached to the authoritative user event.
-- It is not chat metadata and is never projected to the model or UI.

ALTER TABLE public.conversation_events
    ADD COLUMN IF NOT EXISTS shadow_enrollment JSONB;

ALTER TABLE public.agent_shadow_observations
    ADD COLUMN IF NOT EXISTS violation_codes JSONB NOT NULL
    DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_conversation_events_shadow_enrollment'
          AND conrelid = 'public.conversation_events'::regclass
    ) THEN
        ALTER TABLE public.conversation_events
            ADD CONSTRAINT ck_conversation_events_shadow_enrollment
            CHECK (
                shadow_enrollment IS NULL
                OR (
                    event_type = 'user_message'
                    AND role = 'user'
                    AND jsonb_typeof(shadow_enrollment) = 'object'
                    AND shadow_enrollment->>'schema_version'
                        = 'agent-shadow-enrollment-v1'
                    AND jsonb_typeof(
                        shadow_enrollment->'controller_fingerprint'
                    ) = 'string'
                    AND length(
                        shadow_enrollment->>'controller_fingerprint'
                    ) = 64
                    AND (
                        shadow_enrollment->>'controller_fingerprint'
                    ) ~ '^[0-9a-f]{64}$'
                    AND jsonb_typeof(
                        shadow_enrollment->'prompt_version'
                    ) = 'string'
                    AND length(
                        shadow_enrollment->>'prompt_version'
                    ) BETWEEN 1 AND 64
                    AND jsonb_typeof(
                        shadow_enrollment->'model_id'
                    ) = 'string'
                    AND (
                        shadow_enrollment->>'model_id'
                    ) ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    AND jsonb_typeof(
                        shadow_enrollment->'model_name'
                    ) = 'string'
                    AND length(
                        shadow_enrollment->>'model_name'
                    ) BETWEEN 1 AND 256
                    AND jsonb_typeof(
                        shadow_enrollment->'timezone'
                    ) = 'string'
                    AND length(
                        shadow_enrollment->>'timezone'
                    ) BETWEEN 1 AND 64
                )
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_shadow_observation_violation_codes'
          AND conrelid = 'public.agent_shadow_observations'::regclass
    ) THEN
        ALTER TABLE public.agent_shadow_observations
            ADD CONSTRAINT ck_agent_shadow_observation_violation_codes
            CHECK (jsonb_typeof(violation_codes) = 'array');
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_conversation_events_shadow_window
    ON public.conversation_events (
        (shadow_enrollment->>'controller_fingerprint'),
        (shadow_enrollment->>'prompt_version'),
        created_at
    )
    WHERE shadow_enrollment IS NOT NULL;

COMMENT ON COLUMN public.conversation_events.shadow_enrollment IS
    'Immutable system-owned Shadow eligibility and recovery stamp; never model-visible';
