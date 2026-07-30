-- change_013_agent_capability_certifications.sql
-- Immutable, configuration-bound Agent mode certification history.

CREATE TABLE IF NOT EXISTS public.agent_capability_certifications (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id                    UUID NOT NULL REFERENCES public.models(id) ON DELETE CASCADE,
    provider                    VARCHAR(64) NOT NULL,
    provider_model_id           VARCHAR(256) NOT NULL,
    configuration_fingerprint   VARCHAR(64) NOT NULL,
    contract_version            VARCHAR(64) NOT NULL,
    certified                   BOOLEAN NOT NULL,
    checked_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    latency_ms                  INTEGER NOT NULL CHECK (latency_ms >= 0),
    cases                       JSONB NOT NULL DEFAULT '[]'::jsonb,
    failure_cases               JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_type                  VARCHAR(128),
    last_error                  TEXT,
    CONSTRAINT ck_agent_certification_fingerprint
        CHECK (configuration_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_certification_cases_array
        CHECK (jsonb_typeof(cases) = 'array'),
    CONSTRAINT ck_agent_certification_failures_array
        CHECK (jsonb_typeof(failure_cases) = 'array')
);

CREATE INDEX IF NOT EXISTS idx_agent_certification_current
ON public.agent_capability_certifications (
    model_id,
    configuration_fingerprint,
    contract_version,
    checked_at DESC
);

CREATE INDEX IF NOT EXISTS idx_agent_certification_outcome
ON public.agent_capability_certifications (certified, checked_at DESC);
