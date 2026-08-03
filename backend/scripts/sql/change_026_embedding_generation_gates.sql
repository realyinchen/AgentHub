-- Immutable calibration reports and atomic embedding-generation cutover ledger.

CREATE TABLE IF NOT EXISTS public.embedding_calibration_reports (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id                UUID NOT NULL
                            REFERENCES public.embedding_spaces(id)
                            ON DELETE RESTRICT,
    report_fingerprint      CHAR(64) NOT NULL UNIQUE,
    dataset_version         VARCHAR(128) NOT NULL,
    dataset_sha256          CHAR(64) NOT NULL,
    source_watermark        TIMESTAMPTZ NOT NULL,
    threshold               DOUBLE PRECISION NOT NULL
                            CHECK (threshold BETWEEN -1.0 AND 1.0),
    sample_count            INTEGER NOT NULL CHECK (sample_count > 0),
    positive_count          INTEGER NOT NULL CHECK (positive_count > 0),
    negative_count          INTEGER NOT NULL CHECK (negative_count > 0),
    precision_score         DOUBLE PRECISION NOT NULL
                            CHECK (precision_score BETWEEN 0.0 AND 1.0),
    recall_score            DOUBLE PRECISION NOT NULL
                            CHECK (recall_score BETWEEN 0.0 AND 1.0),
    f1_score                DOUBLE PRECISION NOT NULL
                            CHECK (f1_score BETWEEN 0.0 AND 1.0),
    score_distribution      JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_checks       JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                  VARCHAR(16) NOT NULL
                            CHECK (status IN ('passed', 'failed')),
    failure_codes           JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embedding_calibration_space_created
    ON public.embedding_calibration_reports (space_id, created_at DESC);

-- Support databases that received an earlier candidate form of change_026.
ALTER TABLE public.embedding_calibration_reports
    ADD COLUMN IF NOT EXISTS source_watermark TIMESTAMPTZ;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.embedding_calibration_reports
        WHERE source_watermark IS NULL
    ) THEN
        RAISE EXCEPTION
            'embedding calibration rows require a real source watermark';
    END IF;
    ALTER TABLE public.embedding_calibration_reports
        ALTER COLUMN source_watermark SET NOT NULL;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_embedding_calibration_space_dataset
    ON public.embedding_calibration_reports (space_id, dataset_sha256);

CREATE TABLE IF NOT EXISTS public.embedding_space_activations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purpose                 VARCHAR(32) NOT NULL
                            CHECK (
                                purpose IN ('routing', 'memory', 'documents')
                            ),
    action                  VARCHAR(16) NOT NULL
                            CHECK (action IN ('activate', 'rollback')),
    from_space_id           UUID
                            REFERENCES public.embedding_spaces(id)
                            ON DELETE RESTRICT,
    to_space_id             UUID NOT NULL
                            REFERENCES public.embedding_spaces(id)
                            ON DELETE RESTRICT,
    calibration_report_id   UUID NOT NULL
                            REFERENCES public.embedding_calibration_reports(id)
                            ON DELETE RESTRICT,
    idempotency_key         CHAR(64) NOT NULL UNIQUE,
    source_commit_sha       VARCHAR(40) NOT NULL DEFAULT '',
    reason                  VARCHAR(512) NOT NULL DEFAULT '',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embedding_activations_purpose_created
    ON public.embedding_space_activations (purpose, created_at DESC);

CREATE OR REPLACE FUNCTION public.reject_embedding_audit_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$;

DROP TRIGGER IF EXISTS trg_embedding_calibration_append_only
    ON public.embedding_calibration_reports;
CREATE TRIGGER trg_embedding_calibration_append_only
    BEFORE UPDATE OR DELETE ON public.embedding_calibration_reports
    FOR EACH ROW EXECUTE FUNCTION public.reject_embedding_audit_mutation();

DROP TRIGGER IF EXISTS trg_embedding_activation_append_only
    ON public.embedding_space_activations;
CREATE TRIGGER trg_embedding_activation_append_only
    BEFORE UPDATE OR DELETE ON public.embedding_space_activations
    FOR EACH ROW EXECUTE FUNCTION public.reject_embedding_audit_mutation();

COMMENT ON TABLE public.embedding_calibration_reports IS
    'Immutable generation-specific threshold and quality-gate reports';

COMMENT ON TABLE public.embedding_space_activations IS
    'Append-only receipts for atomic embedding generation activation and rollback';
