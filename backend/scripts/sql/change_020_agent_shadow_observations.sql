-- Bind certifications to the exact Controller prompt/schema contract and
-- persist immutable, de-identified Shadow observations.

ALTER TABLE public.agent_capability_certifications
    ADD COLUMN IF NOT EXISTS controller_fingerprint VARCHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_certification_controller_fingerprint'
    ) THEN
        ALTER TABLE public.agent_capability_certifications
            ADD CONSTRAINT ck_agent_certification_controller_fingerprint
            CHECK (
                controller_fingerprint IS NULL
                OR controller_fingerprint ~ '^[0-9a-f]{64}$'
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_certification_controller_current
ON public.agent_capability_certifications (
    model_id,
    configuration_fingerprint,
    contract_version,
    controller_fingerprint,
    checked_at DESC
);

CREATE TABLE IF NOT EXISTS public.agent_shadow_observations (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    observation_key                 VARCHAR(64) NOT NULL,
    user_id                         UUID NOT NULL
                                    REFERENCES public.users(id) ON DELETE CASCADE,
    thread_id                       UUID NOT NULL
                                    REFERENCES public.conversations(thread_id)
                                    ON DELETE CASCADE,
    request_id                      VARCHAR(128) NOT NULL,
    model_id                        UUID REFERENCES public.models(id)
                                    ON DELETE SET NULL,
    certification_id                UUID
                                    REFERENCES public.agent_capability_certifications(id)
                                    ON DELETE SET NULL,
    configuration_fingerprint       VARCHAR(64),
    controller_fingerprint          VARCHAR(64) NOT NULL,
    agent_core_contract_version     VARCHAR(64) NOT NULL,
    certification_contract_version VARCHAR(64) NOT NULL,
    prompt_version                  VARCHAR(64) NOT NULL,
    context_snapshot_hash           VARCHAR(64),
    input_evidence_hash             VARCHAR(64) NOT NULL,
    controller_status               VARCHAR(32) NOT NULL,
    output_mode                     VARCHAR(32),
    valid                           BOOLEAN,
    would_execute                   BOOLEAN NOT NULL DEFAULT FALSE,
    side_effect_count               INTEGER NOT NULL DEFAULT 0,
    latency_ms                      INTEGER NOT NULL,
    proposal_summary                JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan_summary                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    checks                          JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_hashes                    JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_shadow_observation_key
        UNIQUE (observation_key),
    CONSTRAINT ck_agent_shadow_observation_key
        CHECK (observation_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_shadow_observation_fingerprints
        CHECK (
            controller_fingerprint ~ '^[0-9a-f]{64}$'
            AND (
                configuration_fingerprint IS NULL
                OR configuration_fingerprint ~ '^[0-9a-f]{64}$'
            )
            AND (
                context_snapshot_hash IS NULL
                OR context_snapshot_hash ~ '^[0-9a-f]{64}$'
            )
            AND input_evidence_hash ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_agent_shadow_observation_status
        CHECK (
            controller_status IN (
                'denied',
                'shadow_valid',
                'shadow_invalid',
                'failed'
            )
        ),
    CONSTRAINT ck_agent_shadow_observation_counts
        CHECK (latency_ms >= 0 AND side_effect_count >= 0),
    CONSTRAINT ck_agent_shadow_observation_proposal_object
        CHECK (jsonb_typeof(proposal_summary) = 'object'),
    CONSTRAINT ck_agent_shadow_observation_plan_object
        CHECK (jsonb_typeof(plan_summary) = 'object'),
    CONSTRAINT ck_agent_shadow_observation_checks_array
        CHECK (jsonb_typeof(checks) = 'array'),
    CONSTRAINT ck_agent_shadow_observation_errors_array
        CHECK (jsonb_typeof(error_hashes) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_agent_shadow_observation_window
ON public.agent_shadow_observations (
    controller_fingerprint,
    created_at
);

CREATE INDEX IF NOT EXISTS idx_agent_shadow_observation_request
ON public.agent_shadow_observations (thread_id, request_id);
