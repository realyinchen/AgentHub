-- Bind Agent capability certifications to the exact source release.
-- Historical certifications remain nullable and are never admitted as v3.

ALTER TABLE public.agent_capability_certifications
    ADD COLUMN IF NOT EXISTS source_commit_sha VARCHAR(40);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_certification_source_commit'
    ) THEN
        ALTER TABLE public.agent_capability_certifications
            ADD CONSTRAINT ck_agent_certification_source_commit
            CHECK (
                source_commit_sha IS NULL
                OR source_commit_sha ~ '^[0-9a-f]{40}$'
            );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_certification_v3_release_required'
    ) THEN
        ALTER TABLE public.agent_capability_certifications
            ADD CONSTRAINT ck_agent_certification_v3_release_required
            CHECK (
                contract_version <> 'agent-capability-v3'
                OR source_commit_sha IS NOT NULL
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_certification_release_current
ON public.agent_capability_certifications (
    model_id,
    configuration_fingerprint,
    contract_version,
    controller_fingerprint,
    source_commit_sha,
    checked_at DESC
);

COMMENT ON COLUMN public.agent_capability_certifications.source_commit_sha IS
'Exact clean Git commit that executed this immutable certification; NULL only for historical records.';
