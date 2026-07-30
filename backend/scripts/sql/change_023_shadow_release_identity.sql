-- Bind every current Shadow enrollment and observation to one deployment commit.
-- Historical v1 enrollments/observations remain readable but are not Gate-eligible.

ALTER TABLE public.agent_shadow_observations
    ADD COLUMN IF NOT EXISTS source_commit_sha VARCHAR(40);

DO $$
DECLARE
    current_definition TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid)
    INTO current_definition
    FROM pg_constraint
    WHERE conname = 'ck_conversation_events_shadow_enrollment'
      AND conrelid = 'public.conversation_events'::regclass;

    IF current_definition IS NOT NULL
       AND current_definition NOT LIKE '%agent-shadow-enrollment-v2%' THEN
        ALTER TABLE public.conversation_events
            DROP CONSTRAINT ck_conversation_events_shadow_enrollment;
    END IF;

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
                    AND (
                        (
                            shadow_enrollment->>'schema_version'
                                = 'agent-shadow-enrollment-v1'
                            AND NOT (
                                shadow_enrollment ? 'source_commit_sha'
                            )
                        )
                        OR (
                            shadow_enrollment->>'schema_version'
                                = 'agent-shadow-enrollment-v2'
                            AND jsonb_typeof(
                                shadow_enrollment->'source_commit_sha'
                            ) = 'string'
                            AND (
                                shadow_enrollment->>'source_commit_sha'
                            ) ~ '^[0-9a-f]{40}$'
                        )
                    )
                    AND jsonb_typeof(
                        shadow_enrollment->'controller_fingerprint'
                    ) = 'string'
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
        WHERE conname = 'ck_agent_shadow_observation_source_commit'
          AND conrelid = 'public.agent_shadow_observations'::regclass
    ) THEN
        ALTER TABLE public.agent_shadow_observations
            ADD CONSTRAINT ck_agent_shadow_observation_source_commit
            CHECK (
                source_commit_sha IS NULL
                OR source_commit_sha ~ '^[0-9a-f]{40}$'
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_conversation_events_shadow_release_window
    ON public.conversation_events (
        (shadow_enrollment->>'source_commit_sha'),
        (shadow_enrollment->>'controller_fingerprint'),
        (shadow_enrollment->>'prompt_version'),
        created_at
    )
    WHERE shadow_enrollment->>'schema_version'
        = 'agent-shadow-enrollment-v2';

CREATE INDEX IF NOT EXISTS idx_agent_shadow_observation_release_window
    ON public.agent_shadow_observations (
        source_commit_sha,
        controller_fingerprint,
        created_at
    )
    WHERE source_commit_sha IS NOT NULL;

COMMENT ON COLUMN public.agent_shadow_observations.source_commit_sha IS
    'Exact deployment Git commit copied from the immutable v2 Shadow enrollment';
