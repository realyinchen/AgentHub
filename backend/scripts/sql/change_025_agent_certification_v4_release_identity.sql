-- Require exact source identity for production-equivalent Agent capability v4.
-- Historical v1/v2/v3 certifications remain immutable and readable.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_certification_v4_release_required'
    ) THEN
        ALTER TABLE public.agent_capability_certifications
            ADD CONSTRAINT ck_agent_certification_v4_release_required
            CHECK (
                contract_version <> 'agent-capability-v4'
                OR source_commit_sha IS NOT NULL
            );
    END IF;
END
$$;

COMMENT ON CONSTRAINT ck_agent_certification_v4_release_required
ON public.agent_capability_certifications IS
'Agent capability v4 certification is valid only when bound to an exact clean source commit.';
